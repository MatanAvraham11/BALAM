"""Export helpers for בל\"מ parsing."""

from __future__ import annotations

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

from parse_balam import (  # noqa: E402
    _MISSING_REV,
    parse_with_regex,
    revision_for_export,
)


def _balam_text_with_quantity(quantity: str) -> str:
    return (
        '600086525000 מ"לב רפסמ\n'
        'L. Moalem E82 ןיינק םש\n'
        "1 תורוש רפסמ\n"
        "10 הרוש רפסמ\n"
        '1099W640-001 קפס ט"קמ\n'
        f"{quantity} תשרדנ תומכ\n"
        "-:האצוה\n"
    )


class RevisionExportTests(unittest.TestCase):
    def test_missing_revision_blank(self):
        self.assertEqual(revision_for_export(_MISSING_REV), "")
        self.assertEqual(revision_for_export(f"  {_MISSING_REV}  "), "")

    def test_real_revision_unchanged(self):
        self.assertEqual(revision_for_export("A"), "A")
        self.assertEqual(revision_for_export("-"), "-")

    def test_parse_with_regex_preserves_plain_decimal_quantity(self):
        order = parse_with_regex(_balam_text_with_quantity("36.00"))

        self.assertIsNotNone(order)
        assert order is not None
        self.assertEqual(order.line_items[0].required_quantity, 36.0)

    def test_parse_with_regex_preserves_comma_thousands_quantity(self):
        order = parse_with_regex(_balam_text_with_quantity("1,495.00"))

        self.assertIsNotNone(order)
        assert order is not None
        self.assertEqual(order.line_items[0].required_quantity, 1495.0)

    def test_parse_with_regex_does_not_match_tail_of_bad_comma_quantity(self):
        self.assertIsNone(parse_with_regex(_balam_text_with_quantity("1,49.00")))


if __name__ == "__main__":
    unittest.main()
