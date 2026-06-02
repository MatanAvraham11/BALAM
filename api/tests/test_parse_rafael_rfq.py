"""Lightweight tests for ``parse_rafael_rfq``.

1. Pure-logic unit tests (always run).
2. PDF smoke tests when the three Rafael RFQ references exist in Downloads.

Run::

    python3 -m unittest api.tests.test_parse_rafael_rfq
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[2]
_API = _ROOT / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

try:
    import eval_type_backport  # noqa: F401
except ModuleNotFoundError:
    pass

from parse_rafael_rfq import (  # noqa: E402
    FAI_NOT_REQUIRED,
    RAFAEL_TXT_COLUMNS,
    Delivery,
    PartBlock,
    RafaelRfq,
    _build_type3_font_code_maps_by_page,
    _classify_fai_digit,
    _decode_fai_not_required_cell,
    _decode_type3_chars,
    _detect_part_blocks,
    _detect_rfq_number,
    _hebrew_letter_count,
    _parse_dmy,
    _type3_code_from_pdf_text,
    _visual_hebrew_to_logical,
    flatten_rafael_to_rows,
    format_rafael_tsv_body,
    parse_rafael_rfq,
)

_DOWNLOADS = Path.home() / "Downloads"

_PDF_CASE_DEFS = [
    {
        "paths": [
            _DOWNLOADS / "RFQ_1294668_684471.pdf",
        ],
        "rfq": "684471",
        "buyer": "חיים קאופמן",
        "submission_date": "08/05/2026",
        "parts": 6,
        "rows": 8,
        "fai": [
            "FAI 2",
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
            "FAI 2",
            "FAI 2",
            FAI_NOT_REQUIRED,
            "FAI 2",
            FAI_NOT_REQUIRED,
        ],
    },
    {
        "paths": [
            _DOWNLOADS / "RFQ_1294668_684196.pdf",
            _DOWNLOADS / "RFQ_1294668_684196 (1).pdf",
        ],
        "rfq": "684196",
        "buyer": "יוסי שלום",
        "submission_date": "08/05/2026",
        "parts": 5,
        "rows": 18,
        "fai": [
            "FAI 2",
            "FAI 2",
            FAI_NOT_REQUIRED,
            "FAI 2",
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
            "FAI 2",
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
            "FAI 2",
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
            FAI_NOT_REQUIRED,
        ],
    },
    {
        "paths": [
            _DOWNLOADS / "RFQ_1294668_684070.pdf",
        ],
        "rfq": "684070",
        "buyer": "שירן סורני שלאם",
        "submission_date": "13/05/2026",
        "parts": 1,
        "rows": 7,
        "fai": [FAI_NOT_REQUIRED] * 7,
    },
]


def _resolve_pdf_cases() -> list[dict]:
    cases: list[dict] = []
    for d in _PDF_CASE_DEFS:
        path = next((p for p in d["paths"] if p.exists()), None)
        if path is None:
            continue
        cases.append({
            "path": path,
            "rfq": d["rfq"],
            "buyer": d["buyer"],
            "submission_date": d["submission_date"],
            "parts": d["parts"],
            "rows": d["rows"],
            "fai": d["fai"],
        })
    return cases


_PDF_CASES = _resolve_pdf_cases()


class Type3DecoderTests(unittest.TestCase):
    def test_code_from_pdf_text(self):
        self.assertEqual(_type3_code_from_pdf_text("A"), 65)
        self.assertEqual(_type3_code_from_pdf_text("(cid:237)"), 237)
        self.assertIsNone(_type3_code_from_pdf_text(""))
        self.assertIsNone(_type3_code_from_pdf_text("AB"))
        self.assertIsNone(_type3_code_from_pdf_text("א"))
        self.assertEqual(_type3_code_from_pdf_text("\u2018"), 143)
        self.assertEqual(_type3_code_from_pdf_text("\u0153"), 156)
        self.assertEqual(_type3_code_from_pdf_text("\u0141"), 149)
        self.assertEqual(_type3_code_from_pdf_text("\u02dd"), 205)

    def test_decode_type3_chars(self):
        chars = [
            {"text": chr(1), "x0": 10.0, "top": 5.0, "size": 0},
            {"text": chr(2), "x0": 14.0, "top": 5.0, "size": 0},
            {"text": chr(3), "x0": 24.0, "top": 5.0, "size": 0},
        ]
        self.assertEqual(
            _decode_type3_chars(chars, {1: "א", 2: "ב", 3: "ג"}, word_gap_min=7.0),
            "אב ג",
        )

    def test_decode_type3_chars_rejects_unmapped_glyphs(self):
        chars = [{"text": chr(9), "x0": 10.0, "top": 5.0, "size": 0}]
        with self.assertRaisesRegex(ValueError, "unmapped"):
            _decode_type3_chars(chars, {})

    def test_decode_type3_chars_rejects_unrepresentable_glyphs(self):
        chars = [{"text": "א", "x0": 10.0, "top": 5.0, "size": 0}]
        with self.assertRaisesRegex(ValueError, "unrepresentable"):
            _decode_type3_chars(chars, {})

    def test_decode_fai_not_required_cell_tries_each_font_map(self):
        chars = [
            {"text": "(cid:224)", "x0": 33.7, "top": 100.0, "size": 0},
            {"text": "=", "x0": 39.0, "top": 100.0, "size": 0},
            {"text": "ø", "x0": 30.8, "top": 109.3, "size": 0},
            {"text": ">", "x0": 36.2, "top": 109.3, "size": 0},
            {"text": "(cid:15)", "x0": 40.7, "top": 109.3, "size": 0},
            {"text": "?", "x0": 45.1, "top": 109.3, "size": 0},
        ]
        wrong_map = {224: "א", 61: "ת", 248: "ש", 62: "ה", 15: "ד", 63: "ג"}
        right_map = {224: "א", 61: "ל", 248: "ש", 62: "ר", 15: "ד", 63: "נ"}

        self.assertEqual(
            _decode_fai_not_required_cell(chars, [wrong_map, right_map]),
            FAI_NOT_REQUIRED,
        )

    def test_decode_fai_not_required_cell_accepts_single_line(self):
        chars = [
            {"text": chr(1), "x0": 10.0, "top": 100.0, "size": 0},
            {"text": chr(2), "x0": 15.0, "top": 100.0, "size": 0},
            {"text": chr(3), "x0": 20.0, "top": 100.0, "size": 0},
            {"text": chr(4), "x0": 25.0, "top": 100.0, "size": 0},
            {"text": chr(5), "x0": 35.0, "top": 100.0, "size": 0},
            {"text": chr(6), "x0": 40.0, "top": 100.0, "size": 0},
        ]
        code_map = {1: "ש", 2: "ר", 3: "ד", 4: "נ", 5: "א", 6: "ל"}

        self.assertEqual(
            _decode_fai_not_required_cell(chars, [code_map]),
            FAI_NOT_REQUIRED,
        )

    def test_decode_fai_not_required_cell_rejects_unrepresentable_glyphs(self):
        chars = [{"text": "א", "x0": 10.0, "top": 100.0, "size": 0}]
        self.assertIsNone(_decode_fai_not_required_cell(chars, [{}]))

    def test_visual_hebrew_to_logical(self):
        self.assertEqual(
            _visual_hebrew_to_logical("ןמפואק םייח"),
            "חיים קאופמן",
        )


class ParseDmyTests(unittest.TestCase):
    def test_valid(self):
        d = _parse_dmy("07/05/2026")
        self.assertIsNotNone(d)
        self.assertEqual((d.day, d.month, d.year), (7, 5, 2026))

    def test_invalid(self):
        self.assertIsNone(_parse_dmy(""))
        self.assertIsNone(_parse_dmy("2026-05-07"))
        self.assertIsNone(_parse_dmy("32/13/2026"))


class ClassifyFaiTests(unittest.TestCase):
    def test_valid_digits(self):
        self.assertEqual(_classify_fai_digit("1"), "FAI 1")
        self.assertEqual(_classify_fai_digit("2"), "FAI 2")
        self.assertEqual(_classify_fai_digit("3"), "FAI 3")

    def test_invalid_is_rejected(self):
        self.assertIsNone(_classify_fai_digit(None))
        self.assertIsNone(_classify_fai_digit(""))
        self.assertIsNone(_classify_fai_digit("9"))


class StrictParserTests(unittest.TestCase):
    def test_delivery_requires_explicit_fai(self):
        with self.assertRaises(ValidationError):
            Delivery(quantity=1.0, weeks_aro=1)

    def test_rfq_number_does_not_fall_back_to_fax_info(self):
        pages = [[{"text": "FAX_INFO:684471:", "x0": 0.0, "x1": 100.0, "top": 100.0}]]
        with self.assertRaisesRegex(ValueError, "no standalone"):
            _detect_rfq_number(pages)

    def test_part_requires_quantity_rows(self):
        words = [
            {"text": "Each", "x0": 500.0, "x1": 520.0, "top": 200.0},
            {"text": "BD01006", "x0": 730.0, "x1": 780.0, "top": 200.0},
        ]
        with self.assertRaisesRegex(ValueError, "no delivery quantity"):
            _detect_part_blocks([words], [[]], [[]])

    def test_delivery_requires_aro_weeks(self):
        words = [
            {"text": "Each", "x0": 500.0, "x1": 520.0, "top": 200.0},
            {"text": "BD01006", "x0": 730.0, "x1": 780.0, "top": 200.0},
            {"text": "12.00", "x0": 260.0, "x1": 290.0, "top": 200.0},
        ]
        with self.assertRaisesRegex(ValueError, "missing integer weeks"):
            _detect_part_blocks([words], [[]], [[]])


class FlattenAndWriteTests(unittest.TestCase):
    def _build_rfq(self) -> RafaelRfq:
        return RafaelRfq(
            rfq_number="684471",
            buyer_name="חיים קאופמן",
            submission_date="08/05/2026",
            parts=[
                PartBlock(
                    rafael_pn="BD01006",
                    deliveries=[
                        Delivery(quantity=12.0, weeks_aro=5, fai="FAI 2"),
                        Delivery(quantity=10.0, weeks_aro=5, fai=FAI_NOT_REQUIRED),
                    ],
                ),
                PartBlock(
                    rafael_pn="C24A1501A",
                    deliveries=[
                        Delivery(quantity=11.0, weeks_aro=26, fai=FAI_NOT_REQUIRED),
                    ],
                ),
            ],
        )

    def test_row_count_and_global_numbering(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["מספר שורה"] for r in rows], [1, 2, 3])

    def test_first_column_is_row_number(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        self.assertEqual(RAFAEL_TXT_COLUMNS[0], "מספר שורה")
        self.assertEqual(list(rows[0].keys())[0], "מספר שורה")

    def test_globals_repeated_per_row(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        for r in rows:
            self.assertEqual(r["מספר בלם"], "684471")
            self.assertEqual(r["שם קניין"], "חיים קאופמן")
            self.assertEqual(r["תאריך סופי להגשה"], "08/05/2026")

    def test_weeks_column_is_integer(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        self.assertEqual(rows[0]["זמן אספקה בשבועות"], 5)
        self.assertEqual(rows[2]["זמן אספקה בשבועות"], 26)

    def test_every_column_non_empty(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        for r in rows:
            for col in RAFAEL_TXT_COLUMNS:
                val = r.get(col, "")
                self.assertNotEqual(val, "")
                self.assertIsNotNone(val)

    def test_tsv_writer_header_and_eol(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        body = format_rafael_tsv_body(rows)
        header = "\t".join(RAFAEL_TXT_COLUMNS)
        self.assertTrue(body.startswith(header + "\r\n"))
        self.assertTrue(body.endswith("\r\n"))
        self.assertEqual(len(body.split("\r\n")), 5)
        for line in body.rstrip("\r\n").split("\r\n"):
            self.assertEqual(line.count("\t"), len(RAFAEL_TXT_COLUMNS) - 1)


class PdfSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _PDF_CASES:
            raise unittest.SkipTest("Rafael RFQ PDF fixtures not found on this machine")

    def test_per_pdf_counts_and_globals(self):
        for case in _PDF_CASES:
            with self.subTest(pdf=case["path"].name):
                rfq = parse_rafael_rfq(case["path"])
                rows = flatten_rafael_to_rows(rfq)

                self.assertEqual(rfq.rfq_number, case["rfq"])
                self.assertEqual(rfq.buyer_name, case["buyer"])
                self.assertGreaterEqual(_hebrew_letter_count(rfq.buyer_name), 2)
                self.assertEqual(rfq.submission_date, case["submission_date"])
                self.assertEqual(rfq.submission_due_date, case["submission_date"])
                self.assertEqual(len(rfq.parts), case["parts"])
                self.assertEqual(len(rows), case["rows"])
                self.assertEqual([r["FAI"] for r in rows], case["fai"])

                for r in rows:
                    for col in RAFAEL_TXT_COLUMNS:
                        val = r.get(col, "")
                        self.assertNotIn(
                            val,
                            ("", None),
                            f"empty {col!r} in row {r.get('מספר שורה')}",
                        )
                    self.assertIsInstance(r["זמן אספקה בשבועות"], int)

    def test_type3_map_is_available_for_references(self):
        for case in _PDF_CASES:
            with self.subTest(pdf=case["path"].name):
                page_maps = _build_type3_font_code_maps_by_page(case["path"])
                decoded = {value for code_map in page_maps[0] for value in code_map.values()}
                self.assertIn("/", decoded)
                self.assertTrue({"0", "2", "5", "6", "8"}.issubset(decoded))
                self.assertIn("ז", decoded)
                self.assertIn("ץ", decoded)
                self.assertGreaterEqual(
                    sum(1 for value in decoded if "\u05d0" <= value <= "\u05ea"),
                    10,
                )

    def test_tsv_round_trip_is_clean(self):
        for case in _PDF_CASES:
            with self.subTest(pdf=case["path"].name):
                rfq = parse_rafael_rfq(case["path"])
                rows = flatten_rafael_to_rows(rfq)
                body = format_rafael_tsv_body(rows)
                lines = body.rstrip("\r\n").split("\r\n")
                self.assertEqual(len(lines), 1 + len(rows))
                body.encode("windows-1255", errors="strict")


if __name__ == "__main__":
    if os.environ.get("RAFAEL_TESTS_VERBOSE"):
        unittest.main(verbosity=2)
    else:
        unittest.main()
