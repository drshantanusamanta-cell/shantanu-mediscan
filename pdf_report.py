"""
PDF export for MediScan AI — branded A4 report with header/footer on every page.
© 2026 Dr. Shantanu Samanta
"""

from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from mediscan_core import (
    APP_NAME, AUTHOR, DISCLAIMER, confidence_of, g, top_differential, urgency_of,
)

INDIGO = colors.HexColor("#3f3d9e")
VIOLET = colors.HexColor("#6d5bd0")
INK = colors.HexColor("#1e2a4a")
MUTED = colors.HexColor("#5b6684")
RULE = colors.HexColor("#d9dcf5")
TINT = colors.HexColor("#f2f1fd")

URGENCY_COLORS = {
    "Emergency": ("#b42318", "#fde8e7"),
    "Urgent": ("#c2410c", "#fff1e6"),
    "Semi-urgent": ("#a16207", "#fef7e0"),
    "Routine": ("#2f6f4f", "#e7f5ee"),
}
CONF_COLORS = {"High": ("#2f6f4f", "#e7f5ee"), "Medium": ("#a16207", "#fef7e0"),
               "Low": ("#b42318", "#fde8e7")}

# Helvetica covers Latin-1 only; map common clinical symbols to safe text.
_SAFE = str.maketrans({
    "≥": ">=", "≤": "<=", "→": "->", "←": "<-", "↑": "(up)", "↓": "(down)", "≈": "~",
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "•": "-", "…": "...",
    "≠": "!=", "∆": "delta ", "Δ": "delta ", "α": "alpha", "β": "beta", "γ": "gamma",
    "θ": "theta", "δ": "delta", "√": "sqrt", "²": "2", "³": "3", " ": " ",
})


def esc(text) -> str:
    t = str(text or "").translate(_SAFE)
    t = t.encode("latin-1", "replace").decode("latin-1")
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _on_page(canvas, doc):
    w, h = A4
    canvas.saveState()
    # Header band
    canvas.setFillColor(TINT)
    canvas.rect(0, h - 14 * mm, w, 14 * mm, stroke=0, fill=1)
    canvas.setFillColor(INDIGO)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(20 * mm, h - 9 * mm, f"{APP_NAME}  ·  Clinical Image Report")
    canvas.setFont("Helvetica-Bold", 9.5)
    canvas.setFillColor(VIOLET)
    canvas.drawRightString(w - 20 * mm, h - 9 * mm, AUTHOR)
    # Footer
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(20 * mm, 13 * mm, w - 20 * mm, 13 * mm)
    canvas.setFont("Helvetica", 7.2)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 8.5 * mm,
                      f"(c) {datetime.now().year} {AUTHOR}  ·  AI-generated draft for "
                      "educational/research use - not a clinical report")
    canvas.drawRightString(w - 20 * mm, 8.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _pill(text, fg, bg, style):
    t = Table([[Paragraph(f'<font color="{fg}"><b>{esc(text)}</b></font>', style)]])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(fg)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_pdf(report: dict, meta: dict, images: list) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=22 * mm, bottomMargin=20 * mm,
        title=f"{APP_NAME} Clinical Report", author=AUTHOR,
    )
    ss = getSampleStyleSheet()
    s_title = ParagraphStyle("t", parent=ss["Title"], fontSize=16, textColor=INK,
                             spaceAfter=1, alignment=0, leading=20)
    s_by = ParagraphStyle("by", parent=ss["Normal"], fontSize=9.5, textColor=VIOLET,
                          fontName="Helvetica-Bold", spaceAfter=4)
    s_meta = ParagraphStyle("m", parent=ss["Normal"], fontSize=8, textColor=MUTED, leading=11)
    s_head = ParagraphStyle("h", parent=ss["Normal"], fontSize=9.5, textColor=INDIGO,
                            fontName="Helvetica-Bold", spaceBefore=11, spaceAfter=3)
    s_body = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.2, leading=13.6, textColor=INK)
    s_bul = ParagraphStyle("bl", parent=s_body, leftIndent=10, bulletIndent=2)
    s_small = ParagraphStyle("sm", parent=s_body, fontSize=8.3, leading=11.5)
    s_pill = ParagraphStyle("p", parent=ss["Normal"], fontSize=8.5, leading=10)
    s_disc = ParagraphStyle("d", parent=ss["Normal"], fontSize=7.8, leading=11,
                            textColor=colors.HexColor("#7a271a"))

    def head(t):
        return [Paragraph(esc(t).upper(), s_head),
                HRFlowable(width="100%", thickness=0.4, color=RULE, spaceAfter=4)]

    def bullets(items):
        return [Paragraph(esc(x), s_bul, bulletText="-") for x in items if str(x).strip()]

    flow = [Paragraph("Clinical Image Report", s_title),
            Paragraph(f"{APP_NAME} by {AUTHOR}", s_by)]
    flow.append(Paragraph(
        f"Generated: {esc(meta.get('when',''))} &nbsp;·&nbsp; Model: {esc(meta.get('model',''))} "
        f"&nbsp;·&nbsp; Modality selected: {esc(meta.get('modality',''))} &nbsp;·&nbsp; "
        f"Read: {esc(meta.get('read_mode',''))}<br/>Files ({len(meta.get('files', []))}): "
        f"{esc(', '.join(meta.get('files', [])) or '-')}", s_meta))
    flow.append(Spacer(1, 6))

    # Patient / reviewer fields (left blank to fill by hand)
    fields = Table(
        [[Paragraph("<b>Patient ID:</b> ____________________", s_small),
          Paragraph("<b>Age / Sex:</b> ____________", s_small),
          Paragraph("<b>Reviewed by:</b> ____________________", s_small)]],
        colWidths=[doc.width * 0.36, doc.width * 0.26, doc.width * 0.38])
    fields.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, RULE), ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    flow += [fields, Spacer(1, 8)]

    # Summary strip
    urg, conf = urgency_of(report), confidence_of(report)
    uf, ub = URGENCY_COLORS.get(urg, ("#5b6684", "#eef0f6"))
    cf, cb = CONF_COLORS.get(conf, ("#5b6684", "#eef0f6"))
    summary = Table(
        [[_pill(f"Urgency: {urg}", uf, ub, s_pill),
          _pill(f"Confidence (self-rated): {conf}", cf, cb, s_pill),
          Paragraph(f"<b>Leading diagnosis:</b> {esc(top_differential(report) or '-')}", s_small)]],
        colWidths=[doc.width * 0.25, doc.width * 0.33, doc.width * 0.42])
    summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    flow.append(summary)

    crit = report.get("critical_findings") or []
    if crit:
        ct = Table([[Paragraph("<b>CRITICAL FINDINGS</b><br/>" + "<br/>".join(
            f"- {esc(c)}" for c in crit), ParagraphStyle(
                "c", parent=s_small, textColor=colors.HexColor("#b42318")))]],
            colWidths=[doc.width])
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fde8e7")),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#f04438")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        flow += [Spacer(1, 6), ct]

    if meta.get("history"):
        flow += head("Clinical history provided")
        flow += [Paragraph(esc(p), s_body) for p in meta["history"].split("\n") if p.strip()]

    idn = report.get("identification", {})
    flow += head("Image identification")
    flow += bullets([f"Modality: {idn.get('modality','')}", f"Region: {idn.get('region','')}",
                     f"View / sequence: {idn.get('view','')}",
                     f"Laterality: {idn.get('laterality','')}"]
                    + ([f"Notes: {idn['notes']}"] if idn.get("notes") else []))

    q = report.get("quality", {})
    flow += head("Technical quality")
    flow.append(Paragraph(f"<b>Rating:</b> {esc(q.get('rating',''))}", s_body))
    flow += bullets(q.get("issues", []))
    if q.get("impact"):
        flow.append(Paragraph(f"<b>Impact:</b> {esc(q['impact'])}", s_body))

    flow += head("Systematic findings")
    rows = [[Paragraph("<b>Area</b>", s_small), Paragraph("<b>Status</b>", s_small),
             Paragraph("<b>Observation</b>", s_small)]]
    for f in report.get("findings", []):
        st = f.get("status", "")
        col = {"Abnormal": "#b42318", "Equivocal": "#a16207"}.get(st, "#2f6f4f")
        rows.append([Paragraph(esc(f.get("area", "")), s_small),
                     Paragraph(f'<font color="{col}"><b>{esc(st)}</b></font>', s_small),
                     Paragraph(esc(f.get("observation", "")), s_small)])
    if len(rows) > 1:
        ft = Table(rows, colWidths=[doc.width * 0.22, doc.width * 0.13, doc.width * 0.65],
                   repeatRows=1)
        ft.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TINT), ("GRID", (0, 0), (-1, -1), 0.4, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        flow.append(ft)
    flow.append(Paragraph(f"<i>Measurement basis: {esc(report.get('measurement_basis',''))}</i>",
                          s_small))

    if report.get("pertinent_negatives"):
        flow += head("Pertinent negatives")
        flow += bullets(report["pertinent_negatives"])

    flow += head("Impression")
    flow += [Paragraph(f"{i}. {esc(x)}", s_bul) for i, x in enumerate(report.get("impression", []), 1)]

    flow += head("Differential diagnosis")
    drows = [[Paragraph("<b>Diagnosis</b>", s_small), Paragraph("<b>Likelihood</b>", s_small),
              Paragraph("<b>For / Against</b>", s_small)]]
    for d in report.get("differentials", []):
        drows.append([Paragraph(f"<b>{esc(d.get('diagnosis',''))}</b>", s_small),
                      Paragraph(esc(d.get("likelihood", "")), s_small),
                      Paragraph(f"<b>For:</b> {esc(d.get('supporting',''))}<br/>"
                                f"<b>Against:</b> {esc(d.get('against',''))}", s_small)])
    if len(drows) > 1:
        dt = Table(drows, colWidths=[doc.width * 0.27, doc.width * 0.15, doc.width * 0.58],
                   repeatRows=1)
        dt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TINT), ("GRID", (0, 0), (-1, -1), 0.4, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        flow.append(dt)

    flow += head("Recommendations")
    flow += bullets(report.get("recommendations", []))
    flow.append(Paragraph(f"<b>Urgency:</b> {esc(urg)} - {esc(g(report, 'urgency', 'rationale'))}",
                          s_body))

    flow += head("AI confidence (model self-rated)")
    flow.append(Paragraph(f"<b>Level:</b> {esc(conf)}", s_body))
    flow += bullets(g(report, "confidence", "reasons", default=[]))

    if report.get("not_assessable"):
        flow += head("Not assessable")
        flow += bullets(report["not_assessable"])

    flow += head("History integration")
    flow.append(Paragraph(esc(report.get("history_integration", "")), s_body))

    for w in meta.get("warnings", []):
        flow.append(Spacer(1, 4))
        flow.append(Paragraph(f'<font color="#b42318"><b>Warning:</b> {esc(w)}</font>', s_small))

    disc = Table([[Paragraph(esc(DISCLAIMER), s_disc)]], colWidths=[doc.width])
    disc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff6f4")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#f5c2b8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    flow += [Spacer(1, 12), KeepTogether(disc)]

    if images:
        flow.append(PageBreak())
        flow += head("Appendix - analysed images")
        for img in images:
            try:
                rl = RLImage(io.BytesIO(img["data"]))
                ratio = rl.imageHeight / float(rl.imageWidth or 1)
                width = min(doc.width, 130 * mm)
                rl.drawWidth, rl.drawHeight = width, width * ratio
                if rl.drawHeight > 170 * mm:
                    s = (170 * mm) / rl.drawHeight
                    rl.drawWidth, rl.drawHeight = rl.drawWidth * s, 170 * mm
                flow += [Spacer(1, 6), rl, Paragraph(esc(img["name"]), s_meta)]
            except Exception:
                flow.append(Paragraph(f"[Could not embed: {esc(img['name'])}]", s_meta))

    doc.build(flow, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
