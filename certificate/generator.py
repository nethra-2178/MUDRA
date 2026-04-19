"""certificate/generator.py — PDF certificate with Real / Uncertain / Fake gauge."""

import uuid
from pathlib import Path
from datetime import datetime

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    _REPORTLAB_OK = True
except ImportError:
    _REPORTLAB_OK = False

OUTPUT_DIR = Path(__file__).parent.parent / "static" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

import sys
if sys.platform.startswith("win"):
    _BASE            = Path(__file__).parent.parent / "fonts"
    _TAMIL_FONT      = str(_BASE / "FreeSerif.ttf")
    _TAMIL_FONT_BOLD = str(_BASE / "FreeSerifBold.ttf")
    _BODY_FONT       = str(_BASE / "Carlito-Regular.ttf")
    _BODY_FONT_BOLD  = str(_BASE / "Carlito-Bold.ttf")
else:
    _TAMIL_FONT      = "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"
    _TAMIL_FONT_BOLD = "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf"
    _BODY_FONT       = "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"
    _BODY_FONT_BOLD  = "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"

# ── Colour palette ─────────────────────────────────────────────────────
TERRACOTTA  = colors.HexColor("#6B2D22")
SALMON      = colors.HexColor("#C4573D")
FOREST      = colors.HexColor("#2E4A24")
AMBER       = colors.HexColor("#8A5E1A")
CREAM       = colors.HexColor("#F5EDE0")
LIGHT_CREAM = colors.HexColor("#FBF5EE")
DARK_TEXT   = colors.HexColor("#1A0E08")
MID_TEXT    = colors.HexColor("#4A2E22")
MUTED_TEXT  = colors.HexColor("#7A5040")
BORDER_CLR  = colors.HexColor("#D4A898")
GREEN_OK    = colors.HexColor("#1a9e6e")
RED_FAIL    = colors.HexColor("#d94040")
AMBER_WARN  = colors.HexColor("#d48c0a")

# gauge fill colours
GAUGE_REAL      = colors.HexColor("#1a9e6e")
GAUGE_UNCERTAIN = colors.HexColor("#d48c0a")
GAUGE_FAKE      = colors.HexColor("#d94040")
GAUGE_TRACK     = colors.HexColor("#e8ddd5")


def _register_fonts():
    reg = {}
    for name, path in [
        ("FreeSerif",     _TAMIL_FONT),
        ("FreeSerifBold", _TAMIL_FONT_BOLD),
        ("Carlito",       _BODY_FONT),
        ("CarlitoB",      _BODY_FONT_BOLD),
    ]:
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            reg[name] = True
        except Exception:
            reg[name] = False
    return reg


def _verdict_color(verdict: str):
    v = verdict.lower()
    if v == "verified": return GREEN_OK
    if v == "forged":   return RED_FAIL
    return AMBER_WARN


def _verdict_label(verdict: str) -> str:
    v = verdict.lower()
    if v == "verified": return "VERIFIED — AUTHENTIC"
    if v == "forged":   return "FORGED — FRAUDULENT"
    return "UNCERTAIN — REVIEW NEEDED"


def _compute_gauge(score: float, verdict: str) -> tuple:
    """
    Return (real%, uncertain%, fake%) that sum to 100.
    Mirrors the JS computeGaugeValues() logic so PDF matches the web UI.
    """
    s = round(score)
    if verdict.lower() == "verified":
        uncertain = max(0, round((100 - s) * 0.3))
        fake      = max(0, 100 - s - uncertain)
        real      = 100 - uncertain - fake
    elif verdict.lower() == "forged":
        uncertain = max(0, round(s * 0.3))
        real      = max(0, s - uncertain)
        fake      = 100 - real - uncertain
    else:
        real      = max(0, round(s * 0.55))
        fake      = max(0, round((100 - s) * 0.55))
        uncertain = 100 - real - fake

    real      = max(0, min(100, real))
    fake      = max(0, min(100, fake))
    uncertain = max(0, 100 - real - fake)
    return real, uncertain, fake


_BASE_TBL = [
    ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING",    (0, 0), (-1, -1), 7),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ("BOX",           (0, 0), (-1, -1), 1,   BORDER_CLR),
    ("INNERGRID",     (0, 0), (-1, -1), 0.5, BORDER_CLR),
]


def _build_gauge_table(real: int, uncertain: int, fake: int,
                        body_bold: str, body_font: str) -> Table:
    """
    Build a compact 3-row bar-chart table showing Real / Uncertain / Fake.

    Each row: label | filled bar | empty track remainder | % text
    The bar width is approximated by splitting a fixed column into
    filled + empty portions using colWidths proportional to the percentage.

    Total track width = 10 cm.  Bar fills proportionally.
    """
    track_w  = 10.0   # cm
    label_w  = 2.2    # cm
    pct_w    = 1.5    # cm

    def bar_row(label, pct, fill_color, text_color):
        filled = round(track_w * pct / 100, 2)
        empty  = round(track_w - filled, 2)
        # Avoid zero-width columns (ReportLab crashes)
        filled = max(filled, 0.05)
        empty  = max(empty,  0.05)

        label_style = ParagraphStyle(
            "gl", fontName=body_bold, fontSize=8,
            textColor=text_color, alignment=TA_LEFT,
        )
        pct_style = ParagraphStyle(
            "gp", fontName=body_bold, fontSize=8,
            textColor=text_color, alignment=TA_LEFT,
        )

        # Inner table: [filled_bar | empty_track]
        inner = Table(
            [["", ""]],
            colWidths=[filled * cm, empty * cm],
        )
        inner.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0), fill_color),
            ("BACKGROUND",    (1, 0), (1, 0), GAUGE_TRACK),
            ("TOPPADDING",    (0, 0), (-1,-1), 0),
            ("BOTTOMPADDING", (0, 0), (-1,-1), 0),
            ("LEFTPADDING",   (0, 0), (-1,-1), 0),
            ("RIGHTPADDING",  (0, 0), (-1,-1), 0),
            ("ROWBACKGROUNDS",(0, 0), (-1,-1), [colors.white]),
        ]))

        return [
            Paragraph(label, label_style),
            inner,
            Paragraph(f"{pct}%", pct_style),
        ]

    rows = [
        bar_row("Real",      real,      GAUGE_REAL,      GREEN_OK),
        bar_row("Uncertain", uncertain, GAUGE_UNCERTAIN, AMBER_WARN),
        bar_row("Fake",      fake,      GAUGE_FAKE,      RED_FAIL),
    ]

    tbl = Table(rows, colWidths=[label_w*cm, track_w*cm, pct_w*cm])
    tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1), [LIGHT_CREAM, CREAM, LIGHT_CREAM]),
        ("BOX",           (0, 0), (-1, -1), 1,   BORDER_CLR),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, BORDER_CLR),
    ]))
    return tbl


def generate_certificate(
    original_filename: str,
    doc_type: str,
    score_result: dict,
    explanation: dict,
) -> dict:
    cert_id  = uuid.uuid4().hex[:10].upper()
    filename = f"MUDRA_{cert_id}.pdf"
    out_path = OUTPUT_DIR / filename

    if not _REPORTLAB_OK:
        out_path.write_text(
            f"MUDRA Certificate\nID: {cert_id}\nFile: {original_filename}\n"
            f"Verdict: {score_result.get('verdict')}\nScore: {score_result.get('score')}\n"
        )
        return {"cert_id": cert_id, "filename": filename}

    reg        = _register_fonts()
    body_font  = "Carlito"   if reg.get("Carlito")   else "Helvetica"
    body_bold  = "CarlitoB"  if reg.get("CarlitoB")  else "Helvetica-Bold"
    tamil_font = "FreeSerif" if reg.get("FreeSerif") else "Helvetica"

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm,  bottomMargin=2*cm,
    )

    styles = {
        "sec_head": ParagraphStyle(
            "sh", fontName=body_bold, fontSize=10, textColor=TERRACOTTA,
            alignment=TA_LEFT, spaceBefore=12, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "bd", fontName=body_font, fontSize=10, textColor=DARK_TEXT,
            alignment=TA_JUSTIFY, leading=16, spaceAfter=5,
        ),
        "body_small": ParagraphStyle(
            "bs", fontName=body_font, fontSize=9, textColor=MID_TEXT,
            alignment=TA_LEFT, leading=14,
        ),
        "label": ParagraphStyle(
            "lb", fontName=body_bold, fontSize=8, textColor=MUTED_TEXT,
            alignment=TA_LEFT,
        ),
        "value": ParagraphStyle(
            "vl", fontName=body_font, fontSize=10, textColor=DARK_TEXT,
            alignment=TA_LEFT,
        ),
        "cert_id": ParagraphStyle(
            "ci", fontName=body_bold, fontSize=12, textColor=AMBER,
            alignment=TA_LEFT,
        ),
        "tamil": ParagraphStyle(
            "ta", fontName=tamil_font, fontSize=11, textColor=DARK_TEXT,
            alignment=TA_LEFT, leading=22, spaceAfter=6,
        ),
        "footer": ParagraphStyle(
            "ft", fontName=body_font, fontSize=7, textColor=MUTED_TEXT,
            alignment=TA_CENTER,
        ),
        "disclaimer": ParagraphStyle(
            "di", fontName=body_font, fontSize=7, textColor=MUTED_TEXT,
            alignment=TA_CENTER,
        ),
        "gauge_head": ParagraphStyle(
            "gh", fontName=body_bold, fontSize=9, textColor=MUTED_TEXT,
            alignment=TA_CENTER,
        ),
    }

    verdict   = score_result.get("verdict", "UNKNOWN")
    score     = score_result.get("score", 0)
    breakdown = score_result.get("breakdown", {})
    anomalies = score_result.get("anomalies", [])
    checks    = score_result.get("checks", [])
    now       = datetime.now().strftime("%d %B %Y  |  %H:%M hrs")
    v_color   = _verdict_color(verdict)
    v_label   = _verdict_label(verdict)

    # Gauge values
    real_pct, unc_pct, fake_pct = _compute_gauge(score, verdict)

    story = []

    # ── Header ─────────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph(
            "<para align='center'>"
            f"<font name='{body_bold}' size='28' color='#6B2D22'>MUDRA</font>"
            "<br/><br/>"
            f"<font name='{body_font}' size='9' color='#7A5040'>DOCUMENT AUTHENTICITY CERTIFICATE</font>"
            "</para>",
            ParagraphStyle("hdr_combined", alignment=TA_CENTER, leading=36),
        )
    ]], colWidths=[17*cm])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), CREAM),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), 14),
        ("BOTTOMPADDING", (0,0),(-1,-1), 14),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
        ("BOX",           (0,0),(-1,-1), 1.5, BORDER_CLR),
    ]))
    story += [hdr, Spacer(1, 0.25*cm),
              HRFlowable(width="100%", thickness=1.5, color=TERRACOTTA, spaceAfter=8)]

    # ── Certificate meta ────────────────────────────────────────────────
    meta_tbl = Table([
        [Paragraph("CERTIFICATE ID", styles["label"]),
         Paragraph("DATE & TIME",    styles["label"]),
         Paragraph("DOCUMENT TYPE",  styles["label"])],
        [Paragraph(cert_id,          styles["cert_id"]),
         Paragraph(now,              styles["value"]),
         Paragraph(doc_type.upper(), styles["value"])],
    ], colWidths=[5.5*cm, 6.5*cm, 5*cm])
    meta_tbl.setStyle(TableStyle([
        *_BASE_TBL,
        ("BACKGROUND", (0,0),(-1,0), CREAM),
        ("BACKGROUND", (0,1),(-1,1), LIGHT_CREAM),
    ]))
    story += [meta_tbl, Spacer(1, 0.2*cm)]

    file_tbl = Table(
        [[Paragraph("ORIGINAL FILE",  styles["label"]),
          Paragraph(original_filename, styles["value"])]],
        colWidths=[3.5*cm, 13.5*cm],
    )
    file_tbl.setStyle(TableStyle([
        *_BASE_TBL,
        ("BACKGROUND", (0,0),(0,-1), CREAM),
    ]))
    story += [file_tbl, Spacer(1, 0.35*cm),
              HRFlowable(width="100%", thickness=0.5, color=BORDER_CLR, spaceAfter=6)]

    # ── Verdict + score ─────────────────────────────────────────────────
    ela_w  = breakdown.get("ela", 0)
    ocr_w  = breakdown.get("ocr_missing", breakdown.get("ocr", 0))
    auth_w = breakdown.get("ocr_auth", 0)
    meta_w = breakdown.get("metadata", 0)
    susp   = ela_w + ocr_w + auth_w + meta_w

    verdict_style = ParagraphStyle(
        "vt", fontName=body_bold, fontSize=15, textColor=v_color, alignment=TA_LEFT,
    )
    score_style = ParagraphStyle(
        "sc", fontName=body_bold, fontSize=15, textColor=DARK_TEXT, alignment=TA_LEFT,
    )

    v_tbl = Table([
        [Paragraph("VERDICT",          styles["label"]),
         Paragraph("AUTHENTICITY",     styles["label"]),
         Paragraph("SUSPICION POINTS", styles["label"])],
        [Paragraph(v_label, verdict_style),
         Paragraph(f"{score:.1f} / 100", score_style),
         Paragraph(
             f"ELA:{ela_w}  OCR:{ocr_w}  Auth:{auth_w}  Meta:{meta_w}  = {susp}",
             styles["body_small"],
         )],
    ], colWidths=[5.5*cm, 4.5*cm, 7*cm])
    v_tbl.setStyle(TableStyle([
        *_BASE_TBL,
        ("BACKGROUND", (0,0),(-1,0), CREAM),
        ("BACKGROUND", (0,1),(-1,1), LIGHT_CREAM),
        ("BOX",        (0,0),(-1,-1), 2,   v_color),
        ("LINEBELOW",  (0,0),(-1,0),  1.5, v_color),
    ]))
    story += [v_tbl, Spacer(1, 0.3*cm)]

    # ── Authenticity gauge ──────────────────────────────────────────────
    story.append(Paragraph("AUTHENTICITY BREAKDOWN", styles["sec_head"]))
    story.append(Paragraph(
        "Shows how Real, Uncertain, and Fake the document scores across all forensic checks.",
        styles["body_small"],
    ))
    story.append(Spacer(1, 0.15*cm))
    story.append(_build_gauge_table(real_pct, unc_pct, fake_pct, body_bold, body_font))
    story.append(Spacer(1, 0.35*cm))

    # ── Verification checks ─────────────────────────────────────────────
    story.append(Paragraph("VERIFICATION CHECKS", styles["sec_head"]))
    status_label = {"pass":"PASS ✓", "fail":"FAIL ✗", "warn":"WARN ⚠"}
    status_color = {"pass":GREEN_OK, "fail":RED_FAIL, "warn":AMBER_WARN}
    row_bg       = {
        "pass": colors.HexColor("#EEF5EB"),
        "fail": colors.HexColor("#FBF0EF"),
        "warn": colors.HexColor("#FDF8EC"),
    }

    chk_rows = [[
        Paragraph("Check",  styles["label"]),
        Paragraph("Result", styles["label"]),
        Paragraph("Detail", styles["label"]),
    ]]
    chk_cmds = [*_BASE_TBL, ("BACKGROUND",(0,0),(-1,0), CREAM)]
    for i, chk in enumerate(checks, 1):
        st = chk.get("status","warn")
        chk_rows.append([
            Paragraph(chk.get("name",""),   styles["body_small"]),
            Paragraph(
                status_label.get(st,"?"),
                ParagraphStyle(f"s{i}", fontName=body_bold, fontSize=9,
                               textColor=status_color.get(st, AMBER_WARN), alignment=TA_CENTER),
            ),
            Paragraph(chk.get("detail",""), styles["body_small"]),
        ])
        chk_cmds.append(("BACKGROUND",(0,i),(-1,i), row_bg.get(st, LIGHT_CREAM)))

    c_tbl = Table(chk_rows, colWidths=[4.5*cm, 2*cm, 10.5*cm])
    c_tbl.setStyle(TableStyle(chk_cmds))
    story += [c_tbl, Spacer(1, 0.35*cm)]

    # ── Anomalies ───────────────────────────────────────────────────────
    if anomalies:
        story.append(Paragraph("DETECTED ANOMALIES", styles["sec_head"]))
        sev_bg = {
            "high":   colors.HexColor("#FBF0EF"),
            "medium": colors.HexColor("#FDF8EC"),
            "low":    colors.HexColor("#EEF5EB"),
        }
        sev_fg = {"high":RED_FAIL, "medium":AMBER_WARN, "low":FOREST}

        a_rows = [[Paragraph("Severity",styles["label"]), Paragraph("Finding",styles["label"])]]
        a_cmds = [*_BASE_TBL, ("BACKGROUND",(0,0),(-1,0), CREAM)]
        for i, a in enumerate(anomalies, 1):
            sev = a.get("severity","low")
            a_rows.append([
                Paragraph(
                    sev.upper(),
                    ParagraphStyle(f"as{i}", fontName=body_bold, fontSize=9,
                                   textColor=sev_fg.get(sev,DARK_TEXT), alignment=TA_CENTER),
                ),
                Paragraph(a.get("text",""), styles["body_small"]),
            ])
            a_cmds.append(("BACKGROUND",(0,i),(-1,i), sev_bg.get(sev, LIGHT_CREAM)))

        a_tbl = Table(a_rows, colWidths=[2.5*cm, 14.5*cm])
        a_tbl.setStyle(TableStyle(a_cmds))
        story += [a_tbl, Spacer(1, 0.35*cm)]

    # ── English explanation ─────────────────────────────────────────────
    eng = explanation.get("english","")
    if eng:
        story += [
            HRFlowable(width="100%", thickness=0.5, color=BORDER_CLR, spaceAfter=6),
            Paragraph("ANALYSIS EXPLANATION", styles["sec_head"]),
        ]
        for para in eng.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), styles["body"]))
        story.append(Spacer(1, 0.35*cm))

    # ── Tamil explanation ───────────────────────────────────────────────
    tamil = explanation.get("tamil","")
    if tamil:
        story += [
            HRFlowable(width="100%", thickness=0.5, color=BORDER_CLR, spaceAfter=6),
            Paragraph("விளக்கம் — Tamil Explanation", styles["sec_head"]),
        ]
        for para in tamil.split("\n\n"):
            if para.strip():
                t_tbl = Table(
                    [[Paragraph(para.strip(), styles["tamil"])]],
                    colWidths=[17*cm],
                )
                t_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0,0),(-1,-1), LIGHT_CREAM),
                    ("VALIGN",        (0,0),(-1,-1), "TOP"),
                    ("TOPPADDING",    (0,0),(-1,-1), 6),
                    ("BOTTOMPADDING", (0,0),(-1,-1), 6),
                    ("LEFTPADDING",   (0,0),(-1,-1), 10),
                    ("RIGHTPADDING",  (0,0),(-1,-1), 10),
                    ("BOX",           (0,0),(-1,-1), 0.5, BORDER_CLR),
                ]))
                story += [t_tbl, Spacer(1, 0.15*cm)]
        story.append(Spacer(1, 0.2*cm))

    # ── Footer ──────────────────────────────────────────────────────────
    story += [
        HRFlowable(width="100%", thickness=1, color=TERRACOTTA, spaceBefore=8, spaceAfter=6),
        Paragraph(
            f"MUDRA Document Verification System  •  Certificate ID: {cert_id}  •  {now}",
            styles["footer"],
        ),
        Paragraph(
            "This certificate is generated automatically for informational purposes only. "
            "For legal or official use, verify with the original issuing authority.",
            styles["disclaimer"],
        ),
    ]

    doc.build(story)
    return {"cert_id": cert_id, "filename": filename}