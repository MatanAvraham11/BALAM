"""
Tests for api/parse_rafael_plr_zip.py — all in-memory (no disk files).
"""
from __future__ import annotations

import csv
import io
import unittest
import zipfile


# ---------------------------------------------------------------------------
# Helpers to build synthetic ZIPs / payloads in memory
# ---------------------------------------------------------------------------

def _make_csv_plr(part_number: str, rows: list[tuple[str, str]]) -> bytes:
    """Build a minimal PLR-style CSV payload."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"Part List for: {part_number}", "Report Date: 01-01-2026"])
    w.writerow(["PLM"])
    w.writerow([])
    w.writerow(["Description:", "Release Status"])
    w.writerow([])
    w.writerow(["Some Part Name", "Released"])
    w.writerow([])
    w.writerow([])
    w.writerow([
        "Operation Sequence", "Component Item", "Component Description",
        "Item Type", "UOM", "QTY",
    ])
    for op, comp in rows:
        w.writerow([op, comp, "some desc", "type", "EA", "1"])
    return buf.getvalue().encode("utf-8")


def _make_inner_zip(xls_name: str, xls_bytes: bytes) -> bytes:
    """Wrap xls_bytes in a single-member ZIP (like PLReport_*.zip)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xls_name, xls_bytes)
    return buf.getvalue()


def _make_product_zip(plr_files: dict[str, bytes]) -> bytes:
    """Build a *_PRODUCT.ZIP with data/files/ structure.

    ``plr_files`` maps ``PLReport_<PN>_*.zip`` → bytes of the inner zip.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in plr_files.items():
            zf.writestr(f"data/files/{name}", data)
    return buf.getvalue()


def _make_transfer_zip(product_zip_bytes: bytes, product_zip_name: str = "12345_1_PRODUCT.ZIP") -> bytes:
    """Wrap a product ZIP in the TransferRequest outer wrapper."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(product_zip_name, product_zip_bytes)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from parse_rafael_plr_zip import extract_plr_rows_from_zip  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDirectProductZip(unittest.TestCase):
    """Upload the _PRODUCT.ZIP directly (no outer wrapper)."""

    def _zip(self, plr_map: dict) -> bytes:
        return _make_product_zip(plr_map)

    def test_basic_extraction(self):
        csv_bytes = _make_csv_plr("BD01006", [("10", "510150130"), ("20", "510150131")])
        inner_zip = _make_inner_zip("BD01006_rev_abc.xls", csv_bytes)
        product = self._zip({"PLReport_BD01006_01_x.zip": inner_zip})
        result = extract_plr_rows_from_zip(product, "BD01006")
        self.assertEqual(result["total_file_count"], 1)
        self.assertEqual(result["matched_file_count"], 1)
        rows = result["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["operation_sequence"], "10")
        self.assertEqual(rows[0]["component_item"], "510150130")
        self.assertEqual(rows[0]["row_number"], 1)
        self.assertEqual(rows[1]["row_number"], 2)

    def test_parent_pn_sorted_to_top(self):
        csv_a = _make_csv_plr("AAA", [("10", "COMP_A1"), ("20", "COMP_A2")])
        csv_b = _make_csv_plr("BBB", [("10", "COMP_B1")])
        inner_a = _make_inner_zip("AAA_rev.xls", csv_a)
        inner_b = _make_inner_zip("BBB_rev.xls", csv_b)
        product = self._zip({
            "PLReport_AAA_01_x.zip": inner_a,
            "PLReport_BBB_01_x.zip": inner_b,
        })
        result = extract_plr_rows_from_zip(product, "BBB")
        rows = result["rows"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(result["matched_file_count"], 1)
        # BBB should be first (parent match)
        self.assertEqual(rows[0]["component_item"], "COMP_B1")
        self.assertEqual(rows[0]["row_number"], 1)
        # AAA rows follow
        self.assertIn(rows[1]["component_item"], ("COMP_A1", "COMP_A2"))

    def test_no_parent_match_still_returns_all(self):
        csv_a = _make_csv_plr("AAA", [("10", "COMP_A")])
        inner_a = _make_inner_zip("AAA_rev.xls", csv_a)
        product = self._zip({"PLReport_AAA_01_x.zip": inner_a})
        result = extract_plr_rows_from_zip(product, "DOES_NOT_EXIST")
        self.assertEqual(result["matched_file_count"], 0)
        self.assertEqual(len(result["rows"]), 1)

    def test_row_numbers_sequential(self):
        csv_a = _make_csv_plr("AAA", [("10", "C1"), ("20", "C2"), ("30", "C3")])
        inner_a = _make_inner_zip("AAA_rev.xls", csv_a)
        product = self._zip({"PLReport_AAA_01_x.zip": inner_a})
        result = extract_plr_rows_from_zip(product, "AAA")
        nums = [r["row_number"] for r in result["rows"]]
        self.assertEqual(nums, [1, 2, 3])

    def test_empty_parent_pn_returns_all(self):
        csv_a = _make_csv_plr("AAA", [("10", "C1")])
        inner_a = _make_inner_zip("AAA_rev.xls", csv_a)
        product = self._zip({"PLReport_AAA_01_x.zip": inner_a})
        result = extract_plr_rows_from_zip(product, "")
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["matched_file_count"], 0)


class TestTransferRequestWrapper(unittest.TestCase):
    """TransferRequest_*.zip wrapping the product ZIP."""

    def test_outer_wrapper_unwrapped(self):
        csv_bytes = _make_csv_plr("PN001", [("1", "COMP1")])
        inner_zip = _make_inner_zip("PN001_rev.xls", csv_bytes)
        product = _make_product_zip({"PLReport_PN001_01.zip": inner_zip})
        transfer = _make_transfer_zip(product)
        result = extract_plr_rows_from_zip(transfer, "PN001")
        self.assertEqual(result["total_file_count"], 1)
        self.assertEqual(len(result["rows"]), 1)


class TestEdgeCases(unittest.TestCase):
    """Corrupt / edge-case inputs."""

    def test_corrupt_zip_returns_empty_with_warning(self):
        result = extract_plr_rows_from_zip(b"not a zip at all", "AAA")
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["total_file_count"], 0)
        self.assertTrue(len(result["warnings"]) > 0)

    def test_no_plr_files_in_product_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data/files/some_drawing.pdf", b"PDF bytes")
        result = extract_plr_rows_from_zip(buf.getvalue(), "AAA")
        self.assertEqual(result["total_file_count"], 0)
        self.assertEqual(result["rows"], [])
        self.assertTrue(any("PLReport" in w for w in result["warnings"]))

    def test_plr_without_part_list_header_skipped_with_warning(self):
        no_header_csv = b"just,some,data\n1,2,3\n"
        inner_zip = _make_inner_zip("BAD_rev.xls", no_header_csv)
        product = _make_product_zip({"PLReport_BAD_01.zip": inner_zip})
        result = extract_plr_rows_from_zip(product, "BAD")
        self.assertEqual(result["rows"], [])
        self.assertTrue(len(result["warnings"]) > 0)

    def test_plr_with_header_but_no_data_rows(self):
        csv_bytes = _make_csv_plr("EMPTY_PN", [])
        inner_zip = _make_inner_zip("EMPTY_PN_rev.xls", csv_bytes)
        product = _make_product_zip({"PLReport_EMPTY_01.zip": inner_zip})
        result = extract_plr_rows_from_zip(product, "EMPTY_PN")
        self.assertEqual(result["rows"], [])
        self.assertTrue(len(result["warnings"]) > 0)

    def test_corrupted_inner_zip_warns_and_skips(self):
        product = _make_product_zip({"PLReport_BAD_01.zip": b"corrupted_zip_bytes"})
        result = extract_plr_rows_from_zip(product, "BAD")
        self.assertEqual(result["rows"], [])
        self.assertTrue(len(result["warnings"]) > 0)

    def test_multiple_files_row_numbers_across_files(self):
        csv_a = _make_csv_plr("PN_A", [("10", "CA1"), ("20", "CA2")])
        csv_b = _make_csv_plr("PN_B", [("10", "CB1")])
        inner_a = _make_inner_zip("PN_A.xls", csv_a)
        inner_b = _make_inner_zip("PN_B.xls", csv_b)
        product = _make_product_zip({
            "PLReport_PN_A_01.zip": inner_a,
            "PLReport_PN_B_01.zip": inner_b,
        })
        result = extract_plr_rows_from_zip(product, "PN_A")
        rows = result["rows"]
        # PN_A at top (parent), then PN_B
        self.assertEqual(rows[0]["component_item"], "CA1")
        self.assertEqual(rows[1]["component_item"], "CA2")
        self.assertEqual(rows[2]["component_item"], "CB1")
        self.assertEqual([r["row_number"] for r in rows], [1, 2, 3])

    def test_oversized_zip_returns_warning(self):
        # Pretend bytes > _MAX_ZIP_BYTES by monkeypatching
        from parse_rafael_plr_zip import _MAX_ZIP_BYTES
        oversized = b"x" * (_MAX_ZIP_BYTES + 1)
        result = extract_plr_rows_from_zip(oversized, "AAA")
        self.assertEqual(result["rows"], [])
        self.assertTrue(any("גדול" in w for w in result["warnings"]))

    def test_case_insensitive_parent_pn_match(self):
        csv_bytes = _make_csv_plr("bd01006", [("10", "C1")])
        inner_zip = _make_inner_zip("bd01006_rev.xls", csv_bytes)
        product = _make_product_zip({"PLReport_bd01006_01.zip": inner_zip})
        result = extract_plr_rows_from_zip(product, "BD01006")
        self.assertEqual(result["matched_file_count"], 1)


if __name__ == "__main__":
    unittest.main()
