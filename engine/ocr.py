"""engine/ocr.py — OCR-based field validation using Tesseract.

Self-contained: handles PDF, JPG, PNG, TIFF etc. with no external
image_loader module needed.

KEY FIXES vs previous version:
  1. Aadhaar number Verhoeff checksum — UIDAI mandates this. GPT-generated
     numbers almost always fail it.
  2. Aadhaar first-digit rule — genuine numbers never start with 0 or 1.
  3. Known fake number blacklist — common sample/test patterns flagged.
  4. UIDAI branding check — genuine cards always contain
     "Unique Identification Authority of India" or "uidai.gov.in".
     AI-generated fakes frequently omit or misspell this.
  5. DOB validity — impossible dates (e.g. 30/02/2001) flagged.
  6. PIN code validity — genuine addresses have a 6-digit PIN starting 2-9.
  7. run_ocr_check now returns "authenticity_flags" list (in addition to
     "missing_fields") so scorer.py can apply extra penalties per flag.
"""

import re
from pathlib import Path
from PIL import Image

import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_AVAILABLE = True

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False


# ── Required fields per doc type ──────────────────────────────────────────────
REQUIRED_FIELDS = {
    "aadhaar":   ["aadhaar", "dob", "male|female", r"\d{4}\s\d{4}\s\d{4}"],
    "pan":       ["permanent account number", "income tax", r"[A-Z]{5}\d{4}[A-Z]"],
    "passport":  ["passport", "republic of india", "nationality"],
    "marksheet": ["register", "marks", "total", "result"],
    "generic":   [],
}

# ── Aadhaar regex patterns ────────────────────────────────────────────────────
_RE_AADHAAR_NUM = re.compile(r"\b(\d{4})[\s\-]?(\d{4})[\s\-]?(\d{4})\b")
_RE_DOB         = re.compile(
    r"\b(\d{2})[\/\-](\d{2})[\/\-](\d{4})\b|(Year\s+of\s+Birth\s*[:\-]?\s*(\d{4}))",
    re.IGNORECASE,
)
_RE_GENDER  = re.compile(
    r"\b(MALE|FEMALE|TRANSGENDER|पुरुष|महिला|ஆண்|பெண்)\b", re.IGNORECASE
)
_RE_ADDRESS = re.compile(
    r"\b(S/O|D/O|W/O|C/O|House|Flat|Plot|Village|Vill\.|Post|"
    r"District|Dist\.|State|Pin|Pincode|Road|Street|Nagar|Address|"
    r"மாவட்டம்|முகவரி|ग्राम|जिला|पिन)\b",
    re.IGNORECASE,
)
_RE_NAME    = re.compile(r"\b([A-Z][a-z]+ ){1,}[A-Z][a-z]+\b")
_RE_PIN     = re.compile(r"\b([2-9]\d{5})\b")

# UIDAI official branding — must appear on every genuine Aadhaar card
_RE_UIDAI_BRAND = re.compile(
    r"(Unique\s+Identification\s+Authority|UIDAI|uidai\.gov\.in|"
    r"भारतीय\s+विशिष्ट\s+पहचान\s+प्राधिकरण|"
    r"இந்திய\s+தனித்துவ\s+அடையாள\s+ஆணையம்)",
    re.IGNORECASE,
)

# Common fake / sample Aadhaar number patterns to blacklist immediately
_FAKE_AADHAAR_PATTERNS = [
    r"^1234[\s\-]?5678[\s\-]?9012$",
    r"^9999[\s\-]?9999[\s\-]?9999$",
    r"^0000[\s\-]?0000[\s\-]?0000$",
    r"^1111[\s\-]?1111[\s\-]?1111$",
    r"^1234[\s\-]?1234[\s\-]?1234$",
    r"^(\d)\1\1\1[\s\-]?\1\1\1\1[\s\-]?\1\1\1\1$",   # all same digit
]

# ── Verhoeff algorithm tables (UIDAI checksum standard) ───────────────────────
_VERHOEFF_D = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,2,3,4,0,6,7,8,9,5],
    [2,3,4,0,1,7,8,9,5,6],
    [3,4,0,1,2,8,9,5,6,7],
    [4,0,1,2,3,9,5,6,7,8],
    [5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2],
    [7,6,5,9,8,2,1,0,4,3],
    [8,7,6,5,9,3,2,1,0,4],
    [9,8,7,6,5,4,3,2,1,0],
]
_VERHOEFF_P = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,5,7,6,2,8,3,0,9,4],
    [5,8,0,3,7,9,6,1,4,2],
    [8,9,1,6,0,4,3,5,2,7],
    [9,4,5,3,1,2,6,8,7,0],
    [4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5],
    [7,0,4,6,9,1,3,2,5,8],
]


def _verhoeff_validate(number: str) -> bool:
    """Return True if the 12-digit string passes the Verhoeff checksum."""
    digits = [int(d) for d in reversed(number)]
    c = 0
    for i, d in enumerate(digits):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][d]]
    return c == 0


def _validate_aadhaar_number(raw: str) -> tuple:
    """
    Validate a raw Aadhaar number string (with possible spaces/dashes).
    Returns (is_valid: bool, reason: str).
    """
    digits = re.sub(r"[\s\-]", "", raw)

    if len(digits) != 12:
        return False, "Not exactly 12 digits"

    # First digit cannot be 0 or 1
    if digits[0] in ("0", "1"):
        return False, f"Invalid first digit '{digits[0]}' — genuine Aadhaar numbers start with 2-9"

    # Blacklist check
    for pattern in _FAKE_AADHAAR_PATTERNS:
        if re.match(pattern, raw.strip()):
            return False, "Matches known fake/sample number pattern"

    # Verhoeff checksum (UIDAI standard)
    if not _verhoeff_validate(digits):
        return False, "Fails Verhoeff checksum (all genuine UIDAI numbers pass this)"

    return True, ""


def _validate_dob(match) -> tuple:
    """Validate a DOB regex match object. Returns (is_valid: bool, reason: str)."""
    # "Year of Birth: YYYY" form
    if match.group(5):
        year = int(match.group(5))
        if not (1900 <= year <= 2025):
            return False, f"Year of birth {year} is outside the plausible range 1900-2025"
        return True, ""

    day   = int(match.group(1))
    month = int(match.group(2))
    year  = int(match.group(3))

    if not (1900 <= year <= 2025):
        return False, f"Year {year} is outside the plausible range 1900-2025"
    if not (1 <= month <= 12):
        return False, f"Month {month} is not a valid month"

    # Days-in-month (allows 29 for Feb — ignores leap year edge case)
    days_in_month = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not (1 <= day <= days_in_month[month]):
        return False, f"Day {day} is impossible for month {month}"

    return True, ""


def _ocr_image(img: Image.Image) -> str:
    try:
        return pytesseract.image_to_string(img, lang="eng")
    except Exception:
        try:
            return pytesseract.image_to_string(img)
        except Exception:
            return ""


def _load_all_pages(source) -> list:
    """Return a list of PIL Images covering every page/frame of the source."""
    if isinstance(source, Image.Image):
        return [source.convert("RGB")]

    path   = Path(source)
    suffix = path.suffix.lower()

    # PDF — convert all pages
    if suffix == ".pdf":
        if not PDF2IMAGE_AVAILABLE:
            return []
        try:
            return [p.convert("RGB") for p in convert_from_path(
                str(path), dpi=200, poppler_path=r"C:\poppler\Library\bin"
            )]
        except Exception:
            return []

    # Multi-frame TIFF
    if suffix in (".tif", ".tiff"):
        try:
            img    = Image.open(str(path))
            frames = []
            frame  = 0
            while True:
                try:
                    img.seek(frame)
                    frames.append(img.copy().convert("RGB"))
                    frame += 1
                except EOFError:
                    break
            return frames or [img.convert("RGB")]
        except Exception:
            return []

    # Regular image (JPG, PNG, BMP, WEBP …)
    try:
        return [Image.open(str(path)).convert("RGB")]
    except Exception:
        return []


def _detect_aadhaar_side(text: str) -> str:
    has_dob    = bool(_RE_DOB.search(text))
    has_gender = bool(_RE_GENDER.search(text))
    has_addr   = bool(_RE_ADDRESS.search(text))
    if (has_dob or has_gender) and not has_addr:
        return "front"
    if has_addr and not has_dob and not has_gender:
        return "back"
    if has_addr and (has_dob or has_gender):
        return "both"
    return "unknown"


def _validate_aadhaar(text: str) -> tuple:
    """
    Deep Aadhaar validation.
    Returns (missing_fields: list, authenticity_flags: list).

    missing_fields      — expected fields that are completely absent.
    authenticity_flags  — fields present but failing deeper validation checks.
    """
    side               = _detect_aadhaar_side(text)
    missing            = []
    authenticity_flags = []

    # ── Aadhaar number ────────────────────────────────────────────────────────
    num_match = _RE_AADHAAR_NUM.search(text)
    if not num_match:
        missing.append("Aadhaar Number (12 digits)")
    else:
        raw_num = num_match.group(0)
        valid, reason = _validate_aadhaar_number(raw_num)
        if not valid:
            authenticity_flags.append(
                f"Aadhaar number '{raw_num}' is invalid: {reason}"
            )

    # ── UIDAI branding ────────────────────────────────────────────────────────
    if not _RE_UIDAI_BRAND.search(text):
        authenticity_flags.append(
            "UIDAI branding absent: genuine Aadhaar cards always print "
            "'Unique Identification Authority of India' or 'uidai.gov.in'. "
            "AI-generated and forged cards frequently omit or misspell this."
        )

    # ── Front-side fields ─────────────────────────────────────────────────────
    if side in ("front", "unknown", "both"):
        dob_match = _RE_DOB.search(text)
        if not dob_match:
            missing.append("Date of Birth / Year of Birth")
        else:
            valid, reason = _validate_dob(dob_match)
            if not valid:
                authenticity_flags.append(f"Date of Birth is invalid: {reason}")

        if not _RE_GENDER.search(text):
            missing.append("Gender")

        if not _RE_NAME.search(text):
            missing.append("Holder Name")

    # ── Back-side fields ──────────────────────────────────────────────────────
    if side in ("back", "both"):
        if not _RE_ADDRESS.search(text):
            missing.append("Address")
        else:
            pin_match = _RE_PIN.search(text)
            if not pin_match:
                authenticity_flags.append(
                    "No valid 6-digit PIN code found in address. "
                    "Genuine Aadhaar addresses always include a valid Indian PIN."
                )

    return missing, authenticity_flags


def run_ocr_check(source, doc_type: str) -> dict:
    """
    Run OCR field validation on a document.

    Parameters
    ----------
    source   : str | Path | PIL.Image
               File path (PDF/JPG/PNG/TIFF/...) or PIL Image.
               ALL pages of multi-page files are read automatically.
    doc_type : str   e.g. "aadhaar", "pan", "passport"

    Returns
    -------
    dict with keys:
        full_text          : str
        missing_fields     : list[str]   — fields absent from the document
        authenticity_flags : list[str]   — fields present but failing deep checks
        ocr_available      : bool
        pages_read         : int
    """
    if not TESSERACT_AVAILABLE:
        return {
            "full_text": "", "missing_fields": [], "authenticity_flags": [],
            "ocr_available": False, "pages_read": 0,
        }

    pages = _load_all_pages(source)
    if not pages:
        return {
            "full_text": "", "missing_fields": [], "authenticity_flags": [],
            "ocr_available": False, "pages_read": 0,
        }

    # OCR every page and concatenate
    page_texts = [f"--- PAGE {i} ---\n{_ocr_image(p)}" for i, p in enumerate(pages, 1)]
    full_text  = "\n\n".join(page_texts)

    if doc_type == "aadhaar":
        missing, authenticity_flags = _validate_aadhaar(full_text)
    else:
        text_lower         = full_text.lower()
        required           = REQUIRED_FIELDS.get(doc_type, [])
        missing            = [f for f in required if not re.search(f.lower(), text_lower)]
        authenticity_flags = []

    return {
        "full_text":          full_text,
        "missing_fields":     missing,
        "authenticity_flags": authenticity_flags,
        "ocr_available":      True,
        "pages_read":         len(pages),
    }