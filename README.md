# converter-cloud

Stateless file-conversion microservice for **All Files Converter**. It handles
the conversions a browser cannot do well — full-fidelity **PDF → Word (.docx)**
and **any office/image file → PDF** — using headless LibreOffice.

Deploy it to free backends (2× Hugging Face Spaces now, Google Cloud Run later).
The website tries the backends in order and fails over automatically, so the
free quotas add up. See [RUNBOOK.md](RUNBOOK.md) for the exact setup clicks.

## Privacy guarantee (the "white-wash")

- Every request gets a **fresh temp directory**; the upload, the LibreOffice
  profile and the output all live there.
- The whole directory is **deleted before the response is sent**.
- No volumes, no database, no object storage. The container filesystem is
  ephemeral, and free backends scale it to zero when idle.
- Logs carry only anonymous sizes and timings — **never filenames or contents**.

## API contract

### `GET /healthz`
→ `200 {"ok": true}` — used by uptime checks and the site's backend picker.

### `GET /`
Tiny human-readable info page (also confirms the service is up).

### `POST /convert`
Multipart form fields:

| Field  | Type | Required | Notes |
|--------|------|----------|-------|
| `file` | file | yes | Max **50 MB**. See allowlist below. |
| `to`   | text | yes | One of `pdf`, `docx`, `txt`. |

**Convertible input extensions:** doc, docx, odt, rtf, txt, pdf, html, htm,
csv, xls, xlsx, ods, ppt, pptx, odp, jpg, jpeg, png, webp, gif, bmp, tif, tiff.

**Success:** `200` with the converted file as the body and
`Content-Disposition: attachment; filename="name.<ext>"`.
MIME types: `application/pdf`, the OOXML wordprocessing MIME for docx,
`text/plain; charset=utf-8` for txt.

**Error codes:**

| Code | Meaning |
|------|---------|
| 400 | Bad `to` value, no file, empty file, or extension not in the allowlist. |
| 413 | Upload larger than 50 MB. |
| 422 | LibreOffice could not convert it (damaged file or unsupported combo). |
| 429 | All conversion slots busy — retry after a few seconds (`Retry-After: 10`). |
| 504 | Conversion took longer than 90 s (very complex/large file). |

Example:

```bash
curl -F "file=@report.pdf" -F "to=docx" https://<backend>/convert -o report.docx
curl https://<backend>/healthz
```

## Limits (per instance)

- Max upload **50 MB**; per-conversion timeout **90 s**; **4** concurrent
  conversions (extra requests get `429`, not a crash).
- PDF → DOCX fidelity is **good, not perfect**: LibreOffice imports the PDF
  through Draw, so complex layouts/tables may shift. Simple text documents
  convert cleanly.
- Scanned/image-only PDFs have no text layer — LibreOffice returns an empty
  result and the API answers `422`. (The website keeps its on-device
  text-extraction path for those.)
- Free Hugging Face Spaces **sleep when idle** (~48 h); the first request
  after sleep takes ~30–60 s to wake. Running two Spaces (failover order)
  makes this rare.

## Environment variables

| Var | Default | Notes |
|-----|---------|-------|
| `CORS_ORIGINS` | `https://allinoneconverter.vercel.app` | Comma-separated list of allowed website origins. |
| `PORT` | `7860` | HF Spaces convention; Cloud Run overrides via its own `PORT`. |

Note: the Docker `CMD` pins port 7860. On Cloud Run, either keep
`--port 7860` on the deploy command or change the CMD to read `$PORT`.

## Local dev

```bash
pip install -r requirements.txt
# needs a local `soffice` (LibreOffice) on PATH
uvicorn app:app --port 7860
```

Or the Docker smoke test: `bash test-local.sh` (needs a Docker daemon).
