"""Lightweight tests for ``parse_rafael_rfq``.

1. Pure-logic unit tests (always run).
2. PDF smoke tests when reference RFQs exist on disk (Cursor workspace or Downloads).

Run::

    python3 -m unittest api.tests.test_parse_rafael_rfq
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

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
    _classify_fai_digit,
    _format_issue_date,
    _hebrew_letter_count,
    _parse_dmy,
    _tesseract_hebrew_ready,
    flatten_rafael_to_rows,
    format_rafael_tsv_body,
    parse_rafael_rfq,
)

_FIXTURE_ROOT = Path(
    "/Users/matanavraham/Library/Application Support/Cursor/User/"
    "workspaceStorage/0d2fd20bb5cdba5e7b46d32eb8198854/pdfs"
)
_DOWNLOADS = Path("/Users/matanavraham/Downloads")

_PDF_CASE_DEFS = [
    {
        "suffixes": [
            _FIXTURE_ROOT / "8fa96acd-fb8c-4c76-b759-2dfaf37bdc31" / "RFQ_1294668_684471.pdf",
            _DOWNLOADS / "RFQ_1294668_684471.pdf",
        ],
        "rfq": "684471",
        "buyer": "חיים קאופמן",
        "parts": 6,
        "rows": 8,
    },
    {
        "suffixes": [
            _FIXTURE_ROOT / "223a6d16-1352-497f-b37b-a387cf796767" / "RFQ_1294668_684070.pdf",
            _DOWNLOADS / "RFQ_1294668_684070.pdf",
        ],
        "rfq": "684070",
        "buyer": "שרה שירן",
        "parts": 1,
        "rows": 7,
    },
    {
        "suffixes": [
            _FIXTURE_ROOT / "a5520b41-7954-4125-b7e5-53912d3cb934" / "RFQ_1294668_684196 (1).pdf",
            _DOWNLOADS / "RFQ_1294668_684196 (1).pdf",
        ],
        "rfq": "684196",
        "buyer": "יוסי שני",
        "parts": 5,
        "rows": 18,
    },
]


def _resolve_pdf_cases() -> list[dict]:
    cases: list[dict] = []
    for d in _PDF_CASE_DEFS:
        path = next((p for p in d["suffixes"] if p.exists()), None)
        if path is None:
            continue
        cases.append({
            "path": path,
            "rfq": d["rfq"],
            "buyer": d["buyer"],
            "parts": d["parts"],
            "rows": d["rows"],
        })
    return cases


_PDF_CASES = _resolve_pdf_cases()


class FormatIssueDateTests(unittest.TestCase):
    def test_unicode_minus(self):
        self.assertEqual(_format_issue_date("04\u2212MAY\u221226"), "04/05/2026")

    def test_ascii_minus(self):
        self.assertEqual(_format_issue_date("04-MAY-26"), "04/05/2026")

    def test_invalid(self):
        self.assertEqual(_format_issue_date("not a date"), "")
        self.assertEqual(_format_issue_date("04-XYZ-26"), "")


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

    def test_invalid_falls_back(self):
        self.assertEqual(_classify_fai_digit(None), FAI_NOT_REQUIRED)
        self.assertEqual(_classify_fai_digit(""), FAI_NOT_REQUIRED)
        self.assertEqual(_classify_fai_digit("9"), FAI_NOT_REQUIRED)


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
                if _tesseract_hebrew_ready():
                    self.assertGreaterEqual(
                        _hebrew_letter_count(rfq.buyer_name),
                        2,
                        f"buyer_name={rfq.buyer_name!r} (expected Hebrew OCR; "
                        f"reference was {case['buyer']!r})",
                    )
                else:
                    self.assertEqual(
                        rfq.buyer_name,
                        "OCR Failed",
                        "without tesseract+heb+pytesseract buyer must not be guessed",
                    )
                self.assertIsNotNone(_parse_dmy(rfq.submission_date))
                self.assertEqual(len(rfq.parts), case["parts"])
                self.assertEqual(len(rows), case["rows"])

                for r in rows:
                    for col in RAFAEL_TXT_COLUMNS:
                        val = r.get(col, "")
                        if col == "שם קניין" and val == "":
                            continue
                        self.assertNotIn(
                            val,
                            ("", None),
                            f"empty {col!r} in row {r.get('מספר שורה')}",
                        )
                    self.assertIsInstance(r["זמן אספקה בשבועות"], int)

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
