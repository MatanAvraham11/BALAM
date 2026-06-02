"""
Rafael BOM (RFQ) parser — Type3 text decoder.

Rafael RFQ PDFs are landscape A4 with a custom subset font whose CMap is
broken for the Hebrew labels (every Hebrew glyph extracts as a
private-use codepoint at ``size = 0``). The numeric and ASCII data,
however, lives in real text spans with ``size > 0`` and stable
``x``-coordinates. The buyer name and cover-letter submission deadline use
the broken Type3 font, so this parser decodes those glyphs by hashing the
embedded ``CharProc`` drawing streams and mapping known Rafael glyph shapes
to Unicode.

Globals (page-header band, y ≲ 140 pt)
    * RFQ number      — sz=10, x≈133–163, y≈55
    * Buyer name      — Type3 ``CharProc`` hash decode from the buyer-name row.
      The row is located relative to the ``…@rafael.co.il`` word; the decoded
      visual RTL glyph order is then converted to logical Hebrew word order.
    * Buyer email     — sz=9,  x≈100–180, y≈100     (geometry anchor)
    * Submission date — Type3 ``CharProc`` hash decode from the page-1 cover
      deadline line (``…לא יאוחר מיום DD/MM/YYYY בשעה…``), with no fallback to
      unrelated dates in later pages.

Locals (per delivery row, repeating per part block)
    * Quantity         — sz=9, x≈266–290     (``\\d+\\.\\d{2}``)
    * Weeks ARO        — sz=8, x≈358–372     (integer, ``זמן אספקה בשבועות`` column in PDF)
    * ``Each`` unit    — sz=9, x≈503–521
    * Rafael part #    — sz=8, x≈731–779     (alphanumeric all-caps)
    * FAI              — either sz=8 ASCII ``FAI−`` + digit, or Type3
      ``לא נדרש`` in the same x-band.

Export TXT: eight tab-separated columns, ``\u05de\u05e1\u05e4\u05e8 \u05e9\u05d5\u05e8\u05d4`` first,
then globals + locals (``\u05d6\u05de\u05df \u05d0\u05e1\u05e4\u05e7\u05d4 \u05d1\u05e9\u05d1\u05d5\u05e2\u05d5\u05ea`` = integer weeks, not a calendar date).
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import pdfplumber
from pdfminer.encodingdb import EncodingDB
from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

FAI_NOT_REQUIRED = "לא נדרש"


class Delivery(BaseModel):
    quantity: float = Field(description="כמות נדרשת")
    weeks_aro: int = Field(
        description="זמן אספקה בשבועות — מספר שלם מעמודת ARO ב-PDF",
    )
    fai: str = Field(
        description='"FAI 1" / "FAI 2" / "FAI 3" / "לא נדרש"',
    )


class PartBlock(BaseModel):
    rafael_pn: str = Field(description="מקט רפאל")
    deliveries: list[Delivery]


class RafaelRfq(BaseModel):
    rfq_number: str = Field(description='מספר בלם')
    buyer_name: str = Field(description="שם קניין")
    submission_date: str = Field(description="תאריך סופי להגשה (dd/mm/yyyy)")
    parts: list[PartBlock]

    @computed_field
    @property
    def submission_due_date(self) -> str:
        """Same value as ``submission_date`` (explicit API / client alias)."""
        return self.submission_date


# ---------------------------------------------------------------------------
# Coordinate-band constants (calibrated against the three reference RFQs)
# ---------------------------------------------------------------------------

# Page-header band (globals)
_RFQ_X = (128.0, 168.0)
_RFQ_Y = (50.0, 62.0)
_EMAIL_X_MAX = 200.0
_EMAIL_Y = (86.0, 112.0)

# Buyer-name Type3 crop (calibrated against 3 reference Rafael RFQs).
# Goal: include ONLY the buyer-name glyphs — no "קניין:" label, no neighbor
# cells (date/phone), no borders.
#
# Calibration (PUA glyph positions from pdfplumber on 3 PDFs):
#   - Buyer-name characters span x ≈ 115–180pt (longest name "שירן סורני שלאם").
#   - "קניין:" label characters span x ≈ 189–206pt (consistent across PDFs).
#   - Email anchor: x0 ≈ 100–104, x1 ≈ 180.7–180.8, top ≈ 100.3.
#   - Buyer-name row Hebrew glyphs centred at top ≈ 82.9 (band ≈ 78–87pt).
#
# Crop coordinates (relative to email anchor `e`):
#   clip_x0 = e.x0 - 15      → ≈ 85–89pt (leftmost name char ~115; safe margin)
#   clip_x1 = e.x1 + 2       → ≈ 183pt   (right of name end 176pt, LEFT of label start 189pt)
#   clip_y0 = e.top - 27     → ≈ 73pt    (+5pt headroom above name glyphs at top≈83)
#   clip_y1 = e.top - 13     → ≈ 87pt    (above phone row at top=88)
_BUYER_CROP_PAD_X0_LEFT = 15.0
_BUYER_CROP_X1_PAD_RIGHT = 2.0
_BUYER_CROP_DELTA_TOP = 27.0
_BUYER_CROP_DELTA_BOTTOM = 13.0
_BUYER_WORD_GAP_MIN = 7.0

# Cover-letter **submission deadline** line (``…לא יאוחר מיום DD/MM/YYYY בשעה…``).
# Hebrew is not extractable in the PDF text layer; geometry is stable on the three
# reference RFQs (landscape A4). We anchor the vertical band to the e-mail row
# (``…@rafael.co.il`` at ``top ≈ 100.3``) and place the deadline line ~76 pt below it.
#
# Horizontal window (calibrated visually on reference RFQs):
#   _SUB_DUE_CROP_X0 = 283 pt  — just before the first DD digit at x≈284.7
#   _SUB_DUE_CROP_X1 = 327.5 pt — after the last YYYY digit, before the next Hebrew glyph
# In PyMuPDF, x increases left→right; Hebrew RTL means the date sits at lower x.
_SUB_DUE_CROP_X0 = 283.0
_SUB_DUE_CROP_X1 = 327.5
_SUB_DUE_ANCHOR_TOP_OFF_FROM_EMAIL = 76.0
_SUB_DUE_ANCHOR_LINE_HEIGHT = 8.0
_SUB_DUE_CROP_PAD_Y = 2.5

# Per-row column x-bands
_QTY_X = (255.0, 295.0)
_OFFSET_X = (355.0, 380.0)
_EACH_X = (495.0, 525.0)
_PARTNUM_X = (725.0, 785.0)
_FAI_FLAG_X = (28.0, 50.0)
_FAI_DIGIT_X = (32.0, 45.0)

# Vertical tolerance when grouping items into the same row band
_ROW_Y_TOL = 4.0
# FAI marker (``FAI−``) sits ~9 pt above its accompanying digit. We accept a
# digit whose y is in (marker.top, marker.top + _FAI_DIGIT_DY_MAX).
_FAI_DIGIT_DY_MAX = 15.0
# ``לא נדרש`` is rendered as two Type3 Hebrew lines in the FAI cell, with the
# first line beginning ~7 pt below the quantity row top.
_FAI_NOT_REQUIRED_X = (28.0, 48.0)
_FAI_NOT_REQUIRED_DY = (-1.0, 22.0)
_TYPE3_LINE_Y_TOL = 2.0

# Words above this y are inside the page-header band and never table data
_HEADER_Y_MAX = 140.0

# Submission-date pattern (dd/mm/yyyy)
_RE_SUB_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
# Rafael part-number heuristic — uppercase alnum, has at least one digit
_RE_PARTNUM = re.compile(r"^(?=.*\d)[A-Z][A-Z0-9]{4,12}$")
# Quantity / integer / decimal helpers
_RE_QTY = re.compile(r"^\d+\.\d{1,3}$")
_RE_INT = re.compile(r"^\d+$")

# Keep only words whose text is printable ASCII + Unicode minus
_ASCII_OK = re.compile(r"^[\u0020-\u007E\u2212]+$")


def _hebrew_letter_count(text: str) -> int:
    """Count characters in the Hebrew letter range U+05D0–U+05EA (Aleph–Tav)."""
    return sum(1 for c in text if "\u05d0" <= c <= "\u05ea")


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _page_clean_words(page: Any) -> list[dict[str, Any]]:
    """Return only the real-text words (size > 0, printable ASCII)."""
    raw = page.extract_words(
        use_text_flow=False,
        keep_blank_chars=False,
        extra_attrs=["size", "fontname"],
    )
    out: list[dict[str, Any]] = []
    for w in raw:
        if (w.get("size") or 0) <= 0:
            continue
        text = w.get("text") or ""
        if not _ASCII_OK.match(text):
            continue
        out.append({
            "text": text,
            "x0": float(w["x0"]),
            "x1": float(w["x1"]),
            "top": float(w["top"]),
            "size": float(w["size"]),
        })
    return out


def _in_x(word: dict[str, Any], lo: float, hi: float) -> bool:
    cx = (word["x0"] + word["x1"]) / 2
    return lo <= cx <= hi


def _y_close(a: float, b: float, tol: float = _ROW_Y_TOL) -> bool:
    return abs(a - b) <= tol


def _parse_dmy(token: str) -> date | None:
    if not token or not _RE_SUB_DATE.match(token):
        return None
    try:
        return datetime.strptime(token, "%d/%m/%Y").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Type3 glyph decoder
# ---------------------------------------------------------------------------

# Rafael/Ghostscript Type3 PDFs do not include /ToUnicode. The same visual glyph
# may be assigned different character codes in different RFQs, but its embedded
# CharProc drawing stream hash is stable. These SHA-256 keys were derived from
# the three reference RFQs:
#   RFQ_1294668_684471.pdf, RFQ_1294668_684196.pdf, RFQ_1294668_684070.pdf
_TYPE3_HASH_TO_TEXT: dict[str, str] = {
    # Deadline-line digits / punctuation.
    "4594cc4bd532242ffa807f2d2da388076dc3b5786e0a16859af70ed50df5ca15": "0",
    "b56392ec983e3f4b026d038d1528497fed06c0c4db085eac6d8afd04aa150919": "1",
    "23a3c548b61ac8087457ffc4162c6e3ac0707ba9286ac2deac1a20c147f9c1b1": "2",
    "05409664a5ea9cd1ce125b002e095a424d20455e64da00823954fb535573a5a8": "3",
    "23517018156af56f7ca4a5fba565b2408dae98c1e645f137e2b146bd5c72c4e6": "4",
    "ef5d813774a799c453c30679e9802f874caa5f0aa9f97c8426dbe4994ad624ce": "4",
    "818364aff90579ff32df11bf9603c9a6b8bebf1e6dd59c2b76b316b53d3e4ed8": "5",
    "082a2e1d5dc834484b1aaa2788fbaf93937170df3236faa74d0a27df6341ed0f": "5",
    "16d96527105b248dd06b5b06997c58a82b040aa0aa33300f79888b4d0af150a1": "5",
    "4b9fb7e9cf292807c07e71e7677032397ff21bd6eefe08ea7318808209290a90": "6",
    "ec1110846a0b3153d9014e12d811ad5b72a0765528b659eb246d794a7ab13140": "8",
    "9d162affd6f0255bb55c3ec30a50017719907bea94c6540fcd1d34329cd1e61d": "/",
    "20c841fab8a2c3ba10e7f3bd386ec84711d7ba467f673914f0962c247b0ab480": ":",
    "743c7bba5aca057f93b11420170334e19e9a5b783a2c188ed117438e4d7f360a": "(",
    "b5b62baf2a8e0eb889864ec651eba2c3a92a5a444d97e92c32388a3470183278": ")",
    "32148d4ca995ec89c736e6ff1970b1aa33f5f966c4e26bc7d88209a096152507": "'",
    "6a7a1d0230c4b94b69f0be539450b689f21f16df468e702a57b127d4cdc6eaad": '"',
    "9e1c00c58eb0b8247d396bb2013f9c13fb96f62eec0dd9ad3c8d67a15013ff3f": '"',
    "a295ea79580eec22e3fe7ca3deb782d0dd65e7fc417661e736e66469fd7600fd": '"',
    "adc01172e6b6a6e9340cc0158459dcdc64525b5922dfffa669ccd567ebfe3773": '"',
    "b6566afa633cadbe85d3e1d166cc790bd4d8c829999b4f6c35536b8daf9a10bd": '"',
    "8173f761f049a36c23b03f621f42cbd125a0bbb7255bad130106256354ed6139": "-",
    "8d575fdf2afd34cd1b129c24b575f3b6053aef5104d0f8b5db3dee35c0e07b54": "-",
    "fa6d347fb9702566a9a614ac6bc7535159299478a769cc014121ae18ad59088e": ",",
    "04fea07d089872d04b645bbbee38ddf08b0e90f3a406f9e70dbac7080b71e012": ".",
    "5b7bfb287af7094f3dbc673065f34a26e0c5d9ce3cc381b53c5c77cbd003f9c3": ".",
    "867180d910ff21aca8912a1e735b372df1890e185c5b6aed0bad14434d4d4ba9": ".",
    "c2acbc6405fc23d1b89054183481e08dc45e203b6b746a3100d400d39e9322d4": ".",
    "f2cb5ae6340c82f03f8e4255faaf58cb5aa26bc9e65ba77a240b2c06125b9cc0": ".",
    "1980dd7ed52839991e3e3c1c2dd1735ef40d2524efdaa3fa6a225922f67cf59c": ":",
    "c7a966ed3d3e17a02740b10a4283f6ea6b8a49a7450ef1a0493f73b88089171c": ":",
    "ce15115c5b233a04f25f7fef4522ca04f981ff4fc2135dcdabf767f7bdf75b33": ":",
    "877f41b83616868fe528ec412412b08d0b7bb30b1fcd71edf99ccdb08ad4d364": ":",
    "265cc42137dd6fb2dd133a5b74a148e38141ddb622624b4279f6117545e4c9c3": "<",
    "69a95cd5b167fe14f65010bd166932a5e80af37808dbba67b963c36e67598ed8": ">",
    "64f58381a0fda49275aa594a2b02c510cb0f38cd2ce1acc37e9f7a9af442b768": "0",
    "ac5aa239c04d621b8852e5e688385e470086420c453a2d0c1df041173b577be4": "0",
    "53548cbe91908a6d797553b75ce3db5ba4f6dee0a74fcce01049553032da8b54": "1",
    "df3662481869438d55fb1c5dc00a789d4b6cec2e7c8159a2369fde35588082ef": "6",
    # Hebrew glyphs observed in buyer-name rows, FAI cells, and fixed cover/header text.
    "bfef2dca66b9b664c9ae6b6963f54d80af0834d898ccc3ba24d1c4aa70f4c909": "א",
    "46ebe86002f718d100e6bd5465559df0378c98c45d4ddde77edf1c216912c8a6": "א",
    "4b29afb94320e1b15ddc3a8e082ba322d18540298b87b806536f249a85bc084b": "א",
    "59738c7ff0a580c6bd5be92133ec13567a5b5f613cc48dd98078851603436b68": "א",
    "697374b3873e030719978088f2c1835acd1418f95b87f4ebb0711c7518db1687": "א",
    "adb0f3af33960447a0ce1b7f2a7c981568d18c55d21d2667a91ea9f0bdaebccb": "א",
    "7bfc51fbbbc40ff128009fce4c956104b060c1a2f3f1a08305fd9eb2d12cdc17": "ב",
    "5bb60e00cae70c106a5fc317a6c5d9f513a56ef0ca6eda6786807473910a6ce3": "ב",
    "ba048a32e9d98f175163756a4750fc2e3e959bd85232da3e16c342c97e3c5284": "ב",
    "d55ff7c3c5cf8635d869eba7a1b5c05636ecfc78cec6f83cf05d96923178514c": "ב",
    "eebca048843c42931cded93ed90539ca846fb124b7f36dc1f96732a132248347": "ב",
    "9255971c6892cbf2d8585b2588c15c2c9b91dc54f12c48630e1c95518d820a9b": "ב",
    "1469801faeb762fbbee30c18c3ccdd3b226027500d4781a205571363bbb82f2e": "ג",
    "11d6b0081dc621e4eb67abb6c158bdbd2adc3d8054492c7f58c4f075041be1af": "ג",
    "1cb015fda4b3606f9ece7547b1f386409f76e85fb823c80c191603e7d136b39b": "ג",
    "294817eccbb4ee1622592c8e5a242c84e44febe90b449e04b072d822084af9b6": "ג",
    "45720f26fc4eb79aff7a5200ef1207bf86a28b1b539c398df0dfced3ec7983d2": "ג",
    "ecbb837b39cdaa99674624c25443398111297ea92e43fe6dba8e693875a86e62": "ג",
    "1aa5ffddd495c4f84aea46bc7df6d8118fb7e1adf09128d7e5c5da78ddd95ea5": "ד",
    "bae695a68ff254ab6a95f3b2976fda933dd1c98f60e9b2b10dc92a58a098df4a": "ד",
    "bf6a367de6b283333e4fa2a81255e98296eddd85df95598779163b645658a12d": "ד",
    "28540c5e5253c8a5ce434d5bb7ad9ac465d405be475144cb1a09b031235e204e": "ד",
    "e1ffa8c3656282c7e9c1a0e10e96693911bbba845c921b864f10955df063cd63": "ד",
    "208f34789991c97711aae3881e6109486c67b5e0507ee9c2a221e5dedf9b53fb": "ד",
    "9698335ef0fe23240ee6c37c59a21fb6f9c61f6dbffa68649020da480d737714": "ד",
    "29f458771d1c4a1e4e2b265c71b89cb26833827e8203b5114a3be5abfeb01435": "ה",
    "5096f0a73cf3b90b1ae8737e3b95a22ff4888fe5a021f06d6116c61b7aa2352f": "ה",
    "78b5c9f90b2468b9113d72b4ee560ac7d83f2b092063e8b1716a08785bcd7368": "ה",
    "d490dfefc65a6296e7166cbc11ea6b3ec016b58bc2e82d4bcabab3629b1d9904": "ה",
    "e446fd17f46e37ebe30aa543d1a8ca7031526f6b12b76506165e128533a70e44": "ה",
    "16089fb99414c7b666075558b18a438fff1e5ec63bb58fe89e6462dff711b239": "ה",
    "0084b50a7ba79068f7668ea72a14f457c3b11a5cfc068af2f07b14b8b9762c9d": "ו",
    "83354eecd142d1cad27c8b8cebd838da17bbc159127964a9ff61741faa03f0cd": "ו",
    "bed2a158ad2ea115a170d97cde581d4409d6915c3b6f1b20ad9d091b53e64107": "ו",
    "d95d4a43754322354949087d4e0651f7ed035e72a180815259a866e91e45f344": "ו",
    "e2c8aad0c4721f9362e7281b9ea96df79541147f53151bfcc4a6d3d25fa70449": "ו",
    "5ebeec7addb9f820c6379d9d70efa3d961fe42433a00a44b1f95cfdc0ae3c061": "ו",
    "fde49b0bfc33d52a6463a6bfb7a6a006579e8ff99907cb4a2c73ec5914952c02": "ו",
    "f734b24ca660bd851f19faf51ccfa0d7552ac017e29aebf91410ec9b18cddaf8": "ו",
    "3a2f9e8ad3d6f9742923d859003beb5815ffcca86a183946b1c6e88d89e501fc": "ז",
    "a054ec532ea03ac858578d383577917ac1e07470a46a9d937d6fcea670622882": "ז",
    "1871772ea5077373834c33b855493591ae9c5ab74f086a54978989819474b9c6": "ח",
    "096f78ce3964f2053bb81be357160822f539a89cf070946d8efb0d4ee3ee91a9": "ט",
    "b522b60a6bd8f43a754a1d7c22a907af2e586346ec28878e8e86060c47ccb88f": "ט",
    "e7592f4becf151997b967d3b1299638aa7d2564ef7bf49a7203e2dcf546c48c6": "ט",
    "bec341506f453b5e4af73f8c1e59ccbc279ef719f92359289d35c4237822ed47": "י",
    "e296e51b94c15f31878b94f86593ae4ccb6d693b9cff0d3f1fecf7be2fdb6ca9": "י",
    "299b789a6a73aebb64cc1b53b91fe1c7bbe49f0a129279e3084e156761cca454": "י",
    "e4d14aa431e399ce8da5ff5556610383871e8bd41690dd089fa84baa62401fbf": "י",
    "76625f8c3c4762a24bcf3dbf19941eac59276d6fc64fc579108e9e629b39aaa6": "כ",
    "ffae45ec95465a4ab76edc5098e8e7c167c7ef757024fa8a3820ef3386c533df": "כ",
    "1406f633a0b3a5cae0983ebb909f3acffa7c099048f2e61c5ea0f0c7a8b5ab84": "ך",
    "46d8f1353c1d4b938c4bbb198b4c6be4bab09ea73945b8ce8dbe0ff20bb2970a": "ך",
    "5627888df8619c5300e1acd696b4df2e11c577137225e9579698c55ccb161173": "ך",
    "902b4dbb2e94a6770d781ce52eb3455b44690c186a7061a6d9d150d21e5b6dfd": "ך",
    "2b5d57fa025cc161eacc3e145d70f0d4b91ccd99e736e1c9dc8fd346d9946e2f": "ל",
    "4987d3d832d21774287acb2646afc10aaffe4f6a5ed127c24559368fd00eb24f": "ל",
    "0a9f672a77485c759661926c0f4e98e9189c2d2bba88b69b918078f3b11afa17": "ל",
    "5b1ef2aa58fb4fb01ad6e13ff934ad2626b55ee40d75f2985e370aa3a9e4c969": "כ",
    "791dc1b8c9270a63859bb1e05e9e1bf89ebc4e5fccd24ce790ef3445a72c1fd4": "ל",
    "b50f0297940a1a14c47f647d8f5e4a5d3ca3d84e37c9f583fc8f4743a9e758e3": "ל",
    "752e1e8775d899b74ccdc9a1954fbcbaaca5be2c62434f7c870c2b7b7570dc80": "ל",
    "9e1e2c7d0163cf5d667f51d054268c99812c013adab8747d2ab4a0eab2d4f21c": "ל",
    "6d9045f00031c828ee9175f7fd3c228d133e201c04ec98e85646a407e24c5931": "ם",
    "779936c9f74c9030e7386a61bbbce13c4e390772b984027e3f9b83765a6a6203": "ם",
    "82a3af1cc758d55777b3c744e6fe456ab2041da9e480aaa224935ed971fe8ca5": "ם",
    "904fb3f15cfa2371ae3796f5dc04780d3c2614c31cb6945be644e0e8cd574bdd": "ם",
    "0bcb8ecfeb70df133ca50ba361f89c5486937b35f0d95f5f2658f8b9b514cd75": "מ",
    "0086aa740444e76fa4a9a0cafd9fb4473bee5cc2da6860016904d472c89efe6b": "מ",
    "191c227b14bdec770449b0729490b908a29ac3b9bf0b6401857f1989df5b7789": "מ",
    "50e292245f130f3fb45f28cdc70645704ba7bea0d7082732267aca815afdfbb2": "מ",
    "5de3f2ca45fbccd6b1dff0f9f7ff28e9222cb8539413b4a38d1a9ec211814591": "מ",
    "8f660eadd166f48e23679bee02cf9bd09ba80651a9ef3efbf26a68c192c00797": "מ",
    "d63c6dc3a8e62440d8e294907f15b3684baa1dffc58e5c6e036591343c4e8dd3": "מ",
    "06247e03fffb3a45ac12e73a5ff98ef0810778cc5a4c927d203fe708590d821f": "ן",
    "584522621b1f75709b6de4b78a70adffad554d1073cecf71b29ad417c5d5f7bb": "ן",
    "6b690d64cbf6bf253c4ac87b5fc62be53424efcdf9949ee1892664cd337efd10": "ן",
    "948eebbd1c56b6f079792c6905d2bd4a2a0cf2ac5de3ca1036164b1259e27944": "ן",
    "9ed384802a47b8132bf709b617c6ea0637b317c9525758179cc55f368ca7c3f7": "ן",
    "a7bbf0360b362878e85457f1dd0465445047843f8d5e70236036b58ddd928b2b": "ן",
    "3fc079ac8ed65bc22f1134280b493a943addf66464a0fa6fc7657804612ed20b": "נ",
    "682d02f1bb2a51a863b94edc0b73949526924fec2c28fdb5db7c64d582880de7": "נ",
    "a3650d78be7a8a763d1ebc4ef35cd2deee56a986694084cd22a489a4da50db6b": "נ",
    "475a61da5d22a0f26a3a9930c3bbb5f911b37256fd5bad68a78d4b0d58680aba": "נ",
    "c652c810414768e20c33a0606c631b10123355754481f772990382f41dd8d17a": "נ",
    "d9466ab70f7b00359244aac55dc6842e0524b5a3908aa040a644737ca204cba3": "נ",
    "3dd6874c6ac0166787addbaca73a713db9a46f9eb436a94c08ed4475a3d3d7d2": "ס",
    "6d55ebafa2e463f6143436eb1ccf5bf3ad3aad0553784741079ecd60532fd6e5": "ס",
    "a8fb1d40aa6e136858108abb7b9a32261d597f16ce8a650f45a6f7060d58e624": "ס",
    "e771f5b7f01b6d1d23d97fa4a4ead1f1b18c04d214fdec6fef732ae8ce364c24": "ס",
    "f6f9080a7673722feeef975ea2b08cb4b714e1e5782f57fdcf3d0f40a417f218": "ס",
    "a2bfe31bb52f8f28d8760945e1694a6f2a526a69408bb6ae6043b5929bd27af9": "ע",
    "03d2a342eabf02157718ad5b420519027f28a0ea8352b1a2387a05e0c96939d0": "ע",
    "6b569ebe3126c1bb184e2b625dcfe54e11167a066455db41f47830332b683c07": "ע",
    "a6ac9b32c29e8d9748c827f4229f88f59d1a04d57fde36391b35bc1f9e8281a5": "ע",
    "c2bbe411573717bb2aef4f4f12ce29f7539a9cd38f755220f4046c8b86edfe56": "ע",
    "e47ab8e0780278d77feb7fdc865549363ff86d943b47d28679c636f3e0ff8590": "ע",
    "f716abe841565dd144e8ef2c894c13dba72ffc28ba36c8d26fba013114d200ea": "ע",
    "86568e28a476306094b16acbc613d898ac66db9e3e817c3aae07455c3babf0c0": "פ",
    "e8d56fb4f4b417674f67c9e06adef787a14a2635b6ef325d835eff21cb7058bb": "פ",
    "ec6d21e93543214ee11e682c263bb583d40aa110bfec2a840992f96d4d772bea": "פ",
    "949cdb33b933814d1ddb0f59a638ce5b5d1b791e89e4ad4bdfe83e1a1d02e64e": "פ",
    "f38f95cd30c2ed7433cf88a2f348e14ad47f283c5b20ada9190d525b2b1660fb": "פ",
    "ad29fec1cb1b4ce53e73969a09f1f1575950db75a126f25df6f2b8225bb3eb55": "ץ",
    "37beb4774d5e2e274772e98747a94c8e4df3b699c3e6f76b910392345cb3579d": "צ",
    "45da13848a1de8d406a716601b2d89cddb18bcdd435ced48814a9a91bf28f6ff": "צ",
    "ea53699503359a7f8b7ea33efdfca37512a1173fa8b658510e8535f5d9aa07ce": "צ",
    "f5489432f73bf3826ae5171ab06e860ce109870dffa288ae7ba0c36b62f73c3d": "צ",
    "03f9377fadbffb88b8f98815ab571170c230dfeec9c362babbc3a1014594dddd": "ק",
    "b0a020921b44b47a3c0e5140b093a4392ed20a8f58bcb9b2bbfde404ffe9bd27": "ק",
    "5cbbdcc8e8ec340009b9f6d433443fca767945e02523ebe11766a6036cdef21e": "ק",
    "86bda205f30cfd299b3001677355567c25c79071e78b43ab2a4a3959aba0cc5e": "ק",
    "f5207dc0bf1cf43cce5628b2212fc85ec5b7a69cbe8069f52a09f36b7e955c5f": "ק",
    "1252e37c31c13b387f08bc0dffa862c1af62cd7f3381ee3bcf52062f7b5e4b39": "ר",
    "4af553522056258f3858c9dde5049360fe799a01865420da1e0b9b19b42c5e35": "ר",
    "523d13fe9e98b6701efdd1e81f77a79a0034863d77a36bbe09aff33597f41fda": "ר",
    "52dabaaa4c0d28147fcf0d110cf4147a4f1bd93f50f24290d441fe56278a8415": "ר",
    "8d05cdb788d6974306e0fe6e11e16c773ac8dfab9a8da41c04225ef796f8f60a": "ר",
    "e86bd0f482379d1cfeef978cb43a6b4b2bc0c6f914aa4861c67edec89a0ade38": "ר",
    "1caa0a3cf28ff09a659f194b7e84cf0fa79bb0250e4d31ef0c50dce0e572970a": "ר",
    "1bce9de331b8ef705787d5d46ebb10e3f081cbc088fa0b2af5a18cc21feb3cf8": "ש",
    "54208eb6dce8c5230069438d8e31cc3e69c67fc10ca0ece6c77e2924ca6179e4": "ש",
    "563075e2d13a56126d91d3fa99cbc6cd1e19620969c95e6cf3e69a839e7cf335": "ש",
    "67d37086acf15c488f366be228b41a31428b5968524275464e4a154d9bf6003a": "ש",
    "723d6d22853fef8f392247094f60c09844274ca3c14b42e8309903d9d00b16eb": "ש",
    "98650631b6c21afc035279022eaac91ab8399e2ed29807243f70f036d080a508": "ש",
    "a5cd576fefa58b0a82ab275cd39c4b1cb2a0a441ea770aa37a526558b8af3f4a": "ש",
    "a678a44bbaabb9e9a1c150a2a7f107801c6d63c9fc85fbff67c04b369d39f520": "ש",
    "0140b3fca3465f2e6f9d22077ff728010f633f3450beb824f05a45c510b039a0": "ש",
    "fddca80de4d95f668d2afd4a790283b17c71500b3e4020e40d6dbe95eba33919": "ש",
    "0200591fc57f43ce636bf5a6db9d1a519d8b4f92881b56430972c6e619335edc": "ח",
    "f4254820e194515c8c9af264746e73d19822ea0e7ff588345d12b3f864444099": "ח",
    "8fafef30fe239c1e2efe1f556363f469950ccc2d1bba151ca61d4751df7e7a76": "ת",
    "31f1d46e8a860a135e92e170744e6d75acf8d2840b6808f550f4f21d8a48e4d3": "ת",
    "3b2ecb64f35ce3d9877c2d4ef9c4c6bf53e1a1b86ed60e766fc41dfb2f116637": "ת",
    "3df228426d8526c887681e1f08d663f5a2e5fb72da155053189d6887830cfc1d": "ת",
    "0b034d9542be0519c1ed6f6659b0d8e0e42ce47a0fd33aa13d4015f3e65a985a": "ת",
    "c9f2da11276fed00edc374a4f2e16614c9c0638f170c7a90e0210e108175ef67": "ת",
    "d915fec2cce71a5090f46ba8c86f11ff3168f06b92c66edbc414699427dc1f86": "ת",
    "e4194f87bc8897496a2768c61ccf0d82bfe5793aea615973cd91a89f269c9756": "ת",
    "ee7fb6adda4065ff5c93297ad1cc8dad186751d000250465c6461be8280a8618": "ת",
    "ec500f5b03775a032597f7488f57990dcd0e53bfe43f5eded3147753c862cd4d": "ת",
    "95e19dede79b2b7f92f7a036f6513d5a1b6a7cca9d3cce0d71f9a130d5a0c399": "ת",
}

_TYPE3_TEXT_TO_CODE_OVERRIDES: dict[str, int] = {
    "\u0192": 134,
    "\u2044": 135,
    "\u2018": 143,
    "\u2019": 144,
    "\u0141": 149,
    "\u0142": 155,
    "\u0153": 156,
}
_TYPE3_STANDARD_TEXT_TO_CODE: dict[str, int] = {
    text: code for code, text in EncodingDB.std2unicode.items()
}


def _type3_code_from_pdf_text(text: str) -> int | None:
    """Return the Type3 character code represented by pdfplumber text."""
    if not text:
        return None
    m = re.fullmatch(r"\(cid:(\d+)\)", text)
    if m:
        return int(m.group(1))
    if len(text) == 1:
        if text in _TYPE3_TEXT_TO_CODE_OVERRIDES:
            return _TYPE3_TEXT_TO_CODE_OVERRIDES[text]
        code = ord(text)
        # pdfplumber preserves byte-valued glyph codes directly. StandardEncoding
        # is only needed for Unicode stand-ins outside that byte range.
        if 0 <= code <= 255:
            return code
        return _TYPE3_STANDARD_TEXT_TO_CODE.get(text)
    return None


def _type3_font_code_maps_from_doc(
    doc: fitz.Document,
    page_index: int,
) -> list[dict[int, str]]:
    """Build one ``character code -> Unicode`` map per Type3 font on a page."""
    if page_index >= len(doc):
        return []
    font_code_maps: list[dict[int, str]] = []
    for font in doc[page_index].get_fonts(full=True):
        xref, subtype = int(font[0]), str(font[2])
        if subtype != "Type3":
            continue
        font_obj = doc.xref_object(xref, compressed=False)
        code_map: dict[int, str] = {}
        for m in re.finditer(r"/a(\d+)\s+(\d+)\s+0\s+R", font_obj):
            code = int(m.group(1))
            charproc_xref = int(m.group(2))
            stream = doc.xref_stream(charproc_xref) or b""
            decoded = _TYPE3_HASH_TO_TEXT.get(hashlib.sha256(stream).hexdigest())
            if decoded is not None:
                code_map[code] = decoded
        if code_map:
            font_code_maps.append(code_map)
    return font_code_maps


def _build_type3_font_code_maps_by_page(
    pdf_path: Path,
) -> list[list[dict[int, str]]]:
    """Build Type3 font maps for every page in a PDF."""
    doc = fitz.open(pdf_path)
    try:
        return [_type3_font_code_maps_from_doc(doc, i) for i in range(len(doc))]
    finally:
        doc.close()


def _find_buyer_email_word(
    words: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """First ``…@rafael.co.il`` token on page 1 (header geometry); pdfplumber anchor."""
    strict = [
        w for w in words
        if _in_x(w, 0.0, _EMAIL_X_MAX)
        and _EMAIL_Y[0] <= w["top"] <= _EMAIL_Y[1]
        and (w.get("text") or "").lower().endswith("@rafael.co.il")
    ]
    if not strict:
        return None
    centre = (_EMAIL_Y[0] + _EMAIL_Y[1]) / 2.0
    return min(strict, key=lambda w: abs(float(w["top"]) - centre))


def _buyer_crop_rect_from_email(email_w: dict[str, Any]) -> fitz.Rect:
    """PDF-space rectangle for the buyer-name Type3 crop (from e-mail anchor)."""
    x0 = float(email_w["x0"])
    x1 = float(email_w["x1"])
    etop = float(email_w["top"])
    clip_x0 = max(0.0, x0 - _BUYER_CROP_PAD_X0_LEFT)
    clip_x1 = x1 + _BUYER_CROP_X1_PAD_RIGHT
    clip_y0 = etop - _BUYER_CROP_DELTA_TOP
    clip_y1 = etop - _BUYER_CROP_DELTA_BOTTOM
    return fitz.Rect(clip_x0, clip_y0, clip_x1, clip_y1)


def _submission_due_surgical_rect_from_email(email_w: dict[str, Any]) -> fitz.Rect:
    """Return PDF-space rectangle for the cover deadline date glyphs."""
    etop = float(email_w["top"])
    anchor_top = etop + _SUB_DUE_ANCHOR_TOP_OFF_FROM_EMAIL
    anchor_bottom = anchor_top + _SUB_DUE_ANCHOR_LINE_HEIGHT
    crop_y0 = max(0.0, anchor_top - _SUB_DUE_CROP_PAD_Y)
    crop_y1 = anchor_bottom + _SUB_DUE_CROP_PAD_Y
    return fitz.Rect(_SUB_DUE_CROP_X0, crop_y0, _SUB_DUE_CROP_X1, crop_y1)


def _type3_chars_in_rect(
    chars: list[dict[str, Any]],
    rect: fitz.Rect,
) -> list[dict[str, Any]]:
    """Return Type3 pdfplumber chars whose origins are inside ``rect``."""
    return sorted(
        [
            c for c in chars
            if (c.get("size") or 0) == 0
            and rect.x0 <= float(c["x0"]) <= rect.x1
            and rect.y0 <= float(c["top"]) <= rect.y1
        ],
        key=lambda c: float(c["x0"]),
    )


def _decode_type3_chars(
    chars: list[dict[str, Any]],
    code_map: dict[int, str],
    *,
    word_gap_min: float | None = None,
) -> str:
    """Decode sorted Type3 chars via the page's ``code -> Unicode`` map."""
    out: list[str] = []
    prev_x: float | None = None
    for c in chars:
        x = float(c["x0"])
        if word_gap_min is not None and prev_x is not None and x - prev_x >= word_gap_min:
            out.append(" ")
        prev_x = x

        code = _type3_code_from_pdf_text(c.get("text") or "")
        if code is None:
            raise ValueError(
                "Rafael Type3 glyph code is unrepresentable: "
                f"raw={c.get('text')!r}, x={x:.1f}, top={float(c['top']):.1f}",
            )
        decoded = code_map.get(code)
        if decoded is None:
            raise ValueError(
                "Rafael Type3 glyph is unmapped: "
                f"raw={c.get('text')!r}, code={code}, x={x:.1f}, top={float(c['top']):.1f}",
            )
        out.append(decoded)
    return "".join(out).strip()


def _decode_type3_visual_lines_as_logical(
    chars: list[dict[str, Any]],
    code_map: dict[int, str],
) -> str | None:
    """Decode stacked visual RTL Type3 lines into top-to-bottom logical text."""
    lines: list[list[dict[str, Any]]] = []
    for c in sorted(chars, key=lambda item: (float(item["top"]), float(item["x0"]))):
        if not lines or abs(float(lines[-1][0]["top"]) - float(c["top"])) > _TYPE3_LINE_Y_TOL:
            lines.append([c])
        else:
            lines[-1].append(c)

    logical_lines: list[str] = []
    for line in lines:
        decoded_line: list[str] = []
        for c in sorted(line, key=lambda item: float(item["x0"])):
            code = _type3_code_from_pdf_text(c.get("text") or "")
            if code is None:
                return None
            decoded = code_map.get(code)
            if decoded is None:
                return None
            decoded_line.append(decoded)
        if decoded_line:
            logical_lines.append("".join(decoded_line)[::-1])
    return re.sub(r"\s+", " ", " ".join(logical_lines)).strip()


def _fai_cell_key(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _decode_fai_not_required_cell(
    chars: list[dict[str, Any]],
    font_code_maps: list[dict[int, str]],
) -> str | None:
    """Decode the Type3 ``לא נדרש`` FAI cell value, trying each page font map."""
    if not chars:
        return None
    expected = _fai_cell_key(FAI_NOT_REQUIRED)
    for code_map in font_code_maps:
        decoded = _decode_type3_visual_lines_as_logical(chars, code_map)
        if decoded is not None and _fai_cell_key(decoded) == expected:
            return FAI_NOT_REQUIRED
    return None


def _visual_hebrew_to_logical(text: str) -> str:
    """Convert left-to-right visual Hebrew glyph order to logical RTL word order."""
    words = [w for w in text.split() if w]
    return " ".join(w[::-1] for w in reversed(words)).strip()


def _require_unique_type3_candidate(field: str, candidates: set[str]) -> str:
    """Return the only decoded value for a field, rejecting missing or ambiguous text."""
    if len(candidates) == 1:
        return next(iter(candidates))
    if not candidates:
        raise ValueError(f"Rafael {field}: no decodable Type3 candidate.")
    raise ValueError(f"Rafael {field}: ambiguous Type3 candidates {sorted(candidates)!r}.")


def _detect_buyer(
    pages: list[list[dict[str, Any]]],
    page0_chars: list[dict[str, Any]],
    font_code_maps: list[dict[int, str]],
) -> str:
    if not pages:
        raise ValueError("Rafael buyer: PDF has no pages.")
    email_w = _find_buyer_email_word(pages[0])
    if email_w is None:
        raise ValueError("Rafael buyer: no @rafael.co.il anchor found on page 1.")
    rect = _buyer_crop_rect_from_email(email_w)
    chars = _type3_chars_in_rect(page0_chars, rect)
    candidates: set[str] = set()
    for code_map in font_code_maps:
        try:
            visual = _decode_type3_chars(
                chars,
                code_map,
                word_gap_min=_BUYER_WORD_GAP_MIN,
            )
        except ValueError:
            continue
        buyer = _visual_hebrew_to_logical(visual)
        if _hebrew_letter_count(buyer) >= 2:
            candidates.add(buyer)
    return _require_unique_type3_candidate("buyer", candidates)


def _detect_submission_date(
    pages: list[list[dict[str, Any]]],
    page0_chars: list[dict[str, Any]],
    font_code_maps: list[dict[int, str]],
) -> str:
    email_w = _find_buyer_email_word(pages[0]) if pages else None
    if email_w is None:
        raise ValueError("Rafael submission date: no @rafael.co.il anchor found on page 1.")
    rect = _submission_due_surgical_rect_from_email(email_w)
    chars = _type3_chars_in_rect(page0_chars, rect)
    candidates: set[str] = set()
    for code_map in font_code_maps:
        try:
            decoded = _decode_type3_chars(chars, code_map)
        except ValueError:
            continue
        for token in re.findall(r"\d{2}/\d{2}/\d{4}", decoded):
            if _parse_dmy(token):
                candidates.add(token)
    return _require_unique_type3_candidate("submission date", candidates)


# ---------------------------------------------------------------------------
# Globals detection
# ---------------------------------------------------------------------------

def _detect_rfq_number(pages: list[list[dict[str, Any]]]) -> str:
    """Find the standalone 6-digit RFQ number in the page-header band."""
    for words in pages:
        for w in words:
            if not (_in_x(w, *_RFQ_X) and _RFQ_Y[0] <= w["top"] <= _RFQ_Y[1]):
                continue
            if re.fullmatch(r"\d{6}", w["text"]):
                return w["text"]
    raise ValueError("Rafael RFQ number: no standalone 6-digit header value found.")


# ---------------------------------------------------------------------------
# Part-block detection
# ---------------------------------------------------------------------------

def _classify_fai_digit(digit: str | None) -> str | None:
    if digit in {"1", "2", "3"}:
        return f"FAI {digit}"
    return None


def _find_fai_for_row(
    words: list[dict[str, Any]],
    page_chars: list[dict[str, Any]],
    font_code_maps: list[dict[int, str]],
    row_y: float,
) -> str:
    """Parse the actual FAI cell value for a delivery row."""
    marker = None
    for w in words:
        if not _in_x(w, *_FAI_FLAG_X):
            continue
        if w["text"].startswith("FAI") and _y_close(w["top"], row_y):
            marker = w
            break
    if marker is not None:
        digit_word = next(
            (
                w for w in words
                if _in_x(w, *_FAI_DIGIT_X)
                and marker["top"] < w["top"] <= marker["top"] + _FAI_DIGIT_DY_MAX
                and _RE_INT.match(w["text"])
            ),
            None,
        )
        fai = _classify_fai_digit(digit_word["text"] if digit_word else None)
        if fai is None:
            raise ValueError(
                "Rafael FAI: FAI marker has no valid 1/2/3 digit "
                f"near row y={row_y:.1f}."
            )
        return fai

    y0 = row_y + _FAI_NOT_REQUIRED_DY[0]
    y1 = row_y + _FAI_NOT_REQUIRED_DY[1]
    not_required_chars = sorted(
        [
            c for c in page_chars
            if (c.get("size") or 0) == 0
            and _FAI_NOT_REQUIRED_X[0] <= float(c["x0"]) <= _FAI_NOT_REQUIRED_X[1]
            and y0 <= float(c["top"]) <= y1
        ],
        key=lambda c: (float(c["top"]), float(c["x0"])),
    )
    fai = _decode_fai_not_required_cell(not_required_chars, font_code_maps)
    if fai is not None:
        return fai

    raise ValueError(f"Rafael FAI: no parseable FAI cell near row y={row_y:.1f}.")


def _detect_part_blocks(
    pages: list[list[dict[str, Any]]],
    page_chars: list[list[dict[str, Any]]],
    page_type3_font_code_maps: list[list[dict[int, str]]],
) -> list[PartBlock]:
    blocks: list[PartBlock] = []

    for page_index, words in enumerate(pages):
        chars = page_chars[page_index] if page_index < len(page_chars) else []
        font_code_maps = (
            page_type3_font_code_maps[page_index]
            if page_index < len(page_type3_font_code_maps)
            else []
        )
        # A real part header row always has the unit label ``Each`` in the
        # unit column at the same y. This filters out the page footer's
        # ``PRODA - <USER> - XPOTDP01 - <id>`` line whose ``XPOTDP01`` token
        # otherwise lands inside _PARTNUM_X.
        each_ys = [
            w["top"] for w in words
            if _in_x(w, *_EACH_X) and w["text"] == "Each"
        ]
        part_words = [
            w for w in words
            if _in_x(w, *_PARTNUM_X)
            and w["top"] > _HEADER_Y_MAX
            and _RE_PARTNUM.match(w["text"])
            and any(_y_close(w["top"], ey) for ey in each_ys)
        ]
        part_words.sort(key=lambda w: w["top"])
        if not part_words:
            continue

        # Each part header row defines a vertical interval up to the next part.
        part_ys = [w["top"] for w in part_words] + [10_000.0]
        for idx, part_word in enumerate(part_words):
            top = part_word["top"] - _ROW_Y_TOL
            bottom = part_ys[idx + 1] - _ROW_Y_TOL
            qty_rows = sorted(
                [
                    w for w in words
                    if _in_x(w, *_QTY_X)
                    and top <= w["top"] <= bottom
                    and _RE_QTY.match(w["text"])
                ],
                key=lambda w: w["top"],
            )
            if not qty_rows:
                raise ValueError(
                    f"Rafael part {part_word['text']}: no delivery quantity rows."
                )
            block = PartBlock(rafael_pn=part_word["text"], deliveries=[])
            for q in qty_rows:
                quantity = float(q["text"])

                # Day-offset on the same row band
                offset_word = next(
                    (
                        w for w in words
                        if _in_x(w, *_OFFSET_X)
                        and _y_close(w["top"], q["top"])
                        and _RE_INT.match(w["text"])
                    ),
                    None,
                )
                if offset_word is None:
                    raise ValueError(
                        "Rafael ARO: missing integer weeks value "
                        f"for part {part_word['text']} near row y={q['top']:.1f}."
                    )
                weeks_aro = int(offset_word["text"])

                fai = _find_fai_for_row(words, chars, font_code_maps, q["top"])
                block.deliveries.append(
                    Delivery(
                        quantity=quantity,
                        weeks_aro=weeks_aro,
                        fai=fai,
                    )
                )
            blocks.append(block)

    return blocks


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_rafael_rfq(pdf_path: str | Path) -> RafaelRfq:
    """Parse a Rafael RFQ PDF and return globals + per-part delivery list."""
    pdf_path = Path(pdf_path)
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = [_page_clean_words(p) for p in pdf.pages]
        page_chars = [list(p.chars) for p in pdf.pages]
        page0_chars = page_chars[0] if page_chars else []

    rfq_number = _detect_rfq_number(pages)
    page_type3_font_code_maps = _build_type3_font_code_maps_by_page(pdf_path)
    page0_font_code_maps = (
        page_type3_font_code_maps[0] if page_type3_font_code_maps else []
    )
    if not page0_font_code_maps:
        raise ValueError("Rafael Type3 decoder: no mapped Type3 glyphs found on page 1.")

    buyer_name = _detect_buyer(pages, page0_chars, page0_font_code_maps)
    submission_date = _detect_submission_date(pages, page0_chars, page0_font_code_maps)

    parts = _detect_part_blocks(pages, page_chars, page_type3_font_code_maps)
    if not parts:
        raise ValueError("Rafael parts: no part blocks found.")

    return RafaelRfq(
        rfq_number=rfq_number,
        buyer_name=buyer_name,
        submission_date=submission_date,
        parts=parts,
    )


# ---------------------------------------------------------------------------
# Row flattening + TSV writer (V.5.7 spec)
# ---------------------------------------------------------------------------

RAFAEL_TXT_COLUMNS: list[str] = [
    "מספר שורה",
    "מספר בלם",
    "שם קניין",
    "תאריך סופי להגשה",
    "מקט רפאל",
    "כמות נדרשת",
    "זמן אספקה בשבועות",
    "FAI",
]


def flatten_rafael_to_rows(rfq: RafaelRfq) -> list[dict[str, Any]]:
    """Flatten parts × deliveries into the 8-column row schema.

    Row numbers are globally sequential 1..N across the whole RFQ
    (not per-part). ``מספר שורה`` is the first column (sequential index).
    """
    rows: list[dict[str, Any]] = []
    line_no = 0
    for part in rfq.parts:
        for d in part.deliveries:
            line_no += 1
            rows.append({
                "מספר שורה": line_no,
                "מספר בלם": rfq.rfq_number,
                "שם קניין": rfq.buyer_name,
                "תאריך סופי להגשה": rfq.submission_date,
                "מקט רפאל": part.rafael_pn,
                "כמות נדרשת": d.quantity,
                "זמן אספקה בשבועות": d.weeks_aro,
                "FAI": d.fai,
            })
    return rows


def format_rafael_tsv_body(rows: list[dict[str, Any]]) -> str:
    """Build a strict TSV body: tab between fields, CRLF line endings.

    No CSV-style quoting / escaping (matches the Balam TSV contract so
    Excel on a Hebrew Windows / Mac opens the result cleanly under the
    windows-1255 encoding the API uses).
    """
    lines: list[str] = ["\t".join(RAFAEL_TXT_COLUMNS)]
    for r in rows:
        lines.append("\t".join(str(r.get(col, "")) for col in RAFAEL_TXT_COLUMNS))
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# CLI test harness — `python parse_rafael_rfq.py <rfq.pdf> [<rfq.pdf> ...]` (V.5.7)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parse_rafael_rfq.py <rfq.pdf> [<rfq.pdf> ...]")
        sys.exit(1)

    for arg in sys.argv[1:]:
        pdf = Path(arg)
        if not pdf.exists():
            print(f"File not found: {pdf}")
            continue
        rfq = parse_rafael_rfq(pdf)
        rows = flatten_rafael_to_rows(rfq)
        body = format_rafael_tsv_body(rows)
        out_path = pdf.with_name(pdf.stem + ".rafael.txt")
        out_path.write_text(body, encoding="utf-8")
        print(
            f"{pdf.name}: rfq={rfq.rfq_number} buyer={rfq.buyer_name} "
            f"sub={rfq.submission_date} parts={len(rfq.parts)} rows={len(rows)} "
            f"-> {out_path.name}"
        )
