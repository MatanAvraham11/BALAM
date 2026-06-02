"""Tests for api/parse_rafael_plr_zip.py."""

from __future__ import annotations

import io
import os
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parse_rafael_plr_zip import (  # noqa: E402
    PlrZipParseError,
    _parse_plr_from_dataframe,
    extract_plr_rows_from_zip,
    format_plr_tsv_body,
)


def _make_inner_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _make_product_zip(
    plreport_files: dict[str, bytes],
    loose_files: dict[str, bytes] | None = None,
    data_files_prefix: str = "data/files",
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in plreport_files.items():
            zf.writestr(f"{data_files_prefix.rstrip('/')}/{name}", data)
        for name, data in (loose_files or {}).items():
            zf.writestr(f"{data_files_prefix.rstrip('/')}/{name}", data)
    return buf.getvalue()


def _make_transfer_zip(product_zip: bytes, product_name: str = "123_1_PRODUCT.ZIP") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(product_name, product_zip)
    return buf.getvalue()


def _row(op: str, component: str, qty: str) -> dict[str, str]:
    return {
        "operation_sequence": op,
        "component_item": component,
        "qty": qty,
    }


class TestZipTraversal(unittest.TestCase):
    def test_basic_direct_product_zip(self):
        inner = _make_inner_zip({"AAA_36_120000000.xls": b"AAA"})
        product = _make_product_zip({"PLReport_AAA_01.zip": inner})

        def fake_parse(data: bytes):
            self.assertEqual(data, b"AAA")
            return "AAA", [_row("1", "C1", "2")]

        with patch("parse_rafael_plr_zip._parse_plr_xls_payload", side_effect=fake_parse):
            result = extract_plr_rows_from_zip(product, "AAA")

        self.assertEqual(result["plreport_zip_count"], 1)
        self.assertEqual(result["xls_file_count"], 1)
        self.assertEqual(result["matched_file_count"], 1)
        self.assertEqual(result["rows"][0]["row_number"], 1)
        self.assertEqual(result["rows"][0]["operation_sequence"], "1")
        self.assertEqual(result["rows"][0]["component_item"], "C1")
        self.assertEqual(result["rows"][0]["qty"], "2")

    def test_transfer_request_wrapper_is_unwrapped(self):
        inner = _make_inner_zip({"AAA.xls": b"AAA"})
        product = _make_product_zip({"PLReport_AAA_01.zip": inner})
        transfer = _make_transfer_zip(product)

        with patch(
            "parse_rafael_plr_zip._parse_plr_xls_payload",
            return_value=("AAA", [_row("1", "C1", "2")]),
        ):
            result = extract_plr_rows_from_zip(transfer, "AAA")

        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["xls_file_count"], 1)

    def test_dot_slash_data_files_path_is_supported(self):
        inner = _make_inner_zip({"AAA.xls": b"AAA"})
        product = _make_product_zip(
            {"PLReport_AAA_01.zip": inner},
            data_files_prefix="./data/files",
        )

        with patch(
            "parse_rafael_plr_zip._parse_plr_xls_payload",
            return_value=("AAA", [_row("1", "C1", "2")]),
        ):
            result = extract_plr_rows_from_zip(product, "AAA")

        self.assertEqual(result["plreport_zip_count"], 1)
        self.assertEqual(result["xls_file_count"], 1)
        self.assertEqual(len(result["rows"]), 1)

    def test_multiple_xls_files_inside_one_plreport_are_all_parsed(self):
        inner = _make_inner_zip(
            {
                "PARENT.xls": b"PARENT",
                "CHILD1.xls": b"CHILD1",
                "CHILD2.xls": b"CHILD2",
            }
        )
        product = _make_product_zip({"PLReport_PARENT_01.zip": inner})

        def fake_parse(data: bytes):
            pn = data.decode("ascii")
            return pn, [_row("1", f"COMP_{pn}", "1")]

        with patch("parse_rafael_plr_zip._parse_plr_xls_payload", side_effect=fake_parse):
            result = extract_plr_rows_from_zip(product, "PARENT")

        self.assertEqual(result["plreport_zip_count"], 1)
        self.assertEqual(result["xls_file_count"], 3)
        self.assertEqual([r["component_item"] for r in result["rows"]], [
            "COMP_PARENT",
            "COMP_CHILD1",
            "COMP_CHILD2",
        ])

    def test_parent_part_number_rows_are_sorted_to_top(self):
        inner_a = _make_inner_zip({"AAA.xls": b"AAA"})
        inner_b = _make_inner_zip({"BBB.xls": b"BBB"})
        product = _make_product_zip(
            {
                "PLReport_AAA_01.zip": inner_a,
                "PLReport_BBB_01.zip": inner_b,
            }
        )

        def fake_parse(data: bytes):
            pn = data.decode("ascii")
            return pn, [_row("1", f"COMP_{pn}", "1")]

        with patch("parse_rafael_plr_zip._parse_plr_xls_payload", side_effect=fake_parse):
            result = extract_plr_rows_from_zip(product, "BBB")

        self.assertEqual(result["matched_file_count"], 1)
        self.assertEqual([r["row_number"] for r in result["rows"]], [1, 2])
        self.assertEqual(result["rows"][0]["component_item"], "COMP_BBB")
        self.assertEqual(result["rows"][1]["component_item"], "COMP_AAA")

    def test_loose_xls_is_ignored_and_no_plreport_is_an_error(self):
        product = _make_product_zip(
            {},
            loose_files={"AAA_MLEDR Report_1.xls": b"loose"},
        )

        with self.assertRaises(PlrZipParseError) as cm:
            extract_plr_rows_from_zip(product, "AAA")

        self.assertTrue(any("PLReport" in msg for msg in cm.exception.messages))


class TestErrors(unittest.TestCase):
    def test_corrupt_outer_zip_is_error(self):
        with self.assertRaises(PlrZipParseError) as cm:
            extract_plr_rows_from_zip(b"not a zip", "AAA")

        self.assertTrue(any("לא ניתן לפתוח" in msg for msg in cm.exception.messages))

    def test_corrupt_nested_plreport_zip_is_error(self):
        product = _make_product_zip({"PLReport_BAD_01.zip": b"not a nested zip"})

        with self.assertRaises(PlrZipParseError) as cm:
            extract_plr_rows_from_zip(product, "BAD")

        self.assertTrue(any("אינו ZIP" in msg for msg in cm.exception.messages))

    def test_nested_plreport_without_xls_is_error(self):
        inner = _make_inner_zip({"readme.txt": b"not xls"})
        product = _make_product_zip({"PLReport_BAD_01.zip": inner})

        with self.assertRaises(PlrZipParseError) as cm:
            extract_plr_rows_from_zip(product, "BAD")

        self.assertTrue(any("לא נמצא קובץ XLS" in msg for msg in cm.exception.messages))

    def test_unreadable_xls_is_error(self):
        inner = _make_inner_zip({"AAA.xls": b"not excel"})
        product = _make_product_zip({"PLReport_AAA_01.zip": inner})

        with self.assertRaises(PlrZipParseError) as cm:
            extract_plr_rows_from_zip(product, "AAA")

        self.assertTrue(any("לא ניתן לקרוא" in msg for msg in cm.exception.messages))


class TestDataFrameParsing(unittest.TestCase):
    def test_extracts_operation_component_and_qty_from_table(self):
        import pandas as pd

        df = pd.DataFrame(
            [
                ["", "", "Part List for: CF1A1005C"],
                ["PLM"],
                [""],
                ["Description:", "Release Status"],
                [""],
                ["", "Operation Sequence", "", "Component Item", "", "QTY"],
                ["", "1", "", "501090676", "", "21.9"],
            ]
        )

        pn, rows = _parse_plr_from_dataframe(df)

        self.assertEqual(pn, "CF1A1005C")
        self.assertEqual(rows, [_row("1", "501090676", "21.9")])

    def test_missing_qty_header_is_error(self):
        import pandas as pd

        df = pd.DataFrame(
            [
                ["Part List for: AAA"],
                ["Operation Sequence", "Component Item"],
                ["1", "C1"],
            ]
        )

        with self.assertRaises(PlrZipParseError) as cm:
            _parse_plr_from_dataframe(df)

        self.assertTrue(any("QTY" in msg for msg in cm.exception.messages))

    def test_header_without_data_rows_is_error(self):
        import pandas as pd

        df = pd.DataFrame(
            [
                ["Part List for: AAA"],
                ["Operation Sequence", "Component Item", "QTY"],
            ]
        )

        with self.assertRaises(PlrZipParseError) as cm:
            _parse_plr_from_dataframe(df)

        self.assertTrue(any("לא נמצאו שורות נתונים" in msg for msg in cm.exception.messages))

    def test_tsv_export_has_row_number_as_first_column(self):
        body = format_plr_tsv_body([
            {"row_number": 1, **_row("1", "501090676", "21.9")},
        ])

        self.assertEqual(
            body,
            "מספר שורה\tOperation Sequence\tComponent Item\tQTY\r\n"
            "1\t1\t501090676\t21.9\r\n",
        )
        body.encode("windows-1255", errors="strict")


class TestLocalSamples(unittest.TestCase):
    SAMPLE_EXPECTATIONS = {
        "/home/liran/Downloads/5355176_1_PRODUCT.ZIP": (6, 6, 7),
        "/home/liran/Downloads/TransferRequest_5351379_1294668_safe.zip": (5, 7, 10),
        "/home/liran/Downloads/TransferRequest_5355118_1294668_safe.zip": (1, 3, 11),
    }

    @unittest.skipUnless(
        all(Path(path).exists() for path in SAMPLE_EXPECTATIONS),
        "local Rafael sample ZIPs are not present",
    )
    def test_local_sample_zips_parse_with_xlrd(self):
        for path, (plreport_count, xls_count, row_count) in self.SAMPLE_EXPECTATIONS.items():
            with self.subTest(path=path):
                result = extract_plr_rows_from_zip(Path(path).read_bytes(), "")
                self.assertEqual(result["plreport_zip_count"], plreport_count)
                self.assertEqual(result["xls_file_count"], xls_count)
                self.assertEqual(len(result["rows"]), row_count)
                self.assertEqual(
                    [row["row_number"] for row in result["rows"]],
                    list(range(1, row_count + 1)),
                )
                for row in result["rows"]:
                    self.assertIn("operation_sequence", row)
                    self.assertIn("component_item", row)
                    self.assertIn("qty", row)


if __name__ == "__main__":
    unittest.main()
