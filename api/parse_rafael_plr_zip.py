"""
Rafael PLR/ZIP parser — V.6.1.

Extracts ``Operation Sequence`` and ``Component Item`` from PLM Part-List Report
files bundled in the ZIP that accompanies a Rafael manufacturing transfer request.

Typical ZIP layout (validated against three sample ZIPs):

    TransferRequest_*.zip            ← optional outer "safe" wrapper
    └── <id>_1_PRODUCT.ZIP           ← the real product ZIP
        └── data/files/              ← all lower-case
            ├── PLReport_<PN>_*.zip  ← each PLR is itself a ZIP
            │   └── <PN>_*.xls       ← binary CDFV2 or dirty CSV
            ├── *_MLEDR Report_*.xls
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
    """Traverse the actual product ZIP and yield PLR file payloads."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        plr_members = [
            m for m in members
            if _is_plr_name(m.filename)
        ]
        if not plr_members:
            warnings.append(
                "לא נמצאו קבצי PLReport_* בתוך data/files/ — "
                "בדוק שה-ZIP הוא מסוג Product Transfer."
            )
            return

        for member in plr_members:
            raw = zf.read(member.filename)
            leaf = member.filename.rsplit("/", 1)[-1]
            # PLReport_*.zip → extract single XLS inside
            if zipfile.is_zipfile(io.BytesIO(raw)):
                try:
                    inner_files = _extract_single_from_zip(raw)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(
                        f"{leaf}: הזיפ המקונן פגום ({exc}) — מדולג."
                    )
                    continue
                for inner_name, inner_bytes in inner_files:
                    yield inner_name, inner_bytes
            else:
                # Plain xls/csv directly (non-nested)
                yield leaf, raw


def _is_plr_name(path: str) -> bool:
    """Return True for data/files/PLReport_* or data/files/PLR_* (case-insensitive)."""
    lower = path.lower()
    basename = lower.rsplit("/", 1)[-1]
    return (
        lower.startswith("data/files/")
        and (basename.startswith("plreport") or basename.startswith("plr_"))
    )


def _extract_single_from_zip(zip_bytes: bytes) -> list[tuple[str, bytes]]:
    """Extract all non-directory files from a nested ZIP, returning (name, bytes)."""
    results: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for m in zf.infolist():
            if not m.is_dir():
                results.append((m.filename.rsplit("/", 1)[-1], zf.read(m.filename)))
    return results


# ---------------------------------------------------------------------------
# PLR file parsing
# ---------------------------------------------------------------------------


def _parse_plr_payload(data: bytes) -> tuple[str | None, list[dict[str, str]]]:
    """Parse a PLR payload (xls bytes or CSV bytes).

    Returns ``(part_number_or_None, rows)``.
    Tries CSV first (works for both plain CSV and HTML-table disguised CSVs),
    then binary xls via ``pandas+xlrd``, then xlsx via ``pandas+openpyxl``.
    """
    # Pass 1 — text CSV
    try:
        text = data.decode("utf-8", errors="replace")
        result = _parse_plr_from_text_lines(text.splitlines())
        if result[0] is not None or _looks_like_text(data):
            return result
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
    """Parse PLR from plain text lines (CSV with comma delimiter)."""
    file_pn: str | None = None
    op_seq_col: int | None = None
    comp_item_col: int | None = None
    rows: list[dict[str, str]] = []

    reader = csv.reader(lines, delimiter=",")
    for raw_row in reader:
        if not raw_row:
            continue
        # Find "Part List for: <PN>"
        if file_pn is None:
            for cell in raw_row:
                m = _RE_PLR_HEADER.search(cell)
                if m:
                    file_pn = m.group(1).strip()
                    break
            continue

        # Find header row
        if op_seq_col is None:
            row_lower = [c.strip().lower() for c in raw_row]
            try:
                op_seq_col = row_lower.index(_HEADER_COL_OP_SEQ)
                comp_item_col = row_lower.index(_HEADER_COL_COMP_ITEM)
            except ValueError:
                continue
            continue

        # Data rows
        op_val = _safe_cell(raw_row, op_seq_col)
        comp_val = _safe_cell(raw_row, comp_item_col)
        if op_val or comp_val:
            rows.append({"operation_sequence": op_val, "component_item": comp_val})

    return file_pn, rows


def _parse_plr_from_dataframe(df: Any) -> tuple[str | None, list[dict[str, str]]]:
    """Parse PLR from a pandas DataFrame (already loaded from xls/xlsx)."""
    import pandas as pd  # noqa: PLC0415

    file_pn: str | None = None
    op_seq_col: int | None = None
    comp_item_col: int | None = None
    rows: list[dict[str, str]] = []

    for _, row in df.iterrows():
        cells = [str(c).strip() if pd.notna(c) else "" for c in row]
        non_empty = [c for c in cells if c]

        if file_pn is None:
            for cell in non_empty:
                m = _RE_PLR_HEADER.search(cell)
                if m:
                    file_pn = m.group(1).strip()
                    break
            continue

        if op_seq_col is None:
            cells_lower = [c.lower() for c in cells]
            try:
                op_seq_col = cells_lower.index(_HEADER_COL_OP_SEQ)
                comp_item_col = cells_lower.index(_HEADER_COL_COMP_ITEM)
            except ValueError:
                continue
            continue

        op_val = cells[op_seq_col] if op_seq_col < len(cells) else ""
        comp_val = cells[comp_item_col] if comp_item_col < len(cells) else ""
        if op_val or comp_val:
            rows.append({"operation_sequence": op_val, "component_item": comp_val})

    return file_pn, rows


def _safe_cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()
