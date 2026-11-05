"""
MediScan AI — Clinical Medical Image Interpreter (Streamlit)
=============================================================
Designed & developed by Dr. Shantanu Samanta.

Upload one or more medical images, optionally add clinical history and the
modality, and get a structured clinical report from Google's Gemini vision
models: systematic findings, critical findings, impression, differential
diagnosis by likelihood tier, recommendations with urgency, and a self-rated
confidence — plus a branded PDF.

RESEARCH & EDUCATIONAL USE ONLY. Not a medical device.
"""

import hmac
import html
import os
import time
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

import mediscan_core as core
from pdf_report import build_pdf

load_dotenv()

st.set_page_config(
    page_title="MediScan AI — Dr. Shantanu Samanta",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="auto",
)

AUTHOR = core.AUTHOR
YEAR = datetime.now().year

MEDIA_RESOLUTIONS = {
    "High — recommended for radiology": "MEDIA_RESOLUTION_HIGH",
    "Medium — half the tokens": "MEDIA_RESOLUTION_MEDIUM",
    "Low — cheapest, loses fine detail": "MEDIA_RESOLUTION_LOW",
    "Model default": "MEDIA_RESOLUTION_UNSPECIFIED",
}
ACCEPTED_TYPES = ["jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff"] + (
    ["heic", "heif"] if core.HEIF_OK else []
)
MAX_FILE_MB = 25

# ─────────────────────────────────────────────────────────────────────────────
# Styling — light blue/violet, easy on the eyes
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(
    """
<style>
  :root {
    --ink: #1e2a4a; --muted: #4f5b7a; --soft: #6b7593;
    --indigo: #4b4fc4; --violet: #7a5fd6; --line: #d6daf3;
    --card: rgba(255,255,255,.86);
  }
  .stApp {
    background: linear-gradient(135deg, #e6f0ff 0%, #ece9ff 45%, #f3ecff 100%) fixed;
    color: var(--ink);
  }
  section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #eef3ff 0%, #f1ecff 100%);
    border-right: 1px solid var(--line);
  }
  header[data-testid="stHeader"] { background: transparent; }
  /* Keep the image in view while scrolling the report (wide screens) */
  @media (min-width: 900px) {
    div[data-testid="stColumn"]:has(div.st-key-card_viewer) {
      position: sticky; top: 3.75rem; align-self: flex-start;
    }
  }
  @media (max-width: 640px) {
    .ms-author { margin-left: 0; text-align: left; width: 100%; }
    .ms-brand { padding: 14px 16px; }
  }

  /* Brand header & footer */
  .ms-brand {
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    background: var(--card); border: 1px solid var(--line); border-radius: 18px;
    padding: 16px 22px; margin-bottom: 18px;
    box-shadow: 0 6px 24px rgba(91, 79, 196, .08);
  }
  .ms-logo {
    width: 48px; height: 48px; border-radius: 14px; flex-shrink: 0;
    background: linear-gradient(135deg, #5b8def, #8a6ae0);
    display: flex; align-items: center; justify-content: center;
    color: #fff; font-size: 24px; box-shadow: 0 4px 14px rgba(122, 95, 214, .35);
  }
  .ms-title { font-size: 22px; font-weight: 800; color: var(--ink); letter-spacing: -.3px; line-height: 1.15; }
  .ms-title span { color: var(--violet); }
  .ms-sub { font-size: 13px; color: var(--muted); margin-top: 3px; }
  .ms-author { margin-left: auto; text-align: right; }
  .ms-author-k { font-size: 11px; color: var(--soft); letter-spacing: 1.2px; text-transform: uppercase; }
  .ms-author-n {
    font-size: 18px; font-weight: 800; letter-spacing: -.2px;
    background: linear-gradient(90deg, #3f5bd6, #7a4fd0);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .ms-footer {
    margin-top: 34px; padding: 18px 10px 6px; border-top: 1px solid var(--line);
    text-align: center; color: var(--muted); font-size: 13px; line-height: 1.7;
  }
  .ms-footer b { color: var(--indigo); }

  /* Cards (bordered containers with a key starting "card") */
  div[class*="st-key-card"] {
    background: var(--card); border-radius: 16px !important;
    box-shadow: 0 4px 18px rgba(91, 79, 196, .06);
  }
  .ms-sec { font-size: 13px; font-weight: 800; letter-spacing: 1.2px; text-transform: uppercase;
            color: var(--indigo); margin: 2px 0 10px; }
  .ms-body { font-size: 15px; line-height: 1.7; color: var(--ink); }
  .ms-muted { color: var(--muted); font-size: 13.5px; }

  /* Pills / badges */
  .pill { display: inline-block; padding: 3px 11px; border-radius: 999px; font-size: 12.5px;
          font-weight: 700; border: 1px solid; white-space: nowrap; }
  .p-red    { color: #b42318; background: #fde8e7; border-color: #f4a49d; }
  .p-orange { color: #b54708; background: #fff1e6; border-color: #f8c49a; }
  .p-amber  { color: #8a5a00; background: #fef7e0; border-color: #f2d27a; }
  .p-green  { color: #22704a; background: #e7f5ee; border-color: #9fd6b8; }
  .p-grey   { color: #4f5b7a; background: #eef0f6; border-color: #cfd4e4; }
  .p-violet { color: #5b3fc0; background: #efeafd; border-color: #c9bdf2; }

  /* Summary strip */
  .ms-sum { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
  .ms-sum-k { font-size: 11.5px; color: var(--soft); letter-spacing: 1px; text-transform: uppercase; }
  .ms-sum-v { font-size: 16px; font-weight: 700; color: var(--ink); margin-top: 5px; }
  .ms-crit { background: #fde8e7; border: 1px solid #f4a49d; border-radius: 12px;
             padding: 12px 16px; color: #8f1d14; margin-top: 12px; font-size: 14.5px; }
  .ms-crit b { color: #b42318; }
  .ms-warn { background: #fef7e0; border: 1px solid #f2d27a; border-radius: 12px;
             padding: 10px 14px; color: #6b4a00; margin-bottom: 10px; font-size: 14px; }

  /* Findings table */
  table.ms-t { width: 100%; border-collapse: collapse; font-size: 14px; }
  table.ms-t th { text-align: left; color: var(--soft); font-size: 11.5px; letter-spacing: 1px;
                  text-transform: uppercase; padding: 6px 8px; border-bottom: 1px solid var(--line); }
  table.ms-t td { padding: 8px; border-bottom: 1px solid #e7e9f6; vertical-align: top; color: var(--ink); }
  table.ms-t td:first-child { font-weight: 600; width: 24%; }
  .ms-dx { padding: 10px 0; border-bottom: 1px solid #e7e9f6; }
  .ms-dx:last-child { border-bottom: none; }
  .ms-dx-n { font-weight: 700; font-size: 15px; color: var(--ink); }
  .ms-dx-d { font-size: 13.5px; color: var(--muted); margin-top: 4px; line-height: 1.6; }

  /* Empty state */
  .ms-empty { text-align: center; padding: 34px 20px 10px; }
  .ms-empty-icon { font-size: 52px; }
  .ms-empty-title { color: var(--ink); font-size: 20px; font-weight: 700; margin-top: 8px; }
  .ms-empty-text { color: var(--muted); font-size: 14.5px; margin-top: 6px; }
</style>
""",
    unsafe_allow_html=True,
)


def h(text) -> str:
    """Escape model text before it goes into HTML."""
    return html.escape(str(text or ""))


def brand_header(subtitle: str = "Clinical medical image interpreter · powered by Gemini"):
    st.markdown(
        f"""
<div class="ms-brand">
  <div class="ms-logo">🩺</div>
  <div>
    <div class="ms-title">MediScan <span>AI</span></div>
    <div class="ms-sub">{h(subtitle)}</div>
  </div>
  <div class="ms-author">
    <div class="ms-author-k">Designed &amp; developed by</div>
    <div class="ms-author-n">{h(AUTHOR)}</div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )


def brand_footer():
    st.markdown(
        f"""
<div class="ms-footer">
  <b>MediScan AI</b> · Designed &amp; developed by <b>{h(AUTHOR)}</b> · © {YEAR} All rights reserved<br/>
  For education and research only — not a medical device. Every report must be reviewed by a qualified physician.
</div>""",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Config & optional passcode gate
# ─────────────────────────────────────────────────────────────────────────────

def get_secret(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name, default)


def check_passcode():
    expected = get_secret("APP_PASSCODE")
    if not expected or st.session_state.get("ms_authed"):
        return
    brand_header("Access restricted — enter the passcode to continue")
    entered = st.text_input("Passcode", type="password", key="ms_pass_input")
    if entered:
        if hmac.compare_digest(entered, expected):
            st.session_state["ms_authed"] = True
            st.rerun()
        else:
            st.error("Incorrect passcode.")
    brand_footer()
    st.stop()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_models(api_key: str) -> list:
    return core.list_models(api_key)


# ─────────────────────────────────────────────────────────────────────────────
# Badges
# ─────────────────────────────────────────────────────────────────────────────

URG_CLASS = {"Emergency": ("p-red", "Emergency — immediate"), "Urgent": ("p-orange", "Urgent — 24–48 h"),
             "Semi-urgent": ("p-amber", "Semi-urgent — within 1 week"), "Routine": ("p-green", "Routine")}
CONF_CLASS = {"High": "p-green", "Medium": "p-amber", "Low": "p-red"}
STATUS_CLASS = {"Normal": "p-green", "Abnormal": "p-red", "Equivocal": "p-amber"}
LIK_CLASS = {"Most likely": "p-violet", "Likely": "p-violet", "Possible": "p-grey",
             "Less likely": "p-grey", "Must exclude": "p-orange"}


def urgency_pill(level: str) -> str:
    cls, label = URG_CLASS.get(level, ("p-grey", level or "Not stated"))
    return f'<span class="pill {cls}">{h(label)}</span>'


def conf_pill(level: str) -> str:
    return f'<span class="pill {CONF_CLASS.get(level, "p-grey")}">{h(level or "Not stated")}</span>'


def bullets_html(items) -> str:
    items = [i for i in (items or []) if str(i).strip()]
    if not items:
        return '<div class="ms-muted">None stated.</div>'
    return '<ul class="ms-body" style="margin:0 0 0 1.1em;padding:0">' + "".join(
        f"<li>{h(i)}</li>" for i in items) + "</ul>"


def card(key: str, title: str, body_html: str):
    with st.container(border=True, key=f"card_{key}"):
        st.markdown(f'<div class="ms-sec">{h(title)}</div>{body_html}', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Report rendering
# ─────────────────────────────────────────────────────────────────────────────

def render_summary(report: dict, warnings: list):
    for w in warnings:
        st.markdown(f'<div class="ms-warn">⚠️ {h(w)}</div>', unsafe_allow_html=True)
    urg, conf = core.urgency_of(report), core.confidence_of(report)
    q = core.g(report, "quality", "rating") or "—"
    idn = report.get("identification", {})
    crit = report.get("critical_findings") or []
    crit_html = ""
    if crit:
        crit_html = '<div class="ms-crit"><b>🚨 Critical findings</b><ul style="margin:6px 0 0 1.1em;padding:0">' + \
            "".join(f"<li>{h(c)}</li>" for c in crit) + "</ul></div>"
    with st.container(border=True, key="card_summary"):
        st.markdown(
            f"""
<div class="ms-sum">
  <div><div class="ms-sum-k">Urgency</div><div class="ms-sum-v">{urgency_pill(urg)}</div></div>
  <div><div class="ms-sum-k">Leading diagnosis</div><div class="ms-sum-v">{h(core.top_differential(report) or '—')}</div></div>
  <div><div class="ms-sum-k">Study</div><div class="ms-sum-v">{h(idn.get('modality', ''))} · {h(idn.get('region', ''))}</div></div>
  <div><div class="ms-sum-k">Image quality</div><div class="ms-sum-v">{h(q)}</div></div>
  <div><div class="ms-sum-k">Confidence (self-rated)</div><div class="ms-sum-v">{conf_pill(conf)}</div></div>
</div>{crit_html}""",
            unsafe_allow_html=True,
        )


def render_report(report: dict, blind: dict | None):
    idn = report.get("identification", {})
    q = report.get("quality", {})
    card("id", "Image identification & quality",
         f"""<div class="ms-body">
<b>Modality:</b> {h(idn.get('modality'))} &nbsp;·&nbsp; <b>Region:</b> {h(idn.get('region'))}<br/>
<b>View / sequence:</b> {h(idn.get('view'))} &nbsp;·&nbsp; <b>Laterality:</b> {h(idn.get('laterality'))}
{('<br/><b>Notes:</b> ' + h(idn.get('notes'))) if idn.get('notes') else ''}
<div style="margin-top:10px"><b>Quality:</b> {h(q.get('rating'))}</div></div>
{bullets_html(q.get('issues'))}
{('<div class="ms-muted" style="margin-top:6px">' + h(q.get('impact')) + '</div>') if q.get('impact') else ''}""")

    rows = "".join(
        f"<tr><td>{h(f.get('area'))}</td>"
        f"<td><span class='pill {STATUS_CLASS.get(f.get('status'), 'p-grey')}'>{h(f.get('status'))}</span></td>"
        f"<td>{h(f.get('observation'))}</td></tr>"
        for f in report.get("findings", [])
    )
    card("findings", "Systematic findings",
         f"<table class='ms-t'><tr><th>Area</th><th>Status</th><th>Observation</th></tr>{rows}</table>"
         f"<div class='ms-muted' style='margin-top:8px'><i>Measurement basis:</i> "
         f"{h(report.get('measurement_basis'))}</div>")

    if report.get("pertinent_negatives"):
        card("neg", "Pertinent negatives", bullets_html(report["pertinent_negatives"]))

    imp = report.get("impression", [])
    card("imp", "Impression",
         '<ol class="ms-body" style="margin:0 0 0 1.2em;padding:0">' +
         "".join(f"<li>{h(i)}</li>" for i in imp) + "</ol>" if imp else
         '<div class="ms-muted">None stated.</div>')

    dx = "".join(
        f"""<div class="ms-dx"><span class="ms-dx-n">{i}. {h(d.get('diagnosis'))}</span>
 &nbsp;<span class="pill {LIK_CLASS.get(d.get('likelihood'), 'p-grey')}">{h(d.get('likelihood'))}</span>
<div class="ms-dx-d"><b>For:</b> {h(d.get('supporting'))}<br/><b>Against:</b> {h(d.get('against'))}</div></div>"""
        for i, d in enumerate(report.get("differentials", []), 1)
    )
    card("dx", "Differential diagnosis",
         (dx or '<div class="ms-muted">No differential given.</div>') +
         '<div class="ms-muted" style="margin-top:8px">Likelihood tiers are the model\'s judgement, '
         'not calibrated probabilities.</div>')

    card("rec", "Recommendations",
         bullets_html(report.get("recommendations")) +
         f'<div style="margin-top:10px">{urgency_pill(core.urgency_of(report))} '
         f'<span class="ms-muted">{h(core.g(report, "urgency", "rationale"))}</span></div>')

    card("conf", "AI confidence (model self-rated)",
         f'<div style="margin-bottom:6px">{conf_pill(core.confidence_of(report))}</div>' +
         bullets_html(core.g(report, "confidence", "reasons", default=[])))

    if report.get("not_assessable"):
        card("na", "Not assessable on these images", bullets_html(report["not_assessable"]))

    card("hist", "How the clinical history was used",
         f'<div class="ms-body">{h(report.get("history_integration"))}</div>')

    if blind:
        with st.expander("Compare with the blind read (before history was given)"):
            st.markdown(
                f"""<div class="ms-body">
<b>Blind read leading diagnosis:</b> {h(core.top_differential(blind) or '—')}<br/>
<b>Blind read urgency:</b> {urgency_pill(core.urgency_of(blind))}<br/>
<b>Final leading diagnosis:</b> {h(core.top_differential(report) or '—')}<br/>
<b>Final urgency:</b> {urgency_pill(core.urgency_of(report))}</div>""",
                unsafe_allow_html=True,
            )
            st.caption("If history moved the diagnosis or urgency a lot, check that the image really supports it.")


def render_viewer(images: list):
    with st.container(border=True, key="card_viewer"):
        st.markdown('<div class="ms-sec">Image viewer</div>', unsafe_allow_html=True)
        if not images:
            st.caption("No images.")
            return
        idx = 0
        if len(images) > 1:
            idx = st.radio(
                "View", list(range(len(images))), horizontal=True,
                format_func=lambda i: f"View {i + 1}", label_visibility="collapsed",
            )
        img = images[idx]
        st.image(img["data"], caption=img["name"], width="stretch")
        w, hgt = img["size"]
        ow, oh = img["orig_size"]
        note = f"Sent to the model at {w}×{hgt}px"
        if (w, hgt) != (ow, oh):
            note += f" (original {ow}×{oh}px)"
        st.caption(note + " · use the ⤢ button on the image for full screen.")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def reset_analysis():
    for k in ("report", "blind", "warnings", "meta", "images", "pdf", "sig", "md"):
        st.session_state.pop(k, None)
    st.session_state["uploader_n"] = st.session_state.get("uploader_n", 0) + 1


def main():
    check_passcode()
    brand_header()
    api_key = get_secret("GEMINI_API_KEY")

    # ── Sidebar: settings only ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ Settings")
        models = cached_models(api_key) if api_key else core.DEFAULT_MODELS
        model = st.selectbox("Analysis model", models, index=0,
                             help="List fetched live from Google, so retired models disappear automatically.")
        if any(x in model for x in core.PAID_ONLY_HINTS):
            st.warning("Preview Pro models usually need billing enabled.", icon="💳")
        res_label = st.selectbox("Image detail", list(MEDIA_RESOLUTIONS.keys()), index=0,
                                 help="High detail catches subtler findings (small nodules, line tips).")
        two_pass = st.toggle(
            "Blind read first, then add history", value=False,
            help="Reads the image without history first, then integrates the history and shows "
                 "what changed. Reduces anchoring bias. Uses 2 requests instead of 1. "
                 "Only applies when history is given.")
        st.divider()
        st.markdown("**Privacy**")
        st.caption(
            "Images are sent to Google's Gemini API. On the free tier Google may use submitted data "
            "to improve its models. Crop out names, IDs and dates burned into images before uploading. "
            "EXIF metadata is stripped automatically.")
        st.markdown("**DICOM**")
        st.caption("Export as PNG/JPEG from your PACS viewer (RadiAnt, Horos, Weasis, 3D Slicer) first.")
        if st.session_state.get("report"):
            st.divider()
            st.button("＋ New analysis", width="stretch", on_click=reset_analysis)

    # ── Input card ───────────────────────────────────────────────────────────
    with st.container(border=True, key="card_input"):
        st.markdown('<div class="ms-sec">1 · Study</div>', unsafe_allow_html=True)
        c1, c2 = st.columns([3, 2], gap="large")
        with c1:
            uploads = st.file_uploader(
                "Medical images — add every view of the same study together",
                type=ACCEPTED_TYPES, accept_multiple_files=True,
                key=f"uploader_{st.session_state.get('uploader_n', 0)}",
            )
        with c2:
            modality = st.selectbox(
                "Modality", list(core.MODALITY_CHECKLISTS.keys()), index=0,
                help="Choosing the modality gives the model a specialist review checklist, "
                     "which reduces missed findings.")
            history = st.text_area(
                "Clinical history (optional)", height=110,
                placeholder="e.g. 62 M, smoker, 3 weeks productive cough, fever 38.9°C, "
                            "left pleuritic pain. WBC 16,400.")
        analyse_clicked = st.button("🔬 Generate clinical report", type="primary", width="stretch")

    # ── Prepare uploads ──────────────────────────────────────────────────────
    raw = []
    for f in uploads or []:
        data = f.getvalue()
        if len(data) > MAX_FILE_MB * 1024 * 1024:
            st.warning(f"**{f.name}** is larger than {MAX_FILE_MB} MB — skipped.", icon="⚠️")
            continue
        raw.append((f.name, data))
    sig = core.uploads_signature([d for _, d in raw]) if raw else None

    # A report must never be shown next to different images
    if st.session_state.get("report") and sig and sig != st.session_state.get("sig"):
        for k in ("report", "blind", "warnings", "meta", "images", "pdf", "md"):
            st.session_state.pop(k, None)
        st.info("Images changed — the previous report was cleared. Generate a new one.", icon="🔄")

    if analyse_clicked:
        if not api_key:
            st.error("No Gemini API key configured. Add **GEMINI_API_KEY** to the app secrets "
                     "or to `.env` when running locally.", icon="🔑")
        elif not raw:
            st.error("Upload at least one medical image first.", icon="🖼️")
        else:
            images, bad = [], []
            for name, data in raw:
                try:
                    images.append(core.prepare_image(data, name))
                except Exception:
                    bad.append(name)
            for b in bad:
                st.warning(f"**{b}** could not be opened as an image — skipped.", icon="⚠️")
            total_mb = sum(len(i["data"]) for i in images) * 4 / 3 / 1024 / 1024
            if not images:
                st.error("None of the uploads could be read as images.")
            elif total_mb > core.MAX_TOTAL_INLINE_MB:
                st.error(f"Together the images are about {total_mb:.0f} MB after preparation — "
                         f"too large for one request. Analyse fewer views at a time.")
            else:
                started = time.time()
                passes = "2 passes" if (two_pass and history.strip()) else "1 pass"
                try:
                    with st.spinner(f"Reading {len(images)} image(s) with {model} ({passes}) — "
                                    "usually 20–90 seconds…"):
                        result = core.analyse(model, api_key, images, history, modality,
                                              MEDIA_RESOLUTIONS[res_label], two_pass)
                    meta = {
                        "model": model, "history": history.strip(), "modality": modality,
                        "files": [i["name"] for i in images],
                        "when": datetime.now().strftime("%d %b %Y, %H:%M"),
                        "secs": round(time.time() - started, 1),
                        "read_mode": "Blind read + history" if result["blind_report"] else "Single read",
                        "warnings": result["warnings"], "year": YEAR,
                    }
                    st.session_state.update(
                        report=result["report"], blind=result["blind_report"],
                        warnings=result["warnings"], meta=meta, images=images, sig=sig,
                        md=core.report_to_markdown(result["report"], meta),
                    )
                    try:
                        st.session_state["pdf"] = build_pdf(result["report"], meta, images)
                    except Exception as exc:
                        st.session_state["pdf"] = None
                        st.warning(f"PDF could not be built: {exc}")
                except core.QuotaExhausted as exc:
                    st.error(str(exc), icon="⏳")
                except Exception as exc:
                    st.error(f"Analysis failed: {exc}", icon="🚫")

    report = st.session_state.get("report")

    # ── Empty state ──────────────────────────────────────────────────────────
    if not report:
        with st.container(border=True, key="card_empty"):
            st.markdown(
                '<div class="ms-empty"><div class="ms-empty-icon">🩻</div>'
                '<div class="ms-empty-title">Awaiting a study</div>'
                '<div class="ms-empty-text">Upload the images, choose the modality, add any clinical '
                'history, then generate the report.</div></div>',
                unsafe_allow_html=True,
            )
            cols = st.columns(3)
            for col, (icon, step, label) in zip(cols, [
                ("🖼️", "1", "Upload every view"), ("🧭", "2", "Pick modality & add history"),
                ("📋", "3", "Review the report with the image")]):
                col.markdown(
                    f'<div style="text-align:center;padding:10px 4px 18px"><div style="font-size:26px">{icon}</div>'
                    f'<div class="ms-sum-k" style="margin-top:6px">Step {step}</div>'
                    f'<div class="ms-body" style="font-size:14px">{label}</div></div>',
                    unsafe_allow_html=True,
                )
        brand_footer()
        return

    # ── Report ───────────────────────────────────────────────────────────────
    meta = st.session_state.get("meta", {})
    st.markdown(
        f'<div class="ms-sec" style="margin-top:8px">2 · Report</div>'
        f'<div class="ms-muted" style="margin-bottom:10px">{h(meta.get("when"))} · {h(meta.get("model"))} · '
        f'{h(meta.get("modality"))} · {h(meta.get("read_mode"))} · {len(meta.get("files", []))} file(s) · '
        f'{meta.get("secs", "?")} s</div>',
        unsafe_allow_html=True,
    )
    render_summary(report, st.session_state.get("warnings", []))

    left, right = st.columns([2, 3], gap="large")
    with left:
        render_viewer(st.session_state.get("images", []))
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        if st.session_state.get("pdf"):
            st.download_button("📄 Download PDF", data=st.session_state["pdf"],
                               file_name=f"mediscan_report_{stamp}.pdf", mime="application/pdf",
                               width="stretch", type="primary")
        st.download_button("📝 Download text", data=st.session_state.get("md", ""),
                           file_name=f"mediscan_report_{stamp}.md", mime="text/markdown",
                           width="stretch")
    with right:
        render_report(report, st.session_state.get("blind"))

    st.markdown(f'<div class="ms-warn" style="background:#fff6f4;border-color:#f5c2b8;color:#7a271a">'
                f'<b>Important:</b> {h(core.DISCLAIMER)}</div>', unsafe_allow_html=True)
    with st.expander("Raw model output (JSON)"):
        st.json(report)
    brand_footer()


if __name__ == "__main__":
    main()
