"""engine/scorer.py — combine sub-scores into frontend-compatible result.

SCORE SEMANTICS (fixed — was ambiguous in previous version):
  `score` is now ALWAYS an "authenticity confidence" in [1, 99]:
    - 99  = definitely genuine
    -  1  = definitely forged
  This means the frontend can always read `score` as "how real is this?"
  without having to flip the meaning based on `verdict`.

  Internally we still compute `suspicion_pts` (higher = worse), then
  convert at the very end:   authenticity_score = 100 - suspicion_pts (clamped).

KEY FIXES (cumulative — includes all previous fixes):
  1. total == 0 no longer hard-codes 98. Positive evidence required.
  2. Near-empty OCR text on a typed doc = 20 pt penalty.
  3. Bare PDF metadata (no Producer/CreationDate) = 5 pt penalty.
  4. ocr_result["authenticity_flags"] are scored:
       - Invalid Aadhaar number (Verhoeff fail / bad first digit) = 40 pts
       - UIDAI branding absent                                     = 25 pts
       - Invalid DOB / PIN                                         = 10 pts each
  5. `score` is now always authenticity confidence (higher = more real).
     `verdict` strings remain "verified" / "uncertain" / "forged".
  6. `breakdown` key renamed "ocr_missing" (was "ocr") to match ocr.py output.
"""


# Penalty weights for each authenticity flag keyword
_FLAG_WEIGHTS = [
    # (substring to match in flag text,  penalty_pts, severity)
    ("verhoeff",                 40, "high"),
    ("invalid first digit",      40, "high"),
    ("known fake",               40, "high"),
    ("uidai branding",           25, "high"),
    ("date of birth is invalid", 10, "medium"),
    ("invalid: year",            10, "medium"),
    ("invalid: month",           10, "medium"),
    ("invalid: day",             10, "medium"),
    ("pin code",                 10, "medium"),
]


def _score_authenticity_flags(flags: list) -> tuple:
    """
    Convert authenticity_flags list from ocr.py into penalty points + anomaly dicts.
    Returns (total_penalty: int, anomaly_list: list).
    Caps at 55 pts total.
    """
    pts       = 0
    anomalies = []
    seen      = set()

    for flag in flags:
        flag_lower = flag.lower()
        for keyword, weight, severity in _FLAG_WEIGHTS:
            if keyword in flag_lower and keyword not in seen:
                pts += weight
                seen.add(keyword)
                anomalies.append({"severity": severity, "text": flag})
                break
        else:
            # Unknown flag type — 10 pts, medium severity
            if flag not in seen:
                pts += 10
                seen.add(flag)
                anomalies.append({"severity": "medium", "text": flag})

    return min(pts, 55), anomalies


def _suspicion_to_verdict(suspicion_pts: int, has_positive_evidence: bool) -> tuple:
    """
    Map raw suspicion points → (verdict, authenticity_score).

    authenticity_score is ALWAYS "how real is this?" in [1, 99].
      99 = almost certainly genuine
       1 = almost certainly forged

    Thresholds:
      0  pts + positive evidence  → verified,   ~98
      0  pts, no positive evid.   → uncertain,  ~45
      <10 pts + positive evidence → verified,   90-98
      <10 pts, no positive evid.  → uncertain,  50-55
      10-19 pts                   → uncertain,  70-89
      20-44 pts                   → uncertain,  35-69  (leaning suspicious)
      45+  pts                    → forged,      1-39
    """
    if suspicion_pts == 0 and has_positive_evidence:
        return "verified", 98.0

    if suspicion_pts == 0 and not has_positive_evidence:
        return "uncertain", 45.0

    if suspicion_pts < 10 and has_positive_evidence:
        # Minor blemish but evidence is positive — still verified, slightly lower
        auth = round(98 - suspicion_pts * 1.2, 1)
        return "verified", auth

    if suspicion_pts < 10 and not has_positive_evidence:
        auth = round(55 - suspicion_pts * 0.5, 1)
        return "uncertain", auth

    if suspicion_pts < 20:
        # 10-19 pts: uncertain, authenticity 70-89
        auth = round(90 - (suspicion_pts - 10) * 2.0, 1)
        return "uncertain", auth

    if suspicion_pts < 45:
        # 20-44 pts: uncertain leaning suspicious, authenticity 35-69
        auth = round(70 - (suspicion_pts - 20) * 1.5, 1)
        return "uncertain", auth

    # 45+ pts: forged, authenticity 1-39
    auth = round(max(39 - (suspicion_pts - 45) * 0.65, 1), 1)
    return "forged", auth


def compute_score(ela_result: dict, ocr_result: dict, meta_result: dict,
                  doc_type: str = "generic") -> dict:
    checks    = []
    anomalies = []

    # ─────────────────────────────────────────────────────────────────────────
    # ELA
    # ─────────────────────────────────────────────────────────────────────────
    ela_raw     = ela_result.get("score", 0)
    ela_regions = ela_result.get("high_ela_regions", False)

    if ela_raw >= 22 or (ela_regions and ela_raw >= 15):
        checks.append({
            "name":   "Image Edit Check",
            "status": "fail",
            "detail": f"High pixel-level variance (ELA {ela_raw:.2f}) — strong signs of editing",
        })
        anomalies.append({
            "severity": "high",
            "text": (
                f"ELA score {ela_raw:.2f}: Significant pixel manipulation detected. "
                "Multiple image regions show compression inconsistency."
            ),
        })
        ela_pts = 45

    elif ela_raw >= 12 or (ela_regions and ela_raw >= 8):
        checks.append({
            "name":   "Image Edit Check",
            "status": "warn",
            "detail": f"Moderate pixel variance (ELA {ela_raw:.2f}) — possible editing or heavy re-compression",
        })
        anomalies.append({
            "severity": "medium",
            "text": (
                f"ELA score {ela_raw:.2f}: Some areas show elevated compression residue. "
                "May result from photo editing, multiple saves, or scanner processing."
            ),
        })
        ela_pts = 18

    elif ela_raw >= 5:
        checks.append({
            "name":   "Image Edit Check",
            "status": "warn",
            "detail": f"Minor pixel variance (ELA {ela_raw:.2f}) — consistent with scan noise",
        })
        anomalies.append({
            "severity": "low",
            "text": (
                f"ELA score {ela_raw:.2f}: Low-level variance consistent with "
                "normal scanning artefacts or JPEG re-compression."
            ),
        })
        ela_pts = 6

    else:
        checks.append({
            "name":   "Image Edit Check",
            "status": "pass",
            "detail": f"No pixel manipulation detected (ELA {ela_raw:.2f})",
        })
        ela_pts = 0

    # ─────────────────────────────────────────────────────────────────────────
    # OCR — missing fields
    # ─────────────────────────────────────────────────────────────────────────
    missing            = ocr_result.get("missing_fields", [])
    authenticity_flags = ocr_result.get("authenticity_flags", [])
    ocr_ok             = ocr_result.get("ocr_available", False)
    doc_text           = ocr_result.get("full_text", "")
    has_text           = len(doc_text.strip()) > 50
    ocr_confirmed      = False
    auth_pts           = 0

    if not ocr_ok:
        checks.append({
            "name":   "Text Field Check",
            "status": "warn",
            "detail": "Tesseract OCR not available — install it for full field validation",
        })
        ocr_pts = 0

    elif missing:
        checks.append({
            "name":   "Text Field Check",
            "status": "fail",
            "detail": f"Missing expected fields: {', '.join(missing)}",
        })
        for f in missing:
            anomalies.append({
                "severity": "medium",
                "text": (
                    f"Expected document field not found: '{f}'. "
                    "Authentic documents of this type should contain this field."
                ),
            })
        ocr_pts = min(len(missing) * 8, 30)

    elif not has_text and doc_type not in ("generic",):
        checks.append({
            "name":   "Text Field Check",
            "status": "fail",
            "detail": (
                "Very little text extracted. Genuine printed documents contain "
                "substantial readable text. This may indicate a blank template or image-only forgery."
            ),
        })
        anomalies.append({
            "severity": "high",
            "text": (
                "OCR extracted fewer than 50 characters. Authentic government documents "
                "contain substantial printed text. The near-absence of text strongly "
                "suggests this is not a genuine document."
            ),
        })
        ocr_pts = 20

    else:
        checks.append({
            "name":   "Text Field Check",
            "status": "pass",
            "detail": "All expected text fields found and verified",
        })
        ocr_pts       = 0
        ocr_confirmed = True

    # ─────────────────────────────────────────────────────────────────────────
    # OCR — authenticity flags (Verhoeff, UIDAI brand, DOB, PIN)
    # ─────────────────────────────────────────────────────────────────────────
    if authenticity_flags:
        auth_pts, auth_anomalies = _score_authenticity_flags(authenticity_flags)
        anomalies.extend(auth_anomalies)

        has_high   = any(a["severity"] == "high"   for a in auth_anomalies)
        has_medium = any(a["severity"] == "medium"  for a in auth_anomalies)
        status     = "fail" if has_high else ("warn" if has_medium else "warn")

        checks.append({
            "name":   "Authenticity Validation",
            "status": status,
            "detail": (
                f"{len(authenticity_flags)} deep-validation issue(s) found: "
                + "; ".join(authenticity_flags[:2])
                + ("..." if len(authenticity_flags) > 2 else "")
            ),
        })

        # Revoke ocr_confirmed if high-severity flags fired
        if has_high:
            ocr_confirmed = False

    # ─────────────────────────────────────────────────────────────────────────
    # Metadata
    # ─────────────────────────────────────────────────────────────────────────
    meta_anom = meta_result.get("anomalies", [])
    raw_meta  = meta_result.get("metadata", {})

    real_anom = [
        a for a in meta_anom
        if "No EXIF metadata found" not in a or ela_pts > 20
    ]

    bare_pdf_penalty = 0
    if (
        not real_anom
        and not raw_meta.get("Producer")
        and not raw_meta.get("CreationDate")
        and any("pdf" in a.lower() or "metadata" in a.lower() for a in meta_anom)
    ):
        bare_pdf_penalty = 5
        anomalies.append({
            "severity": "low",
            "text": (
                "PDF contains no Producer or CreationDate metadata. "
                "Genuine government-issued PDFs always carry these fields."
            ),
        })

    meta_confirmed = False
    if real_anom:
        checks.append({
            "name":   "Metadata Check",
            "status": "fail",
            "detail": f"{len(real_anom)} metadata anomaly(s) detected",
        })
        for a in real_anom:
            sev = (
                "high"   if any(w in a.lower() for w in ["photoshop", "gimp", "affinity", "paint.net"])
                else "medium" if any(w in a.lower() for w in ["modification", "timestamp", "gps"])
                else "low"
            )
            anomalies.append({"severity": sev, "text": a})
        meta_pts = min(len(real_anom) * 12, 25) + bare_pdf_penalty

    elif meta_anom and not real_anom:
        checks.append({
            "name":   "Metadata Check",
            "status": "warn",
            "detail": "No EXIF data present — normal for PDF/scanned documents",
        })
        meta_pts = bare_pdf_penalty
        if raw_meta.get("Producer") or raw_meta.get("CreationDate"):
            meta_confirmed = True

    else:
        checks.append({
            "name":   "Metadata Check",
            "status": "pass",
            "detail": "No suspicious metadata found",
        })
        meta_pts = bare_pdf_penalty
        if raw_meta.get("Producer") or raw_meta.get("CreationDate"):
            meta_confirmed = True

    # ─────────────────────────────────────────────────────────────────────────
    # Final scoring — unified semantics
    # ─────────────────────────────────────────────────────────────────────────
    has_positive_evidence = ocr_confirmed or meta_confirmed
    suspicion_pts         = ela_pts + ocr_pts + auth_pts + meta_pts

    # Handle the "no evidence at all" edge case with an explanatory check entry
    if suspicion_pts == 0 and not has_positive_evidence:
        anomalies.append({
            "severity": "medium",
            "text": (
                "No forensic penalties were triggered, but no positive confirming evidence "
                "was found either. Manual verification is recommended."
            ),
        })
        checks.append({
            "name":   "Positive Evidence Check",
            "status": "fail",
            "detail": (
                "No confirming evidence found: OCR text is absent and metadata is bare. "
                "A genuine document should contain extractable text and valid file metadata."
            ),
        })

    verdict, authenticity_score = _suspicion_to_verdict(suspicion_pts, has_positive_evidence)
    authenticity_score          = max(1.0, min(99.0, authenticity_score))

    return {
        # ── Primary result fields ──────────────────────────────────────────
        "verdict": verdict,          # "verified" | "uncertain" | "forged"

        # `score` is ALWAYS authenticity confidence: higher = more genuine.
        #   99 → almost certainly real
        #    1 → almost certainly forged
        # The frontend should display it as "Authenticity: XX%" regardless of verdict.
        "score":   authenticity_score,

        # ── Supporting detail ──────────────────────────────────────────────
        "checks":    checks,
        "anomalies": anomalies,
        "breakdown": {
            "ela":          round(ela_pts,  1),
            "ocr_missing":  round(ocr_pts,  1),   # renamed from "ocr" to match ocr.py key
            "ocr_auth":     round(auth_pts, 1),
            "metadata":     round(meta_pts, 1),
            # Convenience: total suspicion points (for debugging / logging)
            "suspicion_pts": round(suspicion_pts, 1),
        },
        "has_positive_evidence": has_positive_evidence,
    }