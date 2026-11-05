---
title: MediScan AI
emoji: 🏥
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8501
pinned: false
license: mit
short_description: Clinical medical image interpreter by Dr. Shantanu Samanta
---

# 🩺 MediScan AI
**Designed & developed by Dr. Shantanu Samanta** · © 2026

Upload a medical image (X-ray, CT, MRI, ECG, EEG, ultrasound, fundus, histopathology…), choose the
modality, optionally add clinical history, and get a structured clinical report: identification,
technical quality, a systematic findings table, critical findings, pertinent negatives, impression,
differential diagnosis by likelihood tier, recommendations with an urgency level, and a self-rated
confidence. Download it as a branded PDF.

> ⚠️ **Research and educational use only.** This is not a medical device and not a substitute for
> a licensed radiologist or specialist. Never act on AI output without qualified physician review.

## How the report is made more reliable

| What | Why |
|---|---|
| **Structured JSON output** (response schema) | Urgency, confidence and differentials are fields, not guessed from keywords — "no emergency intervention required" can no longer show as EMERGENCY. |
| **No invented measurements** | Sizes in mm/cm only when a scale, caliper or printed value is visible; otherwise relative size. JPEG/PNG exports carry no pixel spacing. |
| **Likelihood tiers, not percentages** | Most likely / Likely / Possible / Less likely / Must exclude, each with features for and against. LLM percentages are not calibrated. |
| **Modality checklists** | Choosing CXR, ECG, fundus, CT, MRI, EEG etc. gives the model a specialist review checklist (e.g. ECG calibration, rate, rhythm, axis, intervals, ST by lead). |
| **Google's recommended sampling** | Gemini 3+ runs at the default temperature with thinking on; forcing temperature 0 can degrade reasoning. |
| **Truncation detection** | A report cut off by the output limit or a safety stop is flagged, never shown as complete. |
| **Optional blind read** | Reads the image without history first, then integrates history and shows what changed — reduces anchoring bias (2 requests). |
| **Image preparation** | EXIF rotation honoured and metadata stripped, 16-bit greyscale windowed, downscaled to 2048 px (no detail lost at HIGH resolution), request size checked. |
| **Stale-report guard** | Changing the images clears the old report, so a report is never shown beside different images. |
| **Live model list** | Models are fetched from Google, so retired IDs disappear automatically. |

## Measuring accuracy — `eval/`

Opinions about accuracy are cheap; measure it. Put de-identified images with known diagnoses in
`eval/cases/` (git-ignored), list them in `eval/cases.csv` (copy `eval/cases_template.csv`), then:

```bash
python eval/run_eval.py --model gemini-3.6-flash
python eval/run_eval.py --model gemini-3.6-flash --two-pass
```

It reports top-1 / top-3 diagnosis accuracy, urgency agreement, **under-triage** (the dangerous
error) and critical-finding recall, and saves a CSV per run so you can compare models and settings.

---


## Do I need my own AI model API? — Yes.

This is the most common surprise, so let's be clear about it.

Hugging Face Spaces (and Streamlit Community Cloud) give you **free hosting** — a server to run
your Python app. They do **not** give you a free vision model to call. The free HF Spaces CPU tier
(16 GB RAM, no GPU) also cannot realistically run a medical vision model locally.

So the app calls out to Google's Gemini API, and **you supply the key**.

| | Cost |
|---|---|
| Hugging Face Space (free CPU tier) | ₹0 |
| Streamlit Community Cloud | ₹0 |
| Google AI Studio API key | Free tier available; paid beyond that |

**Get your key:** <https://aistudio.google.com/apikey> — sign in with Google, click *Create API key*,
copy it. Google's free tier covers a generous number of requests per day; check current limits at
<https://ai.google.dev/gemini-api/docs/rate-limits>.

Because the key is stored server-side in this setup, **every analysis anyone runs is billed to your
Google account.** If your Space is public, set the optional `APP_PASSCODE` secret (see below) so
only people you give the passcode to can use it.

---

## What you need before you start

- A Hugging Face account (free) — <https://huggingface.co/join>
  *or* a GitHub + Streamlit Community Cloud account (both free)
- A Google AI Studio API key (see above)

---

## Option A — Deploy on Hugging Face Spaces (~5 minutes)

Hugging Face **deprecated the native Streamlit SDK**. Streamlit apps now deploy through the
**Docker SDK** — the `Dockerfile` in this repo handles that for you, and the YAML block at the top
of this README already sets `sdk: docker` and `app_port: 8501`. You don't need to change anything.

1. Go to <https://huggingface.co/new-space>
2. **Space name:** `mediscan-ai` · **License:** MIT
3. **Select the SDK:** choose **Docker** → **Blank** template
4. **Hardware:** CPU basic (free) · **Visibility:** Private is safest while you test
5. Click **Create Space**
6. On the Space page click **Files** → **Add file** → **Upload files**
7. Drag in **every file from this folder**, including the hidden ones:
   `app.py`, `requirements.txt`, `README.md`, `Dockerfile`, `.gitignore`, `.env.example`,
   and the `.streamlit` folder
   *(if drag-and-drop skips dotfiles, use "Create a new file" and paste the contents instead)*
8. Click **Commit changes to main**
9. Go to **Settings** → **Variables and secrets** → **New secret**:
   - Name: `GEMINI_API_KEY` · Value: your Google AI Studio key → **Save**
   - *(optional but recommended if public)* Name: `APP_PASSCODE` · Value: any phrase you choose
10. The Space rebuilds automatically. First build takes 2–4 minutes. When the status turns
    **Running**, click **App** — you're live at
    `https://huggingface.co/spaces/<your-username>/mediscan-ai`

**If the build fails:** open the **Logs** tab. Nearly always it's a typo in `requirements.txt`
or a missing file.

---

## Option B — Deploy on Streamlit Community Cloud (~5 minutes)

### Step 1 — Put the code on GitHub

1. Go to <https://github.com/new>
2. Repository name: `mediscan-ai` · set it to **Private** · click **Create repository**
3. Click **uploading an existing file**
4. Drag in all the files from this folder (the `Dockerfile` is ignored here — harmless)
5. Click **Commit changes**

### Step 2 — Deploy

1. Go to <https://share.streamlit.io> and sign in with GitHub
2. Click **New app** → **Deploy a public app from a repo**
3. Repository: your `mediscan-ai` repo · Branch: `main` · Main file path: `app.py`
4. Click **Advanced settings** → **Secrets** and paste:

   ```toml
   GEMINI_API_KEY = "your-key-here"
   APP_PASSCODE = ""
   ```

5. Click **Deploy!** — live in about two minutes.

---

## Running it on your own computer

```bash
# 1. Install Python 3.11+ from python.org, then in a terminal:
cd mediscan-ai
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Create your .env file
cp .env.example .env           # Windows: copy .env.example .env
# open .env and paste your real Gemini key

# 3. Run it
streamlit run app.py
```

Your browser opens at <http://localhost:8501>.

---

## How to use it

1. Upload one or more images (JPEG, PNG, WebP, GIF, BMP, TIFF, HEIC — max 25 MB each) and pick the modality.
   Multiple views of the same study go in together and are analysed as one case.
2. Add clinical history if you have it — age, sex, symptoms, duration, relevant labs.
   This measurably sharpens the differential diagnosis.
3. Click **Generate clinical report** and wait 20–90 seconds.
4. Read the report beside the image, then **Download PDF**.

**DICOM files:** the Gemini API doesn't accept `.dcm` directly. Export as PNG or JPEG from your
PACS viewer (Horos, RadiAnt, 3D Slicer, Weasis) first.

---

## Which model should I pick?

Free tier as of July 2026 (check the [pricing page](https://ai.google.dev/gemini-api/docs/pricing)
for changes — this moves fast):

| Model | Free tier | Notes |
|---|---|---|
| `gemini-3.6-flash` | ✅ | **Default.** Newest, strongest free multimodal model. |
| `gemini-3.5-flash` | ✅ | Previous generation, still excellent. |
| `gemini-3.5-flash-lite` | ✅ | Fastest and cheapest; weakest at subtle findings. |
| `gemini-2.5-flash` | ✅ | Older generation. |
| `gemini-2.5-pro` | ✅ | Older but strong reasoning. |
| `gemini-3.1-pro-preview` | ❌ **paid only** | Strongest available; needs billing enabled. |

**Image detail matters more than you'd expect.** Google's `media_resolution` parameter caps how
many tokens each image gets. `HIGH` (1120 tokens/image on Gemini 3) is their recommended setting
for image analysis, and it's the app default — dropping to `LOW` (280 tokens) will cost you
subtle findings like small nodules, early infiltrates, or line tip position.

## How much free quota do I actually get?

Google **no longer publishes free-tier request limits publicly.** The rate-limits page now sends
you to your own dashboard, because limits are per-project and shift with account standing:

👉 **<https://aistudio.google.com/rate-limit>** — sign in to see your real numbers.

To estimate your own usage, one analysis in this app costs roughly:

- **Input:** ~1,120 tokens per image at HIGH detail + ~1,000 tokens of system prompt and
  instructions ≈ **2,200 tokens for a single-image study**
- **Output:** ~1,000–1,500 tokens of report, plus thinking tokens

So the binding constraint on the free tier is almost always **requests per day**, not tokens.
One study = one request, regardless of how many views you upload together (up to 3,600 images
per request). Batching four views of the same study into one analysis costs one request, not four.


---

## Updating the app later

Edit the file on Hugging Face (**Files** → pencil icon) or on GitHub, commit, and the app
redeploys itself. No terminal needed.

## Security notes

- Never commit your real `.env` or `secrets.toml` — `.gitignore` already excludes them.
- Uploaded images are held in memory for the request and are not written to disk by this app,
  but they **are** transmitted to Google's API. Do not upload identifiable patient data unless
  you have the appropriate consent and a data-processing agreement in place.
- If you're handling real patient data, review Google's terms at
  <https://ai.google.dev/gemini-api/terms> — the free tier may use submitted data to improve
  their models. Paid tiers have different terms.

## License

MIT · © 2026 Dr. Shantanu Samanta
