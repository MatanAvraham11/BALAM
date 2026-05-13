"""Lightweight, dependency-free tests for ``parse_rafael_rfq``.

Two layers:

1. Pure-logic unit tests that always run (format conversions, FAI mapping,
   row flattening, TSV writer).
2. PDF smoke tests that *only* run when the three reference Rafael RFQ PDFs
   are present at their known absolute paths. Each asserts the
   per-PDF expected counts (parts × deliveries) plus that every row has
   all eight columns populated.

Run with::

    python3 -m unittest api.tests.test_parse_rafael_rfq

or directly::

    python3 api/tests/test_parse_rafael_rfq.py
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Allow ``python3 api/tests/test_parse_rafael_rfq.py`` (no PYTHONPATH magic).
_ROOT = Path(__file__).resolve().parents[2]
_API = _ROOT / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

# eval_type_backport keeps pydantic happy with PEP-604 unions on Py<3.10
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
    _buyer_from_email,
    _classify_fai_digit,
    _format_issue_date,
    _offset_days_to_date,
    _parse_dmy,
    flatten_rafael_to_rows,
    format_rafael_tsv_body,
    parse_rafael_rfq,
)

# ---------------------------------------------------------------------------
# Reference PDF fixtures (developer machine only — skipped in CI)
# ---------------------------------------------------------------------------

_FIXTURE_ROOT = Path(
    "/Users/matanavraham/Library/Application Support/Cursor/User/"
    "workspaceStorage/0d2fd20bb5cdba5e7b46d32eb8198854/pdfs"
)
_PDF_CASES = [
    {
        "path": _FIXTURE_ROOT / "8fa96acd-fb8c-4c76-b759-2dfaf37bdc31" / "RFQ_1294668_684471.pdf",
        "rfq": "684471",
        "buyer": "HAIMKA",
        "parts": 6,
        "rows": 8,
    },
    {
        "path": _FIXTURE_ROOT / "223a6d16-1352-497f-b37b-a387cf796767" / "RFQ_1294668_684070.pdf",
        "rfq": "684070",
        "buyer": "SSHIRAN",
        "parts": 1,
        "rows": 7,
    },
    {
        "path": _FIXTURE_ROOT / "a5520b41-7954-4125-b7e5-53912d3cb934" / "RFQ_1294668_684196 (1).pdf",
        "rfq": "684196",
        "buyer": "YOSSISH2",
        "parts": 5,
        "rows": 18,
    },
]


# ---------------------------------------------------------------------------
# Pure-logic tests
# ---------------------------------------------------------------------------

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


class OffsetDaysToDateTests(unittest.TestCase):
    def test_basic(self):
        ref = _parse_dmy("07/05/2026")
        self.assertEqual(_offset_days_to_date(ref, 0), "07/05/2026")
        self.assertEqual(_offset_days_to_date(ref, 16), "23/05/2026")

    def test_no_reference(self):
        self.assertEqual(_offset_days_to_date(None, 16), "")


class BuyerFromEmailTests(unittest.TestCase):
    def test_ldap_uppercase(self):
        self.assertEqual(_buyer_from_email("haimka@rafael.co.il"), "HAIMKA")
        self.assertEqual(_buyer_from_email("Sshiran@rafael.co.il"), "SSHIRAN")

    def test_no_at_sign(self):
        self.assertEqual(_buyer_from_email("no-email-here"), "")


class ClassifyFaiTests(unittest.TestCase):
    def test_valid_digits(self):
        self.assertEqual(_classify_fai_digit("1"), "FAI 1")
        self.assertEqual(_classify_fai_digit("2"), "FAI 2")
        self.assertEqual(_classify_fai_digit("3"), "FAI 3")

    def test_invalid_falls_back(self):
        self.assertEqual(_classify_fai_digit(None), FAI_NOT_REQUIRED)
        self.assertEqual(_classify_fai_digit(""), FAI_NOT_REQUIRED)
        self.assertEqual(_classify_fai_digit("9"), FAI_NOT_REQUIRED)
        self.assertEqual(_classify_fai_digit("X"), FAI_NOT_REQUIRED)


class FlattenAndWriteTests(unittest.TestCase):
    def _build_rfq(self) -> RafaelRfq:
        return RafaelRfq(
            rfq_number="684471",
            buyer_name="HAIMKA",
            submission_date="07/05/2026",
            parts=[
                PartBlock(
                    rafael_pn="BD01006",
                    deliveries=[
                        Delivery(quantity=12.0, delivery_date="12/05/2026", fai="FAI 2"),
                        Delivery(quantity=10.0, delivery_date="12/05/2026", fai=FAI_NOT_REQUIRED),
                    ],
                ),
                PartBlock(
                    rafael_pn="C24A1501A",
                    deliveries=[
                        Delivery(quantity=11.0, delivery_date="02/06/2026", fai=FAI_NOT_REQUIRED),
                    ],
                ),
            ],
        )

    def test_row_count_and_global_numbering(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["מספר שורה"] for r in rows], [1, 2, 3])

    def test_globals_repeated_per_row(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        for r in rows:
            self.assertEqual(r["מספר בלם"], "684471")
            self.assertEqual(r["שם קניין"], "HAIMKA")
            self.assertEqual(r["תאריך סופי להגשה"], "07/05/2026")

    def test_every_column_non_empty(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        for r in rows:
            for col in RAFAEL_TXT_COLUMNS:
                self.assertNotEqual(r.get(col, ""), "")
                self.assertIsNotNone(r.get(col))

    def test_tsv_writer_header_and_eol(self):
        rows = flatten_rafael_to_rows(self._build_rfq())
        body = format_rafael_tsv_body(rows)
        header = "\t".join(RAFAEL_TXT_COLUMNS)
        self.assertTrue(body.startswith(header + "\r\n"))
        self.assertTrue(body.endswith("\r\n"))
        # Header + 3 data lines + trailing empty after final CRLF split
        self.assertEqual(len(body.split("\r\n")), 5)
        for line in body.rstrip("\r\n").split("\r\n"):
            self.assertEqual(line.count("\t"), len(RAFAEL_TXT_COLUMNS) - 1)


# ---------------------------------------------------------------------------
# PDF-backed smoke tests (skipped if fixtures missing — e.g. CI)
# ---------------------------------------------------------------------------

class PdfSmokeTests(unittest.TestCase):
    """End-to-end parser run against the three reference RFQ PDFs.

    These only run on a developer machine that has the fixtures on disk;
    Vercel / CI environments simply skip them.
    """

    @classmethod
    def setUpClass(cls):
        if not all(c["path"].exists() for c in _PDF_CASES):
            raise unittest.SkipTest("Rafael RFQ fixtures not present on this machine")

    def test_per_pdf_counts_and_globals(self):
        for case in _PDF_CASES:
            with self.subTest(pdf=case["path"].name):
                rfq = parse_rafael_rfq(case["path"])
                rows = flatten_rafael_to_rows(rfq)

                self.assertEqual(rfq.rfq_number, case["rfq"])
                self.assertEqual(rfq.buyer_name, case["buyer"])
                self.assertIsNotNone(_parse_dmy(rfq.submission_date))
                self.assertEqual(len(rfq.parts), case["parts"])
                self.assertEqual(len(rows), case["rows"])

                for r in rows:
                    for col in RAFAEL_TXT_COLUMNS:
                        val = r.get(col, "")
                        self.assertNotIn(
                            val,
                            ("", None),
                            f"empty {col!r} in row {r.get('מספר שורה')}",
                        )

    def test_tsv_round_trip_is_clean(self):
        for case in _PDF_CASES:
            with self.subTest(pdf=case["path"].name):
                rfq = parse_rafael_rfq(case["path"])
                rows = flatten_rafael_to_rows(rfq)
                body = format_rafael_tsv_body(rows)
                # 1 header + N data rows + trailing CRLF
                lines = body.rstrip("\r\n").split("\r\n")
                self.assertEqual(len(lines), 1 + len(rows))
                # Encoding contract: windows-1255 must accept the body
                body.encode("windows-1255", errors="strict")


if __name__ == "__main__":
    # Friendly summary when invoked as a plain script.
    if os.environ.get("RAFAEL_TESTS_VERBOSE"):
        unittest.main(verbosity=2)
    else:
        unittest.main()
