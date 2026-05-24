#!/usr/bin/env python3
"""Smoke: parse a Rafael RFQ PDF and print buyer_name (V.5.9 OCR.space).

Requires ``OCR_SPACE_API_KEY``.

Usage::

    export OCR_SPACE_API_KEY=...
    python3 api/test_rafael_ocr_space.py /path/to/RFQ.pdf
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_API = Path(__file__).resolve().parent
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from parse_rafael_rfq import parse_rafael_rfq  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "Usage: python3 api/test_rafael_ocr_space.py <path-to-rfq.pdf>",
            file=sys.stderr,
        )
        return 2
    if not (os.environ.get("OCR_SPACE_API_KEY") or "").strip():
        print("Set OCR_SPACE_API_KEY in the environment.", file=sys.stderr)
        return 1
    pdf_path = Path(sys.argv[1]).expanduser().resolve()
    if not pdf_path.is_file():
        print(f"Not a file: {pdf_path}", file=sys.stderr)
        return 1

    rfq = parse_rafael_rfq(pdf_path)
    print("buyer_name:", repr(rfq.buyer_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
