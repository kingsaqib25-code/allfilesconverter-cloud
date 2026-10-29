# converter-cloud — Owner Runbook

Plain-words setup guide. You do **Part A now** (free, no card). **Part B** is
for later, only if you ever put a card on file (still $0 inside the free
tier). **Part C** is just information — the website wiring happens after the
backends are live; nothing for you to do there yet.

What this is, in one line: a small private "conversion machine" that turns
files into PDF or Word. A file goes in, the converted file comes straight
back out, and **everything is deleted immediately** — nothing is kept anywhere.

---

## Part A — Hugging Face Spaces (free, NO card needed)

We run **two** copies so that if one is asleep or busy, the other answers.

### A1. Create a free account

1. Go to **huggingface.co** and click **Sign Up** (top right).
2. Sign up with your email (or "Continue with Google"). **No card is asked.**
3. Confirm your email if it asks.

### A2. Make a token (the Spaces need it once, for uploading the files)

1. Click your profile picture (top right) → **Settings**.
2. Left menu → **Access Tokens** → **Create new token**.
3. Name: `spaces-upload`. Type: **Write**. Click **Create**.
4. **Copy the token** somewhere safe (you won't see it again). Nobody else
   should ever see it.

### A3. Create Space #1

1. Click your profile picture → **New Space**.
2. Fill in:
   - **Space name:** `allfilesconverter-cloud-1`
   - **License:** MIT (any is fine)
   - **Select the Space SDK:** **Docker** ← important, pick Docker
   - **Space hardware:** CPU basic (the free one)
   - **Visibility:** Public
3. Click **Create Space**.
4. You land on an empty Space page. Click the **Files** tab → **Add file** →
   **Upload files**, and upload these 4 files from the `converter-cloud`
   folder: `Dockerfile`, `app.py`, `requirements.txt`, `.dockerignore`.
   (Or: mono will give you 3 copy-paste `git` commands that do the same —
   ask if you prefer that.)
5. The Space starts **building** automatically (first build takes ~5–10
   minutes because LibreOffice is big — that is normal, one time only).
6. When the Space status says **Running**, open its address. It looks like:
   `https://YOUR-USERNAME-allfilesconverter-cloud-1.hf.space`
   You should see the "converter-cloud" info page. Add `/healthz` to the
   address — it should show `{"ok": true}`.
7. **Save that address.** That is Backend #1.

### A4. Create Space #2

Repeat A3 with Space name **`allfilesconverter-cloud-2`**. Same 4 files.
Save its address — that is Backend #2.

### A5. Two things to know

- **Sleeping:** free Spaces sleep after about 48 hours with no visitors.
  The first visitor after sleep waits ~30–60 seconds while it wakes up.
  With two Spaces it is rare that both are asleep at once — and the website
  tries the second one automatically.
- **Cost:** $0. Nothing to pay, no card on file.

---

## Part B — Google Cloud Run (LATER — only if you ever add a card)

This is the bigger engine: about **40,000–60,000 conversions a month free**,
and it never "sleeps". It needs a Google Cloud project with a billing
account (card on file). Inside the free tier the bill is $0 — but set the
$1 alert below anyway, so you would know instantly if anything ever changed.

Run these on any computer with the Google Cloud CLI installed
(`cloud.google.com/sdk` → install → then the commands):

```bash
# 1. Sign in and pick your project (replace PROJECT_ID)
gcloud auth login
gcloud config set project PROJECT_ID

# 2. Turn on the services we need (one time)
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com

# 3. Make a place to store the built image (Mumbai region — closest to you)
gcloud artifacts repositories create converter-cloud \
  --repository-format=docker --location=asia-south1 \
  --description="converter-cloud images"

# 4. Build the image from the converter-cloud folder (run this INSIDE the folder)
cd converter-cloud
gcloud builds submit --region=asia-south1 \
  --tag asia-south1-docker.pkg.dev/PROJECT_ID/converter-cloud/converter-cloud:latest .

# 5. Deploy it
gcloud run deploy converter-cloud \
  --image asia-south1-docker.pkg.dev/PROJECT_ID/converter-cloud/converter-cloud:latest \
  --region asia-south1 --platform managed \
  --memory 2Gi --cpu 1 --timeout 300 --max-instances 10 \
  --allow-unauthenticated --port 7860 \
  --set-env-vars CORS_ORIGINS=https://allinoneconverter.vercel.app
```

After step 5 Google prints a **Service URL** — save it. That becomes Backend #3.

**Where to watch the free usage:** Google Cloud Console → **Billing** →
**Budgets & alerts** → create a budget of **$1** with email alerts at 50%,
90%, 100%. Usage itself: Console → **Cloud Run** → your service → **Metrics**,
or **Billing** → **Reports** filtered to Cloud Run. Free tier per month:
2M requests, 180,000 vCPU-seconds, 360,000 GB-seconds — one conversion is a
few vCPU-seconds, so tens of thousands of conversions fit.

---

## Part C — How the website will use the backends (nothing to do yet)

When the backends are live, the website gets one setting — the backend list
in failover order:

```
CONVERTER_BACKENDS=https://<you>-allfilesconverter-cloud-1.hf.space,https://<you>-allfilesconverter-cloud-2.hf.space[,https://<cloud-run-url>]
```

The site's converter widget will:
1. Try Backend #1 (20 s timeout).
2. If it is asleep/busy/errors → try Backend #2 automatically.
3. (Later) If both fail → Backend #3 (Cloud Run).

Only the conversions a browser can't do well go to the cloud
(full-fidelity PDF → Word, Office → PDF). Everything else keeps running
100% on the visitor's device, as today. The privacy page will say exactly
this: cloud files are converted and **immediately deleted**, never stored.

**Status: ⏳ waiting — site wiring starts after at least Backend #1 is live
and its URL is saved.**
