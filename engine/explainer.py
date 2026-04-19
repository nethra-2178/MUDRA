"""engine/explainer.py — detailed, specific Explainable AI explanations.

FIX: breakdown key was "ocr" but scorer.py emits "ocr_missing".
     Also updated all score descriptions to match the unified
     authenticity-confidence semantics (higher score = more genuine).
"""

import os
import json

try:
    import google.generativeai as genai
    _GENAI_OK = True
except ImportError:
    _GENAI_OK = False

_API_KEY = os.getenv("GEMINI_API_KEY", "")


def _build_detailed_fallback(score_result: dict, doc_type: str) -> dict:
    """Rich, specific fallback explanation — used when Gemini API is unavailable."""
    verdict   = score_result.get("verdict", "UNKNOWN").upper()
    score     = score_result.get("score", 0)           # always authenticity %
    breakdown = score_result.get("breakdown", {})
    anomalies = score_result.get("anomalies", [])
    checks    = score_result.get("checks", [])

    ela_pts       = breakdown.get("ela", 0)
    ocr_pts       = breakdown.get("ocr_missing", 0)    # FIX: was "ocr"
    ocr_auth_pts  = breakdown.get("ocr_auth", 0)
    meta_pts      = breakdown.get("metadata", 0)
    suspicion_pts = breakdown.get("suspicion_pts", ela_pts + ocr_pts + ocr_auth_pts + meta_pts)
    doc_label     = doc_type.upper() if doc_type != "generic" else "document"

    # ── Summary sentence ──────────────────────────────────────────────────────
    # score is now always "authenticity confidence" (higher = more genuine)
    if verdict == "VERIFIED":
        summary = (
            f"This {doc_label} appears authentic — authenticity confidence {score:.0f}%."
        )
    elif verdict == "UNCERTAIN":
        summary = (
            f"This {doc_label} shows mixed signals — authenticity confidence {score:.0f}%. "
            "Further manual verification is recommended."
        )
    else:
        summary = (
            f"This {doc_label} is likely FORGED — authenticity confidence only {score:.0f}% "
            "(multiple forensic indicators point to manipulation)."
        )

    # ── English explanation ───────────────────────────────────────────────────
    en_parts = []

    if verdict == "VERIFIED":
        en_parts.append(
            f"MUDRA analysed this {doc_label} using three independent forensic methods — "
            "pixel-level Error Level Analysis (ELA), OCR text field validation, and file metadata "
            f"inspection. All checks passed cleanly. Authenticity confidence: {score:.0f}%."
        )
    else:
        en_parts.append(
            f"MUDRA analysed this {doc_label} using three forensic methods: ELA pixel analysis, "
            f"OCR text field validation, and metadata inspection. "
            f"Total suspicion points accumulated: {suspicion_pts:.0f} "
            f"(ELA: {ela_pts}, OCR missing fields: {ocr_pts}, "
            f"OCR deep-validation: {ocr_auth_pts}, Metadata: {meta_pts}). "
            f"Authenticity confidence: {score:.0f}%."
        )

    # ELA detail
    ela_check = next((c for c in checks if "Image Edit" in c.get("name", "")), None)
    if ela_check:
        if ela_check["status"] == "pass":
            en_parts.append(
                "ELA Check (PASSED): The pixel compression pattern across the entire image is "
                "uniform, indicating the document has not been digitally edited after its original "
                "creation. Clean ELA means no region was replaced or inserted."
            )
        elif ela_check["status"] == "warn":
            en_parts.append(
                f"ELA Check (WARNING): {ela_check['detail']}. ELA works by re-saving the image "
                "at a lower JPEG quality and measuring where pixels differ from the original. "
                "Edited regions retain a different compression history, showing as bright spots on "
                "the heatmap. The variance here is mild and may come from scanning or repeated JPEG saves."
            )
        else:
            en_parts.append(
                f"ELA Check (FAILED): {ela_check['detail']}. The ELA heatmap shows bright hotspots "
                "in specific regions — these areas carry a different compression signature from the "
                "rest of the document. This is a strong forensic indicator that text, numbers, stamps, "
                "or images were inserted or altered after the document was originally created."
            )

    # OCR — missing fields
    ocr_check = next((c for c in checks if "Text Field" in c.get("name", "")), None)
    if ocr_check:
        if ocr_check["status"] == "pass":
            en_parts.append(
                f"OCR Field Check (PASSED): All expected text patterns for a {doc_label} were found "
                "and verified. The extracted text content matches the structural and field requirements "
                "of this document type."
            )
        elif ocr_check["status"] == "fail":
            en_parts.append(
                f"OCR Field Check (FAILED): {ocr_check['detail']}. MUDRA uses Tesseract OCR to "
                "extract all visible text and checks for mandatory fields that must appear in genuine "
                "documents of this type. Missing fields can indicate the document was fabricated from "
                "an incomplete template, or that critical information was removed or obscured."
            )
        else:
            en_parts.append(f"OCR Field Check (WARNING): {ocr_check['detail']}.")

    # OCR — deep authenticity flags
    auth_check = next((c for c in checks if "Authenticity Validation" in c.get("name", "")), None)
    if auth_check:
        status_word = auth_check["status"].upper()
        en_parts.append(
            f"Deep Authenticity Check ({status_word}): {auth_check['detail']}. "
            "These checks verify the mathematical validity of document numbers (e.g. Aadhaar "
            "Verhoeff checksum), presence of official branding (UIDAI), and date/PIN plausibility."
        )

    # Metadata detail
    meta_check = next((c for c in checks if "Metadata" in c.get("name", "")), None)
    if meta_check:
        if meta_check["status"] == "pass":
            en_parts.append(
                "Metadata Check (PASSED): File metadata shows no signs of editing software "
                "such as Adobe Photoshop or GIMP, and all embedded timestamps are internally "
                "consistent with original document generation."
            )
        elif meta_check["status"] == "fail":
            en_parts.append(
                f"Metadata Check (FAILED): {meta_check['detail']}. EXIF and file metadata embed "
                "the full processing history of a file. The presence of image editing software tags "
                "or mismatched creation-versus-modification timestamps are strong indicators the file "
                "was processed after its original generation — a hallmark of document fraud."
            )
        elif meta_check["status"] == "warn":
            en_parts.append(f"Metadata Check (WARNING): {meta_check['detail']}.")

    # Critical anomaly callout
    high_anom = [a["text"] for a in anomalies if a.get("severity") == "high"]
    if high_anom:
        en_parts.append("Critical finding(s): " + " | ".join(high_anom))

    # Severity summary
    n_high   = sum(1 for a in anomalies if a.get("severity") == "high")
    n_medium = sum(1 for a in anomalies if a.get("severity") == "medium")
    n_low    = sum(1 for a in anomalies if a.get("severity") == "low")
    if anomalies:
        en_parts.append(
            f"Anomaly severity breakdown: {n_high} high (definitive manipulation evidence), "
            f"{n_medium} medium (suspicious but not conclusive), {n_low} low (minor artefacts). "
            "High-severity anomalies alone are sufficient grounds to reject a document."
        )

    # Recommendation
    if verdict == "VERIFIED":
        en_parts.append(
            "Recommendation: This document can be provisionally accepted as authentic. "
            "For high-stakes legal or financial decisions, always cross-verify with the "
            "original issuing authority."
        )
    elif verdict == "UNCERTAIN":
        en_parts.append(
            "Recommendation: Do not rely solely on this automated analysis. Request the "
            "original physical document and contact the issuing authority to confirm authenticity "
            "before proceeding with any official action."
        )
    else:
        en_parts.append(
            "Recommendation: Treat this document as highly SUSPICIOUS. Do not accept it "
            "for any official purpose. If fraud is suspected, escalate to the relevant "
            "investigative or legal authority immediately."
        )

    english = "\n\n".join(en_parts)

    # ── Tamil explanation ──────────────────────────────────────────────────────
    if verdict == "VERIFIED":
        tamil = (
            f"MUDRA ஆய்வு முடிவு: இந்த {doc_label} ஆவணம் நம்பகமானதாக தெரிகிறது "
            f"(நம்பகத்தன்மை: {score:.0f}%).\n\n"
            "மூன்று முக்கிய பரிசோதனைகள் மேற்கொள்ளப்பட்டன:\n"
            "1. ELA பிக்சல் பகுப்பாய்வு — படத்தில் எந்த திருத்தமும் இல்லை என்று உறுதிப்படுத்தப்பட்டது.\n"
            "2. OCR உரை சரிபார்ப்பு — தேவையான அனைத்து தகவல் புலங்களும் உள்ளன.\n"
            "3. மெட்டாடேட்டா ஆய்வு — எந்த சந்தேக சூழ்நிலையும் காணவில்லை.\n\n"
            "பரிந்துரை: இந்த ஆவணம் தற்காலிகமாக ஏற்றுக்கொள்ளலாம். "
            "முக்கியமான சட்ட அல்லது நிதி முடிவுகளுக்கு வழங்கும் அதிகாரியிடம் சரிபார்க்கவும்."
        )
    elif verdict == "UNCERTAIN":
        ta_issues = []
        if ela_pts > 0:
            ta_issues.append(f"ELA பகுப்பாய்வில் சந்தேகம் ({ela_pts} புள்ளிகள்)")
        if ocr_pts > 0:
            ta_issues.append(f"உரை புலங்கள் காணவில்லை ({ocr_pts} புள்ளிகள்)")
        if ocr_auth_pts > 0:
            ta_issues.append(f"ஆழ்ந்த சரிபார்ப்பு தோல்வி ({ocr_auth_pts} புள்ளிகள்)")
        if meta_pts > 0:
            ta_issues.append(f"மெட்டாடேட்டா முரண்பாடு ({meta_pts} புள்ளிகள்)")
        tamil = (
            f"MUDRA ஆய்வு முடிவு: இந்த {doc_label} ஆவணம் சந்தேகத்திற்குரியது "
            f"(நம்பகத்தன்மை: {score:.0f}%).\n\n"
            f"கண்டறிந்த பிரச்சனைகள்: {'; '.join(ta_issues) if ta_issues else 'சிறிய முரண்பாடுகள்'}.\n\n"
            f"மொத்த சந்தேக புள்ளிகள்: {suspicion_pts:.0f} — "
            f"ELA: {ela_pts}, OCR புலங்கள்: {ocr_pts}, ஆழ்ந்த சரிபார்ப்பு: {ocr_auth_pts}, "
            f"மெட்டாடேட்டா: {meta_pts}.\n\n"
            "பரிந்துரை: இந்த ஆவணத்தை உடனடியாக ஏற்க வேண்டாம். "
            "அசல் ஆவணம் அல்லது வழங்கும் அதிகாரியிடம் நேரடியாக சரிபார்க்கவும்."
        )
    else:
        tamil = (
            f"MUDRA ஆய்வு முடிவு: இந்த {doc_label} ஆவணம் போலியாக இருக்கலாம் "
            f"(நம்பகத்தன்மை வெறும் {score:.0f}%).\n\n"
            f"மொத்த சந்தேக புள்ளிகள்: {suspicion_pts:.0f}.\n\n"
            "முக்கியமான கண்டுபிடிப்புகள்:\n"
        )
        if ela_pts >= 22:
            tamil += (
                "• ELA பரிசோதனை (தோல்வி): படத்தில் குறிப்பிட்ட பகுதிகளில் pixel அளவிலான "
                "திருத்தம் கண்டறியப்பட்டது. ஆவணம் உருவாக்கப்பட்ட பிறகு உரை அல்லது படங்கள் "
                "சேர்க்கப்பட்டதற்கான வலுவான சான்று.\n"
            )
        elif ela_pts > 0:
            tamil += f"• ELA பரிசோதனை (எச்சரிக்கை): மிதமான pixel முரண்பாடு ({ela_pts} புள்ளிகள்).\n"
        if ocr_pts > 0:
            tamil += (
                "• உரை பரிசோதனை (தோல்வி): தேவையான புலங்கள் காணவில்லை. "
                "போலி ஆவணங்கள் பெரும்பாலும் முழுமையற்ற தகவல்களுடன் தயாரிக்கப்படுகின்றன.\n"
            )
        if ocr_auth_pts > 0:
            tamil += (
                f"• ஆழ்ந்த சரிபார்ப்பு (தோல்வி): Verhoeff கணக்கீடு, UIDAI முத்திரை, "
                f"DOB/PIN செல்லுபடியாகும் தன்மை — {ocr_auth_pts} புள்ளிகள் இழப்பு.\n"
            )
        if meta_pts > 0:
            tamil += (
                "• மெட்டாடேட்டா பரிசோதனை (தோல்வி): திருத்தல் மென்பொருளின் அறிகுறிகள் "
                "அல்லது முரண்பட்ட நேர முத்திரைகள்.\n"
            )
        if n_high > 0:
            tamil += f"\nமிக முக்கியமான எச்சரிக்கை: {n_high} உயர்-தீவிர அசாதாரணம் கண்டறியப்பட்டது.\n"
        tamil += (
            "\nபரிந்துரை: இந்த ஆவணத்தை எந்த அதிகாரப்பூர்வ நோக்கத்திற்கும் ஏற்க வேண்டாம். "
            "மோசடி சந்தேகப்பட்டால் உடனடியாக சம்பந்தப்பட்ட அதிகாரத்திடம் தெரிவிக்கவும்."
        )

    return {"summary": summary, "english": english, "tamil": tamil}


def explain(score_result: dict, doc_type: str) -> dict:
    """Return summary, english, and tamil explanations — detailed and specific."""

    verdict   = score_result.get("verdict", "UNKNOWN")
    score     = score_result.get("score", 0)            # now always authenticity %
    anomalies = score_result.get("anomalies", [])
    breakdown = score_result.get("breakdown", {})

    anom_lines = "\n".join(
        f"  [{a.get('severity','?').upper()}] {a.get('text','')}"
        for a in anomalies
    ) or "  None detected"

    fallback = _build_detailed_fallback(score_result, doc_type)

    if not _GENAI_OK or not _API_KEY:
        return fallback

    try:
        genai.configure(api_key=_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")

        ela_pts      = breakdown.get("ela", 0)
        ocr_pts      = breakdown.get("ocr_missing", 0)   # FIX: was "ocr"
        ocr_auth_pts = breakdown.get("ocr_auth", 0)
        meta_pts     = breakdown.get("metadata", 0)
        susp_pts     = breakdown.get("suspicion_pts", ela_pts + ocr_pts + ocr_auth_pts + meta_pts)

        prompt = f"""You are MUDRA, an expert AI document-forgery detection assistant used by \
Indian government officers, bank staff, and non-technical citizens.

=== SCORE SEMANTICS ===
`score` is ALWAYS an authenticity confidence percentage (higher = more genuine).
  99 = almost certainly real
   1 = almost certainly forged
Do NOT describe it as a "suspicion score".

=== ANALYSIS DATA ===
Document type       : {doc_type}
Verdict             : {verdict}
Authenticity score  : {score:.1f}% (higher = more genuine)
Suspicion pts total : {susp_pts}
Score breakdown     : ELA={ela_pts}, OCR missing fields={ocr_pts}, OCR deep-auth={ocr_auth_pts}, Metadata={meta_pts}
Anomalies detected  :
{anom_lines}

=== YOUR TASK ===
Return ONLY a valid JSON object with exactly three keys:

"summary": One sentence (max 25 words) — state the verdict and authenticity score clearly.

"english": 6-8 detailed sentences covering:
  1. Overall verdict and authenticity score meaning for this document type ({doc_type}).
  2. ELA findings — reference exact score, explain heatmap hotspots forensically.
  3. OCR text field check — which fields were/weren't present and why missing = forgery indicator.
  4. Deep authenticity check — Verhoeff checksum, UIDAI branding, DOB/PIN validity if applicable.
  5. Metadata inspection — software tags, timestamp consistency, EXIF findings.
  6. Anomaly severity breakdown (high/medium/low) and what each level implies.
  7. Clear, actionable recommendation for the reader.
  Write in plain English for a non-technical Indian government officer. Be specific.

"tamil": Complete, faithful Tamil translation of the english explanation with ALL technical details.
  Use formal Tamil suitable for official documents.

Return ONLY valid JSON. No markdown fences. No extra text.
"""
        resp = model.generate_content(prompt)
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        return {
            "summary": data.get("summary", fallback["summary"]),
            "english": data.get("english", fallback["english"]),
            "tamil":   data.get("tamil",   fallback["tamil"]),
        }
    except Exception:
        return fallback