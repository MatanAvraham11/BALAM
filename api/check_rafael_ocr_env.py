#!/usr/bin/env python3
"""Print Rafael buyer OCR environment status (V.5.9: OCR.space API key).

Run from repo root::

    python3 api/check_rafael_ocr_env.py

Or from ``api/``::

    python3 check_rafael_ocr_env.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_API = Path(__file__).resolve().parent
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from parse_rafael_rfq import rafael_buyer_ocr_diagnostic  # noqa: E402


def main() -> int:
    d = rafael_buyer_ocr_diagnostic()
    print("rafael_buyer_ocr_diagnostic:", d)
    return 0 if d.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
