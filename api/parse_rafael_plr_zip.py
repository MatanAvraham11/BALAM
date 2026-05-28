"""
Rafael PLR/ZIP parser — V.6.1.

Extracts ``Operation Sequence`` and ``Component Item`` from PLM Part-List Report
files bundled in the ZIP that accompanies a Rafael manufacturing transfer request.

Typical ZIP layout (validated against three sample ZIPs):

    TransferRequest_*.zip            ← optional outer "safe" wrapper
    └── <id>_1_PRODUCT.ZIP           ← the real product ZIP
        └── data/files/              ← all lower-case
            ├── PLReport_<PN>_*.zip  ← ONLY these nested ZIPs are parsed
            │   └── <PN>_*.xls       ← CSV-formatted text (comma-separated)
            ├── *_MLEDR*.xls         ← loose XLS in data/files — IGNORED
            └── *.pdf / *.stp / …

The module is intentionally self-contained (no dependency on
``parse_rafael_rfq``).  All ZIP reading is done **in-memory** (``io.BytesIO``);
no temp files are created.

Public API
----------
``extract_plr_rows_from_zip(zip_bytes, parent_part_number)``
    Returns::

        {
          "rows": [
              {"row_number": 1, "operation_sequence": "...", "component_item": "..."},
              ...
          ],
          "matched_file_count": N,   # PLR files whose PN == parent_part_number
          "total_file_count":   M,   # total PLR files found
          "warnings": ["..."],       # non-fatal issues
        }

    ``matched_file_count`` is 0 when ``parent_part_number`` is not found in any
    PLR header; all files are still returned (sorting has no effect in that case).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_ZIP_BYTES = 50 * 1024 * 1024  # 50 MB soft guard (checked before parsing)

# Regex to parse "Part List for: <PN>" header line
_RE_PLR_HEADER = re.compile(
    r"Part\s+List\s+for\s*:\s*([^\s,]+)",
    re.IGNORECASE,
)

_HEADER_COL_OP_SEQ = "operation sequence"
_HEADER_COL_COMP_ITEM = "component item"

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_plr_rows_from_zip(
    zip_bytes: bytes,
    parent_part_number: str,
) -> dict[str, Any]:
    """Parse all PLR files from *zip_bytes* and return sorted rows.

    Parameters
    ----------
    zip_bytes:
        Raw bytes of the uploaded ZIP (may be the outer TransferRequest wrapper).
    parent_part_number:
        The first ``rafael_pn`` from the RFQ PDF.  PLR files whose header PN
        matches this value are sorted to the top of the combined list.

    Returns
    -------
    dict with keys ``rows``, ``matched_file_count``, ``total_file_count``,
    ``warnings``.
    """
    warnings: list[str] = []
    parent_pn = (parent_part_number or "").strip()

    if len(zip_bytes) > _MAX_ZIP_BYTES:
        return {
            "rows": [],
            "matched_file_count": 0,
            "total_file_count": 0,
            "warnings": [
                f"ZIP גדול מדי ({len(zip_bytes) // (1024 * 1024)} MB); "
                f"המקסימום הוא {_MAX_ZIP_BYTES // (1024 * 1024)} MB.",
            ],
        }

    try:
        plr_payloads = list(_iter_plr_payloads(zip_bytes, warnings))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        return {
            "rows": [],
            "matched_file_count": 0,
            "total_file_count": 0,
            "warnings": [f"לא ניתן לפתוח את ה-ZIP: {exc}"],
        }

    total = len(plr_payloads)
    matched_rows: list[dict[str, str]] = []
    other_rows: list[dict[str, str]] = []
    matched_count = 0

    for filename, payload in plr_payloads:
        try:
            file_pn, rows = _parse_plr_payload(payload)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{filename}: לא ניתן לפרסר ({type(exc).__name__}: {exc})")
            continue
        if file_pn is None:
            warnings.append(f"{filename}: לא נמצאה שורת Part List for: בקובץ — מדולג.")
            continue
        if not rows:
            warnings.append(f"{filename}: לא נמצאו שורות נתונים מתחת ל-header.")
            continue
        if parent_pn and file_pn.upper() == parent_pn.upper():
            matched_count += 1
            matched_rows.extend(rows)
        else:
            other_rows.extend(rows)

    combined = matched_rows + other_rows
    for idx, row in enumerate(combined, start=1):
        row["row_number"] = idx  # type: ignore[assignment]

    return {
        "rows": combined,
        "matched_file_count": matched_count,
        "total_file_count": total,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# ZIP traversal
# ---------------------------------------------------------------------------


def _iter_plr_payloads(
    zip_bytes: bytes,
    warnings: list[str],
) -> Iterator[tuple[str, bytes]]:
    """Yield ``(filename, raw_bytes)`` for every PLR payload found.

    Handles:
    - Direct ``*_PRODUCT.ZIP`` — ``data/files/`` inside.
    - TransferRequest wrapper containing a single ``*_PRODUCT.ZIP`` member.
    - PLReport entries that are themselves ZIPs (nested ZIP).
    """
    try:
        outer_zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise zipfile.BadZipFile(str(exc)) from exc

    with outer_zf:
        names = [m.filename for m in outer_zf.infolist() if not m.is_dir()]

        # Check for TransferRequest wrapper: single member ending _PRODUCT.ZIP
        inner_candidates = [
            n for n in names if n.upper().endswith("_PRODUCT.ZIP")
        ]
        if inner_candidates and len(names) == 1:
            inner_bytes = outer_zf.read(inner_candidates[0])
            yield from _iter_plr_payloads_from_product_zip(inner_bytes, warnings)
            return

        # Direct product ZIP (user uploaded *_PRODUCT.ZIP itself)
        # Check for data/files/ path pattern
        has_data_files = any(
            n.lower().startswith("data/files/") for n in names
        )
        if has_data_files:
            yield from _iter_plr_payloads_from_product_zip(zip_bytes, warnings)
            return

        # Fallback: treat as product ZIP directly
        yield from _iter_plr_payloads_from_product_zip(zip_bytes, warnings)


def _iter_plr_payloads_from_product_zip(
    zip_bytes: bytes,
    warnings: list[str],
) -> Iterator[tuple[str, bytes]]:
    """Traverse the product ZIP and yield inner PLR payloads from nested ZIPs only.

    Under ``data/files/`` we **only** open ``PLReport*.zip`` / ``PLR*.zip`` archives.
    Standalone ``.xls`` / ``.csv`` siblings in that folder are explicitly ignored.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        plr_zip_members = [m for m in members if _is_plr_nested_zip(m.filename)]

        if not plr_zip_members:
            warnings.append(
                "לא נמצאו קבצי PLReport_*.zip / PLR*.zip בתוך data/files/ — "
                "בדוק שה-ZIP הוא מסוג Product Transfer."
            )
            return

        for member in plr_zip_members:
            raw = zf.read(member.filename)
            leaf = member.filename.rsplit("/", 1)[-1]
            if not zipfile.is_zipfile(io.BytesIO(raw)):
                warnings.append(f"{leaf}: אינו ZIP תקין — מדולג.")
                continue
            try:
                inner_files = _extract_files_from_nested_plr_zip(raw)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{leaf}: הזיפ המקונן פגום ({exc}) — מדולג.")
                continue
            if not inner_files:
                warnings.append(f"{leaf}: הזיפ המקונן ריק — מדולג.")
                continue
            for inner_name, inner_bytes in inner_files:
                yield f"{leaf}/{inner_name}", inner_bytes


def _is_plr_nested_zip(path: str) -> bool:
    """True for ``data/files/`` entries that are ``.zip`` and start with PLR / PLReport."""
    lower = path.replace("\\", "/").lower()
    if not lower.startswith("data/files/"):
        return False
    basename = lower.rsplit("/", 1)[-1]
    if not basename.endswith(".zip"):
        return False
    stem = basename[:-4]
    return stem.startswith("plreport") or stem.startswith("plr")


def _extract_files_from_nested_plr_zip(zip_bytes: bytes) -> list[tuple[str, bytes]]:
    """Extract spreadsheet payloads from a PLReport/PLR nested ZIP (usually one ``.xls``)."""
    all_files: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for m in zf.infolist():
            if m.is_dir():
                continue
            leaf = m.filename.rsplit("/", 1)[-1]
            all_files.append((leaf, zf.read(m.filename)))
    if not all_files:
        return []
    xls_like = [
        (name, data)
        for name, data in all_files
        if name.lower().endswith((".xls", ".xlsx", ".csv"))
    ]
    return xls_like if xls_like else all_files


# ---------------------------------------------------------------------------
# PLR file parsing
# ---------------------------------------------------------------------------


def _parse_plr_payload(data: bytes) -> tuple[str | None, list[dict[str, str]]]:
    """Parse inner PLR payload (``.xls`` that is usually comma-separated text).

    Returns ``(part_number_or_None, rows)``.
    Tries CSV/text first, then binary xls via ``pandas+xlrd``, then xlsx.
    """
    # Pass 1 — comma-separated text (typical inner .xls from Rafael PLM)
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            result = _parse_plr_from_text_lines(text.splitlines())
            if result[0] is not None and result[1]:
                return result
            if result[0] is not None or _looks_like_text(data):
                return result
        except Exception:  # noqa: BLE001
            continue
    try:
        text = data.decode("utf-8", errors="replace")
        return _parse_plr_from_text_lines(text.splitlines())
    except Exception:  # noqa: BLE001
        pass

    # Pass 2 — binary xls (CDFV2 Excel 97-2003)
    try:
        import pandas as pd  # noqa: PLC0415
        df = pd.read_excel(
            io.BytesIO(data), engine="xlrd", header=None, dtype=str,
        )
        return _parse_plr_from_dataframe(df)
    except Exception:  # noqa: BLE001
        pass

    # Pass 3 — xlsx (PK\x03\x04 magic bytes)
    if data[:4] == b"PK\x03\x04":
        try:
            import pandas as pd  # noqa: PLC0415
            df = pd.read_excel(
                io.BytesIO(data), engine="openpyxl", header=None, dtype=str,
            )
            return _parse_plr_from_dataframe(df)
        except Exception:  # noqa: BLE001
            pass

    return None, []


def _looks_like_text(data: bytes) -> bool:
    """Heuristic: data is text if the first 512 bytes are mostly printable ASCII."""
    sample = data[:512]
    try:
        decoded = sample.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    printable = sum(1 for c in decoded if c.isprintable() or c in "\r\n\t")
    return printable / max(len(decoded), 1) > 0.85


def _parse_plr_from_text_lines(
    lines: list[str],
) -> tuple[str | None, list[dict[str, str]]]:
    """Parse PLR from comma-separated text (inner .xls is usually CSV under the hood)."""
    file_pn: str | None = None
    op_seq_col: int | None = None
    comp_item_col: int | None = None
    in_data_section = False
    rows: list[dict[str, str]] = []

    reader = csv.reader(lines, delimiter=",")
    for raw_row in reader:
        # Keep rows that are only trailing empties; skip wholly absent lines.
        if raw_row is not None and len(raw_row) == 0:
            continue

        # Find "Part List for: <PN>" (may appear in any cell, including after leading commas)
        if file_pn is None:
            for cell in raw_row:
                m = _RE_PLR_HEADER.search(cell or "")
                if m:
                    file_pn = m.group(1).strip()
                    break
            if file_pn is None:
                continue
            continue

        # Find header row — column indices account for a leading empty column
        if not in_data_section:
            row_lower = [(c or "").strip().lower() for c in raw_row]
            if _HEADER_COL_OP_SEQ in row_lower and _HEADER_COL_COMP_ITEM in row_lower:
                op_seq_col = row_lower.index(_HEADER_COL_OP_SEQ)
                comp_item_col = row_lower.index(_HEADER_COL_COMP_ITEM)
                in_data_section = True
            continue

        # Data rows: do not reject because index 0 is empty (e.g. ",1.0,,316150321,...")
        op_val = _safe_cell(raw_row, op_seq_col)
        comp_val = _safe_cell(raw_row, comp_item_col)
        if _is_plr_data_row(op_val, comp_val):
            rows.append({"operation_sequence": op_val, "component_item": comp_val})

    return file_pn, rows


def _is_plr_data_row(operation_sequence: str, component_item: str) -> bool:
    """True when at least one of the target columns has a non-empty value."""
    return bool((operation_sequence or "").strip() or (component_item or "").strip())


def _parse_plr_from_dataframe(df: Any) -> tuple[str | None, list[dict[str, str]]]:
    """Parse PLR from a pandas DataFrame (already loaded from xls/xlsx)."""
    import pandas as pd  # noqa: PLC0415

    file_pn: str | None = None
    op_seq_col: int | None = None
    comp_item_col: int | None = None
    rows: list[dict[str, str]] = []

    in_data_section = False
    for _, row in df.iterrows():
        cells = [str(c).strip() if pd.notna(c) else "" for c in row]

        if file_pn is None:
            for cell in cells:
                m = _RE_PLR_HEADER.search(cell)
                if m:
                    file_pn = m.group(1).strip()
                    break
            continue

        if not in_data_section:
            cells_lower = [c.lower() for c in cells]
            if _HEADER_COL_OP_SEQ in cells_lower and _HEADER_COL_COMP_ITEM in cells_lower:
                op_seq_col = cells_lower.index(_HEADER_COL_OP_SEQ)
                comp_item_col = cells_lower.index(_HEADER_COL_COMP_ITEM)
                in_data_section = True
            continue

        op_val = _safe_cell(cells, op_seq_col)
        comp_val = _safe_cell(cells, comp_item_col)
        if _is_plr_data_row(op_val, comp_val):
            rows.append({"operation_sequence": op_val, "component_item": comp_val})

    return file_pn, rows


def _safe_cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()
