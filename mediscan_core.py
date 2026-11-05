"""
MediScan AI — core logic (no Streamlit imports)
================================================
Everything that talks to Gemini, prepares images and shapes the report lives
here, so the Streamlit UI (app.py) and the validation harness (eval/run_eval.py)
use exactly the same code path.

Design choices that matter for accuracy:
  * Structured JSON output (responseSchema) — urgency, confidence and
    differentials come back as fields, never guessed from keywords.
  * No invented numbers — measurements only when a scale is visible;
    likelihood tiers instead of uncalibrated percentages.
  * Modality-specific review checklists so no region is skipped.
  * Google's default sampling for Gemini 3 (temperature is not forced to 0).
  * Truncated / blocked responses are reported, never shown as complete.
  * Optional two-pass read: blind image read first, history integrated second.

© 2026 Dr. Shantanu Samanta. Research & educational use only. Not a medical device.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time

import requests
from PIL import Image, ImageOps

try:  # iPhone photos (.heic) — optional dependency
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False

AUTHOR = "Dr. Shantanu Samanta"
APP_NAME = "MediScan AI"

# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

# Fallback list, used only if the live models.list call fails.
DEFAULT_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-3.1-pro-preview",
]
PAID_ONLY_HINTS = ("pro-preview",)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def list_models(api_key: str) -> list[str]:
    """Return vision-capable Gemini text models available to this key.

    Model IDs retire often, so we ask the API instead of hard-coding them.
    Falls back to DEFAULT_MODELS on any error.
    """
    try:
        out, token = [], None
        for _ in range(5):
            params = {"pageSize": 200}
            if token:
                params["pageToken"] = token
            r = requests.get(
                f"{GEMINI_BASE}/models",
                headers={"x-goog-api-key": api_key},
                params=params,
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            for m in data.get("models", []):
                name = m.get("name", "").replace("models/", "")
                methods = m.get("supportedGenerationMethods", [])
                if (
                    name.startswith("gemini-")
                    and "generateContent" in methods
                    and not any(x in name for x in ("image", "tts", "audio", "embedding",
                                                     "live", "computer-use", "robotics"))
                ):
                    out.append(name)
            token = data.get("nextPageToken")
            if not token:
                break
        if not out:
            return DEFAULT_MODELS
        # Preferred ordering: known-good defaults first, then everything else newest-first
        ordered = [m for m in DEFAULT_MODELS if m in out]
        rest = sorted((m for m in out if m not in ordered), reverse=True)
        return ordered + rest
    except Exception:
        return DEFAULT_MODELS


def is_gemini3_or_later(model: str) -> bool:
    try:
        major = int(model.split("-")[1].split(".")[0])
        return major >= 3
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Modality checklists
# ─────────────────────────────────────────────────────────────────────────────

MODALITY_CHECKLISTS = {
    "Auto-detect": "",
    "Chest X-Ray": (
        "Projection (PA/AP/lateral), rotation, inspiration, penetration. "
        "Airway and trachea position. Lungs zone by zone (upper/mid/lower, both sides), "
        "pleura and costophrenic angles, pneumothorax. Heart size (CTR only if PA) and "
        "contour, mediastinum, hila. Diaphragm and free air under it. Bones (ribs, clavicles, "
        "spine), soft tissues. Lines, tubes and devices with tip position. "
        "Review areas: apices, retrocardiac region, behind diaphragm, hila."
    ),
    "Other X-Ray (bone / abdomen)": (
        "Projection and adequacy. Bone: alignment, cortex, trabecular pattern, fracture lines, "
        "joint spaces, periosteal reaction, lytic/sclerotic lesions, soft tissues, foreign bodies. "
        "Abdomen: bowel gas pattern, dilatation, air-fluid levels, free air, calcifications, "
        "organ outlines, bones, lines/devices."
    ),
    "CT Scan": (
        "Region, plane, window, contrast phase if inferable. Systematic organ-by-organ review "
        "of every structure in the field. Hemorrhage, mass effect, midline shift and herniation "
        "for head CT; vessels, nodes, bowel and free fluid/air for body CT. Bones in bone window "
        "if shown. State which slices/levels were not provided."
    ),
    "MRI": (
        "Region, plane, sequence (T1/T2/FLAIR/DWI/ADC/post-contrast) if inferable. Signal "
        "characteristics on each available sequence, diffusion restriction (DWI with ADC "
        "correlation), enhancement, mass effect. State which sequences are missing for a "
        "complete assessment."
    ),
    "ECG": (
        "First check calibration (paper speed 25 mm/s, 10 mm/mV) from the image; if not "
        "visible say so. Rate, rhythm, P waves, PR interval, QRS axis, QRS duration and "
        "morphology (bundle branch block, pre-excitation), QT/QTc, ST segments lead by lead, "
        "T waves, Q waves, chamber enlargement/hypertrophy, ectopy. Lead reversal or artefact. "
        "STEMI and STEMI-equivalent patterns must be explicitly excluded or reported."
    ),
    "EEG": (
        "Montage and settings if visible. Background rhythm (frequency, amplitude, symmetry, "
        "reactivity), state (awake/drowsy/sleep), focal or generalized slowing, epileptiform "
        "discharges (spikes, sharp waves, spike-wave) with location, periodic patterns, "
        "artefacts (eye, muscle, electrode)."
    ),
    "EMG / NCV": (
        "Nerves/muscles tested, latencies, amplitudes, conduction velocities, F-waves, "
        "spontaneous activity, motor unit morphology and recruitment. Pattern: axonal vs "
        "demyelinating, focal vs generalized."
    ),
    "Ultrasound": (
        "Organ/region, probe plane if inferable. Size only if calipers or scale are shown. "
        "Echogenicity, echotexture, margins, posterior acoustic features, vascularity if "
        "Doppler shown, free fluid. Apply TI-RADS/BI-RADS/O-RADS only for thyroid/breast/"
        "adnexal lesions where the image genuinely supports it."
    ),
    "Fundus photograph": (
        "Image field and quality. Optic disc (colour, margins, cup:disc ratio, swelling, "
        "pallor), macula (foveal reflex, exudates, hemorrhages, drusen, edema signs), vessels "
        "(A:V ratio, nicking, tortuosity, emboli, neovascularization), periphery visible, "
        "hemorrhages by type, cotton-wool spots. Grade diabetic/hypertensive retinopathy only "
        "if features support it."
    ),
    "Histopathology": (
        "Tissue type, stain, magnification if inferable. Architecture, cellularity, cytology "
        "(nuclear size, pleomorphism, chromatin, nucleoli, mitoses), necrosis, inflammation, "
        "invasion, margins if present. State that IHC/clinical correlation may be needed."
    ),
    "PET Scan": (
        "Tracer if inferable. Distribution of uptake, focal hypermetabolic lesions with "
        "location, SUV only if displayed on the image, physiological vs pathological uptake."
    ),
    "DEXA": (
        "Sites measured, T-scores and Z-scores only as printed on the report image, "
        "WHO category, vertebral artefacts that may falsely elevate BMD."
    ),
}

LIKELIHOOD_TIERS = ["Most likely", "Likely", "Possible", "Less likely", "Must exclude"]
URGENCY_LEVELS = ["Routine", "Semi-urgent", "Urgent", "Emergency"]
CONFIDENCE_LEVELS = ["High", "Medium", "Low"]
QUALITY_LEVELS = ["Excellent", "Good", "Adequate", "Poor", "Non-diagnostic"]

# ─────────────────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a careful clinical image-interpretation assistant reporting the way an experienced radiologist, cardiologist, neurophysiologist, ophthalmologist or pathologist would, for review by a qualified physician.

RULES — these override everything else:
1. Report only what is visible. If a structure is obscured, cropped, out of frame or not on the provided views, list it under "not_assessable" with the reason. Never fill gaps from typical anatomy.
2. NO INVENTED NUMBERS. Give measurements in mm/cm ONLY if a ruler, scale bar, caliper readout or printed value is visible in the image; otherwise describe size relative to neighbouring anatomy (e.g. "about one rib interspace") and set measurement_basis accordingly. Do not estimate age or sex unless printed on the image or obvious from the anatomy, and say which.
3. Use structured lexicons (BI-RADS, TI-RADS, LI-RADS, PI-RADS, Fleischner, etc.) ONLY when the modality, region and image genuinely support them. Never force a category.
4. Review systematically. Report pertinent normal findings and explicitly exclude the dangerous diagnoses relevant to this study.
5. Differential diagnosis: use the likelihood tiers provided (Most likely / Likely / Possible / Less likely / Must exclude). Do not give percentages. For each, state the image features for and against.
6. Urgency must reflect the most serious finding actually seen, not a hypothetical one.
7. Confidence is your own honest self-assessment; give concrete reasons (image quality, single view, atypical appearance, missing history, missing sequences/leads).
8. Clinical history, if given, may sharpen the differential but must never override or invent image findings. If history and image disagree, say so.
9. If the image is not a medical image, or is too poor to interpret, say so plainly with quality "Non-diagnostic", Low confidence and an empty differential.
"""


def _review_instruction(modality: str) -> str:
    checklist = MODALITY_CHECKLISTS.get(modality, "")
    if modality == "Auto-detect" or not checklist:
        return (
            "First identify the modality and region. Then review systematically using the "
            "standard checklist a specialist in that modality would use, covering every "
            "region/structure in the image."
        )
    return (
        f"The clinician indicates this study is: {modality}. If the image clearly is a "
        f"different modality, say so in identification.notes and use the correct checklist.\n"
        f"Review checklist — address every item that is visible, and list the rest under "
        f"not_assessable:\n{checklist}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Response schema (Gemini OpenAPI subset)
# ─────────────────────────────────────────────────────────────────────────────

def _s(desc: str) -> dict:
    return {"type": "STRING", "description": desc}


def _enum(values: list, desc: str) -> dict:
    return {"type": "STRING", "enum": values, "description": desc}


def _arr(item: dict, desc: str) -> dict:
    return {"type": "ARRAY", "items": item, "description": desc}


def _obj(props: dict, required: list | None = None, desc: str = "") -> dict:
    o = {"type": "OBJECT", "properties": props, "propertyOrdering": list(props.keys())}
    if required:
        o["required"] = required
    if desc:
        o["description"] = desc
    return o


REPORT_SCHEMA = _obj(
    {
        "identification": _obj(
            {
                "modality": _s("Imaging/recording modality"),
                "region": _s("Anatomical region or recording type"),
                "view": _s("Projection, plane, sequence or montage; 'Not determinable' if unclear"),
                "laterality": _s("Right / Left / Bilateral / Not applicable / Not determinable"),
                "notes": _s("Demographics only if printed or anatomically obvious; modality mismatch notes"),
            },
            ["modality", "region", "view", "laterality"],
        ),
        "quality": _obj(
            {
                "rating": _enum(QUALITY_LEVELS, "Overall diagnostic quality"),
                "issues": _arr(_s("One technical issue"), "Exposure, rotation, motion, artefact, cropping, photo-of-screen glare, etc."),
                "impact": _s("How the quality limits interpretation"),
            },
            ["rating", "issues", "impact"],
        ),
        "findings": _arr(
            _obj(
                {
                    "area": _s("Region/structure/lead reviewed"),
                    "observation": _s("What is seen, in standard terminology"),
                    "status": _enum(["Normal", "Abnormal", "Equivocal"], "Assessment of this area"),
                },
                ["area", "observation", "status"],
            ),
            "Systematic review, one entry per area on the checklist that is visible",
        ),
        "measurement_basis": _s(
            "How any sizes were derived: 'Visible scale/calipers', 'Printed values', or "
            "'No scale visible — relative sizes only'"
        ),
        "critical_findings": _arr(
            _s("A finding needing prompt action"),
            "Only findings actually seen that need urgent/emergency action; empty if none",
        ),
        "pertinent_negatives": _arr(_s("A dangerous diagnosis explicitly not seen"), "Important exclusions"),
        "impression": _arr(_s("One impression point"), "Key conclusions in decreasing clinical significance"),
        "differentials": _arr(
            _obj(
                {
                    "diagnosis": _s("Diagnosis"),
                    "likelihood": _enum(LIKELIHOOD_TIERS, "Likelihood tier"),
                    "supporting": _s("Image features (and history) in favour"),
                    "against": _s("Features against, or what is missing"),
                },
                ["diagnosis", "likelihood", "supporting", "against"],
            ),
            "Ordered most to least likely; 'Must exclude' items last",
        ),
        "recommendations": _arr(_s("One next step"), "Further imaging, labs, correlation, referral"),
        "urgency": _obj(
            {
                "level": _enum(URGENCY_LEVELS, "Routine / Semi-urgent (within 1 week) / Urgent (24–48 h) / Emergency (immediate)"),
                "rationale": _s("Which finding drives this level"),
            },
            ["level", "rationale"],
        ),
        "confidence": _obj(
            {
                "level": _enum(CONFIDENCE_LEVELS, "Model's self-rated confidence"),
                "reasons": _arr(_s("One factor"), "Concrete factors affecting confidence"),
            },
            ["level", "reasons"],
        ),
        "not_assessable": _arr(_s("Structure/item and reason"), "What could not be evaluated and why"),
        "history_integration": _s(
            "How the clinical history changed or supported the read; 'No history provided' if none"
        ),
    },
    [
        "identification", "quality", "findings", "measurement_basis", "critical_findings",
        "pertinent_negatives", "impression", "differentials", "recommendations", "urgency",
        "confidence", "not_assessable", "history_integration",
    ],
)

# ─────────────────────────────────────────────────────────────────────────────
# Image preparation
# ─────────────────────────────────────────────────────────────────────────────

MAX_LONG_EDGE = 2048          # beyond what HIGH media resolution uses — no detail lost
MAX_TOTAL_INLINE_MB = 18      # keep the whole request well under the inline payload cap


def prepare_image(raw: bytes, name: str) -> dict:
    """Normalise an upload: honour EXIF rotation, drop EXIF/metadata, handle 16-bit
    greyscale and animated GIF/HEIC, downscale to MAX_LONG_EDGE, re-encode.

    Returns {"data", "mime", "name", "orig_size", "size"}.
    """
    img = Image.open(io.BytesIO(raw))
    try:
        img.seek(0)  # first frame of animated GIF / multi-frame TIFF
    except Exception:
        pass
    img = ImageOps.exif_transpose(img)

    if img.mode in ("I;16", "I;16B", "I;16L", "I"):
        # 16-bit greyscale (common in exported radiographs): window to full range
        img = img.convert("I")
        lo, hi = img.getextrema()
        scale = 255.0 / max(1, (hi - lo))
        img = img.point(lambda v: (v - lo) * scale).convert("L")
    elif img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (0, 0, 0))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode not in ("L", "RGB"):
        img = img.convert("RGB")

    orig_size = img.size
    if max(img.size) > MAX_LONG_EDGE:
        img.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.LANCZOS)

    buf = io.BytesIO()
    # PNG for greyscale keeps subtle densities lossless; JPEG q95 for colour photos
    if img.mode == "L":
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    else:
        img.save(buf, format="JPEG", quality=95, subsampling=0)
        mime = "image/jpeg"
    return {"data": buf.getvalue(), "mime": mime, "name": name,
            "orig_size": orig_size, "size": img.size}


def uploads_signature(raw_list: list[bytes]) -> str:
    h = hashlib.sha256()
    for b in raw_list:
        h.update(hashlib.sha256(b).digest())
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Gemini call
# ─────────────────────────────────────────────────────────────────────────────

class GeminiError(RuntimeError):
    pass


class QuotaExhausted(GeminiError):
    pass


def _post(model: str, api_key: str, payload: dict, retries: int = 4) -> dict:
    url = f"{GEMINI_BASE}/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    last = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
        except requests.exceptions.Timeout:
            last = GeminiError("Request timed out. Try fewer images or a faster model.")
        except requests.exceptions.RequestException as exc:
            last = GeminiError(f"Network error: {exc}")
        else:
            if resp.status_code == 200:
                return resp.json()
            try:
                err = resp.json().get("error", {})
                msg = err.get("message", "") or resp.text[:400]
            except Exception:
                err, msg = {}, resp.text[:400]
            if resp.status_code == 429:
                low = msg.lower()
                # Daily / per-project quota — retrying is pointless
                if "per day" in low or "perday" in low or "quota" in low and "minute" not in low:
                    raise QuotaExhausted(
                        "Gemini quota for this API key is used up for now. "
                        f"Try later or pick another model. ({msg[:200]})"
                    )
                last = GeminiError(f"Rate limited (429): {msg[:200]}")
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit() and attempt < retries:
                    time.sleep(min(int(retry_after), 30))
                    continue
            elif resp.status_code in (400, 401, 403, 404):
                raise GeminiError(f"API error {resp.status_code}: {msg}")
            else:
                last = GeminiError(f"API error {resp.status_code}: {msg[:300]}")
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise last or GeminiError("Unknown error contacting the Gemini API.")


def _extract(data: dict) -> tuple[str, str, dict]:
    """Return (text, finishReason, usage)."""
    candidates = data.get("candidates") or []
    if not candidates:
        reason = data.get("promptFeedback", {}).get("blockReason")
        raise GeminiError(
            f"The model returned no content (blocked: {reason})." if reason
            else "The model returned no content. Try a different image."
        )
    cand = candidates[0]
    parts = cand.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return text, cand.get("finishReason", "UNKNOWN"), data.get("usageMetadata", {})


def _gen_config(model: str, media_resolution: str) -> dict:
    cfg = {
        "responseMimeType": "application/json",
        "responseSchema": REPORT_SCHEMA,
        "maxOutputTokens": 32768,  # thinking + report; avoids silent truncation
    }
    if media_resolution and media_resolution != "MEDIA_RESOLUTION_UNSPECIFIED":
        cfg["mediaResolution"] = media_resolution
    if not is_gemini3_or_later(model):
        # Gemini 2.x is fine with low temperature; Gemini 3+ is left at Google's
        # recommended default (1.0) — lowering it can degrade reasoning.
        cfg["temperature"] = 0.2
    return cfg


def _image_parts(images: list) -> list:
    return [
        {"inlineData": {"mimeType": i["mime"], "data": base64.b64encode(i["data"]).decode()}}
        for i in images
    ]


def _parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise


def _one_pass(model, api_key, images, user_text, media_resolution) -> tuple[dict, list[str], dict]:
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": _gen_config(model, media_resolution),
        "contents": [{"role": "user", "parts": [{"text": user_text}] + _image_parts(images)}],
    }
    data = _post(model, api_key, payload)
    text, finish, usage = _extract(data)
    warnings = []
    if finish not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        warnings.append(
            {
                "MAX_TOKENS": "The report was cut off before it finished (output limit reached). "
                              "Sections may be missing — re-run, or use fewer images.",
                "SAFETY": "The model stopped for safety reasons; the report is incomplete.",
                "RECITATION": "The model stopped early (recitation filter); the report is incomplete.",
            }.get(finish, f"The model stopped early (finishReason: {finish}); treat as incomplete.")
        )
    try:
        report = _parse_json(text)
    except Exception:
        raise GeminiError(
            "The model's reply could not be read as a structured report"
            + (" because it was cut off." if finish == "MAX_TOKENS" else ".")
            + " Please run the analysis again."
        )
    return report, warnings, usage


def analyse(
    model: str,
    api_key: str,
    images: list,
    clinical_history: str = "",
    modality: str = "Auto-detect",
    media_resolution: str = "MEDIA_RESOLUTION_HIGH",
    two_pass: bool = False,
) -> dict:
    """Run the analysis. Returns
    {"report": dict, "blind_report": dict|None, "warnings": [...], "requests": int, "usage": [...]}
    """
    history = (clinical_history or "").strip()
    review = _review_instruction(modality)
    n = len(images)
    views = f"{n} image{'s' if n != 1 else ''} of the same study/case" if n > 1 else "1 image"

    if two_pass and history:
        # Pass 1 — blind read, no history (avoids anchoring)
        blind_text = (
            f"Interpret these medical images ({views}). No clinical history is provided for "
            f"this first read — interpret the images on their own.\n\n{review}\n\n"
            "Set history_integration to 'Blind read — no history provided'."
        )
        blind, w1, u1 = _one_pass(model, api_key, images, blind_text, media_resolution)
        # Pass 2 — integrate history with the blind read
        final_text = (
            f"Interpret these medical images ({views}).\n\n{review}\n\n"
            "A first, blind read of the same images (without history) produced this JSON:\n"
            f"{json.dumps(blind, ensure_ascii=False)}\n\n"
            "CLINICAL HISTORY PROVIDED BY THE CLINICIAN:\n"
            f"{history}\n\n"
            "Re-examine the images and produce the final report. Image findings must remain "
            "grounded in what is visible. In history_integration, state exactly what the "
            "history changed compared with the blind read (differential order, urgency, "
            "recommendations), and flag any conflict between history and image."
        )
        final, w2, u2 = _one_pass(model, api_key, images, final_text, media_resolution)
        return {"report": final, "blind_report": blind, "warnings": w1 + w2,
                "requests": 2, "usage": [u1, u2]}

    user_text = f"Interpret these medical images ({views}).\n\n{review}"
    if history:
        user_text += (
            "\n\nCLINICAL HISTORY PROVIDED BY THE CLINICIAN (use it to sharpen the "
            "differential, but never let it override or invent image findings):\n"
            f"{history}"
        )
    report, warnings, usage = _one_pass(model, api_key, images, user_text, media_resolution)
    return {"report": report, "blind_report": None, "warnings": warnings,
            "requests": 1, "usage": [usage]}


# ─────────────────────────────────────────────────────────────────────────────
# Report helpers (shared by UI, PDF, text export and eval)
# ─────────────────────────────────────────────────────────────────────────────

def g(d: dict, *path, default=""):
    """Safe nested get."""
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
        if d is None:
            return default
    return d


def normalise_enum(value: str, allowed: list[str], fallback: str) -> str:
    v = (value or "").strip().lower().replace("_", "-")
    for a in allowed:
        if v == a.lower():
            return a
    return fallback


def urgency_of(report: dict) -> str:
    return normalise_enum(g(report, "urgency", "level"), URGENCY_LEVELS, "Not stated")


def confidence_of(report: dict) -> str:
    return normalise_enum(g(report, "confidence", "level"), CONFIDENCE_LEVELS, "Not stated")


def top_differential(report: dict) -> str:
    diffs = report.get("differentials") or []
    for d in diffs:
        if d.get("likelihood") != "Must exclude":
            return d.get("diagnosis", "")
    return diffs[0].get("diagnosis", "") if diffs else ""


def report_to_markdown(report: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    L = [f"# {APP_NAME} — Clinical Image Report", f"_{AUTHOR}_", ""]
    if meta:
        L.append(f"Generated: {meta.get('when','')} · Model: {meta.get('model','')} · "
                 f"Modality selected: {meta.get('modality','')} · Files: "
                 f"{', '.join(meta.get('files', []))}")
        L.append("")
    if meta.get("history"):
        L += ["## Clinical history provided", meta["history"], ""]
    idn = report.get("identification", {})
    L += ["## Image identification",
          f"- Modality: {idn.get('modality','')}",
          f"- Region: {idn.get('region','')}",
          f"- View / sequence: {idn.get('view','')}",
          f"- Laterality: {idn.get('laterality','')}"]
    if idn.get("notes"):
        L.append(f"- Notes: {idn['notes']}")
    q = report.get("quality", {})
    L += ["", "## Technical quality", f"Rating: {q.get('rating','')}"]
    L += [f"- {i}" for i in q.get("issues", [])]
    if q.get("impact"):
        L.append(f"Impact: {q['impact']}")
    L += ["", "## Systematic findings"]
    L += [f"- **{f.get('area','')}** ({f.get('status','')}): {f.get('observation','')}"
          for f in report.get("findings", [])]
    L.append(f"Measurement basis: {report.get('measurement_basis','')}")
    if report.get("critical_findings"):
        L += ["", "## Critical findings"] + [f"- {x}" for x in report["critical_findings"]]
    if report.get("pertinent_negatives"):
        L += ["", "## Pertinent negatives"] + [f"- {x}" for x in report["pertinent_negatives"]]
    L += ["", "## Impression"] + [f"{i}. {x}" for i, x in enumerate(report.get("impression", []), 1)]
    L += ["", "## Differential diagnosis"]
    for i, d in enumerate(report.get("differentials", []), 1):
        L.append(f"{i}. **{d.get('diagnosis','')}** [{d.get('likelihood','')}] — "
                 f"For: {d.get('supporting','')} Against: {d.get('against','')}")
    L += ["", "## Recommendations"] + [f"- {x}" for x in report.get("recommendations", [])]
    L += [f"Urgency: {urgency_of(report)} — {g(report, 'urgency', 'rationale')}"]
    L += ["", "## AI confidence (model self-rated)", f"Level: {confidence_of(report)}"]
    L += [f"- {x}" for x in g(report, "confidence", "reasons", default=[])]
    if report.get("not_assessable"):
        L += ["", "## Not assessable"] + [f"- {x}" for x in report["not_assessable"]]
    L += ["", "## History integration", report.get("history_integration", "")]
    L += ["", "---", DISCLAIMER, "", f"© {meta.get('year', '2026')} {AUTHOR}"]
    return "\n".join(L)


DISCLAIMER = (
    "This report is generated by an artificial intelligence system for educational "
    "and research-assistive purposes only. It is NOT a substitute for professional medical "
    "evaluation, clinical diagnosis or radiological reporting. All findings must be reviewed, "
    "verified and clinically correlated by a licensed radiologist or appropriate specialist "
    "before any clinical decision is made. Likelihood tiers and confidence are model "
    "self-assessments and are not calibrated probabilities."
)
