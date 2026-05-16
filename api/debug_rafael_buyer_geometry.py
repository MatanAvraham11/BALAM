#!/usr/bin/env python3
"""
Temporary debug: geometric words above Rafael e-mail / 073- phone on page 1.

Usage::

    python3 api/debug_rafael_buyer_geometry.py [path/to/RFQ_1294668_684471.pdf]

Defaults to Downloads + test fixture paths if no argument given.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pdfplumber

# Same order as tests
_CANDIDATES = [
    Path("/Users/matanavraham/Downloads/RFQ_1294668_684471.pdf"),
    Path(
        "/Users/matanavraham/Library/Application Support/Cursor/User/"
        "workspaceStorage/0d2fd20bb5cdba5e7b46d32eb8198854/pdfs/"
        "8fa96acd-fb8c-4c76-b759-2dfaf37bdc31/RFQ_1294668_684471.pdf",
    ),
]


def _pick_pdf(argv: list[str]) -> Path | None:
    if len(argv) > 1:
        p = Path(argv[1]).expanduser()
        return p if p.exists() else None
    for p in _CANDIDATES:
        if p.exists():
            return p
    return None


def _is_anchor(w: dict) -> bool:
    t = (w.get("text") or "").lower()
    if "@rafael.co.il" in t:
        return True
    if t.startswith("073") or t.startswith("073-"):
        return True
    return "073-" in t or t.startswith("073")


def _x_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    lo = max(a0, b0)
    hi = min(a1, b1)
    return max(0.0, hi - lo)


def _is_noise_anchor_row(w: dict) -> bool:
    t = (w.get("text") or "").replace("\u2212", "-")
    if "073" in t:
        return True
    if re.fullmatch(r"\d{6}", w.get("text") or ""):
        return True
    return False


def main() -> int:
    pdf_path = _pick_pdf(sys.argv)
    if pdf_path is None:
        print("No PDF found. Pass path:", file=sys.stderr)
        print(f"  {sys.argv[0]} /path/to/RFQ_1294668_684471.pdf", file=sys.stderr)
        return 1

    print("PDF:", pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(
            use_text_flow=False,
            keep_blank_chars=False,
            extra_attrs=["fontname", "size"],
        )
        all_chars = list(page.chars)

    anchors = [w for w in words if _is_anchor(w)]
    if not anchors:
        print("No anchor word (@rafael.co.il or 073-). Sample words in header (y<140):")
        for w in sorted(words, key=lambda x: (x["top"], x["x0"])):
            if float(w["top"]) < 140:
                print(" ", repr(w.get("text")), w)
        return 2

    # Prefer e-mail row as anchor (larger top = lower on page); else lowest 073- row.
    email_anchors = [
        w for w in anchors
        if "@rafael.co.il" in (w.get("text") or "").lower()
    ]
    if email_anchors:
        anchor = max(email_anchors, key=lambda w: float(w["top"]))
    else:
        anchor = min(anchors, key=lambda w: float(w["top"]))
    print("\n=== ALL ANCHOR CANDIDATES ===")
    for w in sorted(anchors, key=lambda x: float(x["top"])):
        print(
            " ",
            repr(w.get("text")),
            "x0,top,x1,bottom",
            float(w["x0"]),
            float(w["top"]),
            float(w["x1"]),
            float(w.get("bottom", w["top"])),
        )
    ax0, ax1 = float(anchor["x0"]), float(anchor["x1"])
    atop = float(anchor["top"])
    abottom = float(anchor.get("bottom", anchor["top"]))
    aw = ax1 - ax0

    print("\n=== ANCHOR ===")
    print("text:", repr(anchor.get("text")))
    print("x0, top, x1, bottom:", ax0, atop, ax1, abottom)
    print("size:", anchor.get("size"), "fontname:", anchor.get("fontname"))

    # Same column: horizontal overlap with anchor band (strict) or center within column slack
    col_slack_pt = max(8.0, aw * 0.35)
    # Relaxed vertical gap (pt) between candidate bottom and anchor top
    gap_lo, gap_hi = 0.0, 45.0
    # Strict: only the band immediately above the e-mail row (~one line)
    strict_gap_lo, strict_gap_hi = 2.0, 14.0

    def collect(g_lo: float, g_hi: float, skip_phone_like: bool) -> list[dict]:
        out: list[dict] = []
        for w in words:
            if skip_phone_like and _is_noise_anchor_row(w):
                continue
            wx0, wx1 = float(w["x0"]), float(w["x1"])
            wbottom = float(w.get("bottom", w["top"]))
            if wbottom >= atop - 0.5:
                continue
            gap = atop - wbottom
            if not (g_lo <= gap <= g_hi):
                continue
            overlap = _x_overlap(ax0, ax1, wx0, wx1)
            if overlap <= 0:
                if _x_overlap(ax0 - col_slack_pt, ax1 + col_slack_pt, wx0, wx1) <= 0:
                    continue
            out.append(w)
        out.sort(key=lambda w: float(w["x0"]))
        return out

    strict_candidates = collect(strict_gap_lo, strict_gap_hi, skip_phone_like=True)
    candidates = collect(gap_lo, gap_hi, skip_phone_like=False)

    print("\n=== STRICT: words ~one line above anchor (gap 2–14 pt, column overlap) ===")
    for w in strict_candidates:
        print(
            repr(w.get("text")),
            "x0,top,x1,bottom",
            float(w["x0"]),
            float(w["top"]),
            float(w["x1"]),
            float(w.get("bottom", w["top"])),
            "size",
            w.get("size"),
        )
    st_parts = [str(w.get("text") or "") for w in strict_candidates]
    st_text = "".join(st_parts)
    print("repr:", repr(st_text))
    print("hex ord:", [hex(ord(c)) for c in st_text])

    print("\n=== page.chars in STRICT union bbox ===")
    if strict_candidates:
        min_top = min(float(w["top"]) for w in strict_candidates) - 2
        max_bottom = max(float(w.get("bottom", w["top"])) for w in strict_candidates) + 2
        min_x = min(float(w["x0"]) for w in strict_candidates) - 2
        max_x = max(float(w["x1"]) for w in strict_candidates) + 2
        chs_s = [
            c
            for c in all_chars
            if min_x <= float(c["x0"]) <= max_x + 5
            and min_top - 1 <= float(c["top"]) <= max_bottom + 1
        ]
        chs_s.sort(key=lambda c: (float(c["top"]), float(c["x0"])))
        char_s = "".join(str(c.get("text") or "") for c in chs_s)
        print("repr:", repr(char_s))
        print("hex ord:", [hex(ord(c)) for c in char_s if len(c) == 1])

    print("\n=== RELAXED: words above anchor (gap 0–45 pt, column overlap) ===")
    for w in candidates:
        print(
            repr(w.get("text")),
            "x0,top,x1,bottom",
            float(w["x0"]),
            float(w["top"]),
            float(w["x1"]),
            float(w.get("bottom", w["top"])),
            "size",
            w.get("size"),
        )

    # Concatenate in reading order (top then x0)
    extracted_parts = [str(w.get("text") or "") for w in candidates]
    extracted_text = "".join(extracted_parts)
    # If user expects spaced words, also show space-joined
    extracted_spaced = " ".join(extracted_parts)

    print("\n=== CONCAT (no spaces) ===")
    print("repr:", repr(extracted_text))
    print("hex ord:", [hex(ord(c)) for c in extracted_text])

    print("\n=== SPACE-JOINED ===")
    print("repr:", repr(extracted_spaced))
    print("hex ord:", [hex(ord(c)) for c in extracted_spaced])

    # Also: chars API in same bbox for comparison
    print("\n=== page.chars in bbox (union of candidate words, expanded 2pt) ===")
    if candidates:
        min_top = min(float(w["top"]) for w in candidates) - 2
        max_bottom = max(float(w.get("bottom", w["top"])) for w in candidates) + 2
        min_x = min(float(w["x0"]) for w in candidates) - 2
        max_x = max(float(w["x1"]) for w in candidates) + 2
        chs = [
            c
            for c in all_chars
            if min_x <= float(c["x0"]) <= max_x + 20
            and min_top - 2 <= float(c["top"]) <= max_bottom + 2
        ]
        chs.sort(key=lambda c: (float(c["top"]), float(c["x0"])))
        char_text = "".join(str(c.get("text") or "") for c in chs)
        print("repr:", repr(char_text))
        print("hex ord:", [hex(ord(c)) for c in char_text if len(c) == 1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
