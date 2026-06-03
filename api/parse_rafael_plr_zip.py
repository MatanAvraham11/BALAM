"""
Rafael PLR/ZIP parser.

Supported ZIP layouts:

    TransferRequest_*.zip            optional outer wrapper
    └── <id>_1_PRODUCT.ZIP           product ZIP
        └── data/files/
            ├── PLReport_<PN>_*.zip  nested report ZIPs parsed by this module
            │   └── *.xls            one or more binary Excel 97-2003 files
            └── other files          ignored

The parser intentionally reads only nested ``PLReport*.zip`` archives under
``data/files/``. Loose ``*_MLEDR Report_*.xls`` files are ignored.
"""

from __future__ import annotations

import contextlib
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any

_MAX_ZIP_BYTES = 50 * 1024 * 1024
_MAX_TOTAL_EXTRACTED_BYTES = 100 * 1024 * 1024
_MAX_ARCHIVE_MEMBER_COUNT = 1000
_MAX_TOTAL_ARCHIVE_MEMBER_COUNT = 5000

_RE_PLR_HEADER = re.compile(
    r"Part\s+List\s+for\s*:\s*([^\s,]+)",
    re.IGNORECASE,
)
_RE_COLLAPSE_WS = re.compile(r"\s+")

_HEADER_COL_OP_SEQ = "operation sequence"
_HEADER_COL_COMP_ITEM = "component item"
_HEADER_COL_QTY = "qty"

PLR_TSV_COLUMNS: list[tuple[str, str]] = [
    ("מספר שורה", "row_number"),
    ("Operation Sequence", "operation_sequence"),
    ("Component Item", "component_item"),
    ("QTY", "qty"),
]


class PlrZipParseError(ValueError):
    """Fatal PLR ZIP parsing error with one or more UI-displayable messages."""

    def __init__(self, messages: str | list[str]) -> None:
        if isinstance(messages, str):
            self.messages = [messages]
        else:
            self.messages = [str(m).strip() for m in messages if str(m).strip()]
        if not self.messages:
            self.messages = ["שגיאה לא ידועה בפענוח ה-ZIP."]
        super().__init__("\n".join(self.messages))


@dataclass
class _ExtractionBudget:
    remaining_bytes: int
    remaining_member_count: int

    def include_members(
        self,
        members: list[zipfile.ZipInfo],
        *,
        label: str,
    ) -> None:
        if len(members) > self.remaining_member_count:
            raise PlrZipParseError(
                f"{label}: מספר הקבצים המצטבר בעץ ה-ZIP חורג מהמקסימום "
                f"({_MAX_TOTAL_ARCHIVE_MEMBER_COUNT})."
            )
        self.remaining_member_count -= len(members)

    def read_member(
        self,
        archive: zipfile.ZipFile,
        member: zipfile.ZipInfo,
        *,
        label: str,
    ) -> bytes:
        if member.file_size < 0 or member.file_size > self.remaining_bytes:
            raise PlrZipParseError(
                f"{label}: גודל החילוץ המצטבר חורג מהמקסימום "
                f"({_MAX_TOTAL_EXTRACTED_BYTES // (1024 * 1024)} MB)."
            )
        try:
            with archive.open(member) as source:
                payload = source.read(self.remaining_bytes + 1)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise PlrZipParseError(f"{label}: לא ניתן לחלץ קובץ מה-ZIP.") from exc
        if len(payload) != member.file_size or len(payload) > self.remaining_bytes:
            raise PlrZipParseError(f"{label}: גודל הקובץ שחולץ אינו תקין.")
        self.remaining_bytes -= len(payload)
        return payload


def extract_plr_rows_from_zip(
    zip_bytes: bytes,
    parent_part_number: str,
) -> dict[str, Any]:
    """Parse Rafael PLR rows from a Product/TransferRequest ZIP.

    Returns rows with ``row_number``, ``operation_sequence``, ``component_item``
    and ``qty``.
    Raises ``PlrZipParseError`` for structural or parsing errors.
    """
    parent_pn = (parent_part_number or "").strip()

    if len(zip_bytes) > _MAX_ZIP_BYTES:
        raise PlrZipParseError(
            f"ZIP גדול מדי ({len(zip_bytes) // (1024 * 1024)} MB); "
            f"המקסימום הוא {_MAX_ZIP_BYTES // (1024 * 1024)} MB."
        )

    try:
        plreport_zip_count, plr_payloads = _collect_plr_payloads(
            zip_bytes,
            _ExtractionBudget(
                _MAX_TOTAL_EXTRACTED_BYTES,
                _MAX_TOTAL_ARCHIVE_MEMBER_COUNT,
            ),
        )
    except PlrZipParseError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise PlrZipParseError("לא ניתן לפתוח את ה-ZIP.") from exc

    matched_rows: list[dict[str, str]] = []
    other_rows: list[dict[str, str]] = []
    matched_count = 0
    errors: list[str] = []

    for filename, payload in plr_payloads:
        try:
            file_pn, rows = _parse_plr_xls_payload(payload)
        except PlrZipParseError as exc:
            errors.extend(f"{filename}: {message}" for message in exc.messages)
            continue

        if parent_pn and file_pn.upper() == parent_pn.upper():
            matched_count += 1
            matched_rows.extend(rows)
        else:
            other_rows.extend(rows)

    if errors:
        raise PlrZipParseError(errors)

    combined_rows = matched_rows + other_rows
    if not combined_rows:
        raise PlrZipParseError("לא נמצאו שורות PLR לאחר פענוח קבצי ה-XLS.")
    numbered_rows = [
        {"row_number": row_number, **row}
        for row_number, row in enumerate(combined_rows, start=1)
    ]

    return {
        "rows": numbered_rows,
        "matched_file_count": matched_count,
        "plreport_zip_count": plreport_zip_count,
        "xls_file_count": len(plr_payloads),
    }


def format_plr_tsv_body(rows: list[dict[str, Any]]) -> str:
    """Build a tab-separated PLR export with CRLF line endings."""
    lines = ["\t".join(label for label, _key in PLR_TSV_COLUMNS)]
    for row in rows:
        lines.append(
            "\t".join(
                _format_tsv_cell(row.get(key, ""))
                for _label, key in PLR_TSV_COLUMNS
            )
        )
    return "\r\n".join(lines) + "\r\n"


def _format_tsv_cell(value: Any) -> str:
    """Keep exported cells inside one TSV field and inert when Excel opens them."""
    text = str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _file_members(archive: zipfile.ZipFile, *, label: str) -> list[zipfile.ZipInfo]:
    members = [member for member in archive.infolist() if not member.is_dir()]
    if len(members) > _MAX_ARCHIVE_MEMBER_COUNT:
        raise PlrZipParseError(
            f"{label}: נמצאו יותר מדי קבצים בתוך ה-ZIP; "
            f"המקסימום הוא {_MAX_ARCHIVE_MEMBER_COUNT}."
        )
    return members


def _collect_plr_payloads(
    zip_bytes: bytes,
    budget: _ExtractionBudget,
) -> tuple[int, list[tuple[str, bytes]]]:
    """Return ``(PLReport zip count, [(display_name, xls_bytes), ...])``."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as outer_zf:
        members = _file_members(outer_zf, label="ZIP חיצוני")

        if len(members) == 1 and members[0].filename.upper().endswith("_PRODUCT.ZIP"):
            budget.include_members(members, label="ZIP חיצוני")
            product_bytes = budget.read_member(
                outer_zf,
                members[0],
                label=members[0].filename,
            )
            return _collect_plr_payloads_from_product_zip(product_bytes, budget)

        return _collect_plr_payloads_from_product_zip(zip_bytes, budget)


def _collect_plr_payloads_from_product_zip(
    zip_bytes: bytes,
    budget: _ExtractionBudget,
) -> tuple[int, list[tuple[str, bytes]]]:
    payloads: list[tuple[str, bytes]] = []
    errors: list[str] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as product_zf:
        members = _file_members(product_zf, label="Product ZIP")
        budget.include_members(members, label="Product ZIP")
        plreport_members = [
            m for m in members if _is_plreport_nested_zip(m.filename)
        ]

        if not plreport_members:
            raise PlrZipParseError(
                "לא נמצאו קבצי PLReport*.zip בתוך data/files/."
            )

        for member in plreport_members:
            leaf = member.filename.rsplit("/", 1)[-1]
            raw_nested_zip = budget.read_member(
                product_zf,
                member,
                label=leaf,
            )
            nested_buf = io.BytesIO(raw_nested_zip)

            if not zipfile.is_zipfile(nested_buf):
                errors.append(f"{leaf}: קובץ PLReport אינו ZIP תקין.")
                continue

            nested_buf.seek(0)
            try:
                with zipfile.ZipFile(nested_buf) as nested_zf:
                    nested_members = _file_members(nested_zf, label=leaf)
                    budget.include_members(nested_members, label=leaf)
                    xls_members = [
                        m
                        for m in nested_members
                        if m.filename.rsplit("/", 1)[-1].lower().endswith(".xls")
                    ]

                    if not xls_members:
                        errors.append(f"{leaf}: לא נמצא קובץ XLS בתוך ה-PLReport.")
                        continue

                    for xls_member in xls_members:
                        xls_leaf = xls_member.filename.rsplit("/", 1)[-1]
                        payloads.append(
                            (
                                f"{leaf}/{xls_leaf}",
                                budget.read_member(
                                    nested_zf,
                                    xls_member,
                                    label=f"{leaf}/{xls_leaf}",
                                ),
                            )
                        )
            except zipfile.BadZipFile:
                errors.append(f"{leaf}: הזיפ המקונן פגום.")

    if errors:
        raise PlrZipParseError(errors)

    return len(plreport_members), payloads


def _is_plreport_nested_zip(path: str) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    lower = normalized.lower()
    if not lower.startswith("data/files/"):
        return False
    basename = lower.rsplit("/", 1)[-1]
    return basename.startswith("plreport") and basename.endswith(".zip")


def _parse_plr_xls_payload(data: bytes) -> tuple[str, list[dict[str, str]]]:
    """Read a binary ``.xls`` payload and extract PLR rows."""
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError as exc:
        raise PlrZipParseError("חסרה תלות Python לקריאת XLS: pandas.") from exc

    try:
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            df = pd.read_excel(
                io.BytesIO(data),
                engine="xlrd",
                header=None,
                dtype=str,
            )
    except ImportError as exc:
        raise PlrZipParseError("חסרה תלות Python לקריאת XLS: xlrd.") from exc
    except Exception as exc:  # noqa: BLE001
        raise PlrZipParseError("לא ניתן לקרוא את קובץ ה-XLS.") from exc

    return _parse_plr_from_dataframe(df)


def _parse_plr_from_dataframe(df: Any) -> tuple[str, list[dict[str, str]]]:
    import pandas as pd  # noqa: PLC0415

    file_pn: str | None = None
    op_seq_col: int | None = None
    comp_item_col: int | None = None
    qty_col: int | None = None
    found_header = False
    rows: list[dict[str, str]] = []

    for _, row in df.iterrows():
        cells = [str(cell).strip() if pd.notna(cell) else "" for cell in row]

        if file_pn is None:
            for cell in cells:
                match = _RE_PLR_HEADER.search(cell)
                if match:
                    file_pn = match.group(1).strip()
                    break
            if file_pn is None:
                continue

        if not found_header:
            op_idx = _find_plr_column_index(cells, _HEADER_COL_OP_SEQ)
            comp_idx = _find_plr_column_index(cells, _HEADER_COL_COMP_ITEM)
            qty_idx = _find_plr_column_index(cells, _HEADER_COL_QTY)
            if op_idx is not None and comp_idx is not None and qty_idx is not None:
                op_seq_col = op_idx
                comp_item_col = comp_idx
                qty_col = qty_idx
                found_header = True
            continue

        component_item = _safe_cell(cells, comp_item_col)
        if not component_item:
            continue

        rows.append(
            {
                "operation_sequence": _safe_cell(cells, op_seq_col),
                "component_item": component_item,
                "qty": _safe_cell(cells, qty_col),
            }
        )

    if file_pn is None:
        raise PlrZipParseError("לא נמצאה שורת Part List for בקובץ ה-XLS.")
    if not found_header:
        raise PlrZipParseError(
            "לא נמצאה טבלת PLR עם העמודות Operation Sequence, Component Item ו-QTY."
        )
    if not rows:
        raise PlrZipParseError("לא נמצאו שורות נתונים בטבלת ה-PLR.")

    return file_pn, rows


def _normalize_plr_header_cell(cell: str) -> str:
    return _RE_COLLAPSE_WS.sub(
        " ",
        (cell or "").replace("\r", " ").replace("\n", " "),
    ).strip().lower()


def _find_plr_column_index(row: list[str], header_name: str) -> int | None:
    target = header_name.lower()
    for idx, cell in enumerate(row):
        if _normalize_plr_header_cell(cell) == target:
            return idx
    return None


def _safe_cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()
