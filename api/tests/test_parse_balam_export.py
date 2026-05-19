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


class RevisionExportTests(unittest.TestCase):
    def test_missing_revision_blank(self):
        self.assertEqual(revision_for_export(_MISSING_REV), "")
        self.assertEqual(revision_for_export(f"  {_MISSING_REV}  "), "")

    def test_real_revision_unchanged(self):
        self.assertEqual(revision_for_export("A"), "A")
        self.assertEqual(revision_for_export("-"), "-")

    def test_parse_with_regex_is_defined(self):
        self.assertTrue(callable(parse_with_regex))


if __name__ == "__main__":
    unittest.main()
