"""
converter-cloud: stateless file-conversion microservice (headless LibreOffice).

WHITE-WASH DESIGN: every request gets a fresh temp directory. The upload is
written there, LibreOffice converts it (with its own fresh per-request
profile dir), the result bytes are read back, and the whole temp directory
— upload, profile, output — is deleted BEFORE the response is sent.

Nothing is persisted: no volumes, no database, no file-content logging.
Logs carry only anonymous sizes/timings, never filenames or contents.
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

log = logging.getLogger("converter-cloud")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MAX_BYTES = 50 * 1024 * 1024   # 50 MB upload cap
CONVERT_TIMEOUT = 90           # seconds per LibreOffice run
MAX_CONCURRENT = 4             # simultaneous conversions per instance
ACQUIRE_TIMEOUT = 30           # seconds a request waits for a free slot

# Extensions LibreOffice can import headlessly (lowercase, with dot).
ALLOWED_EXTS = {
    ".doc", ".docx", ".odt", ".rtf", ".txt",
    ".pdf",
    ".html", ".htm",
    ".csv", ".xls", ".xlsx", ".ods",
    ".ppt", ".pptx", ".odp",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
}

# target -> (mime type, soffice --convert-to filter spec, glob ext, download ext)
TARGETS = {
    "pdf": (
        "application/pdf",
        "pdf",
        ".pdf",
        ".pdf",
    ),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        'docx:"MS Word 2007 XML"',
        ".docx",
        ".docx",
    ),
    "txt": (
        "text/plain; charset=utf-8",
        'txt:"Text (encoded):UTF8"',
        ".txt",
        ".txt",
    ),
}

semaphore = asyncio.Semaphore(MAX_CONCURRENT)

app = FastAPI(title="converter-cloud", docs_url=None, redoc_url=None, openapi_url=None)

_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "https://allinoneconverter.vercel.app").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=86400,
)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!doctype html><html><head><meta charset="utf-8">
<title>converter-cloud</title></head>
<body style="font-family:sans-serif;max-width:640px;margin:40px auto;padding:0 16px">
<h1>converter-cloud</h1>
<p>Stateless file-conversion microservice (headless LibreOffice).</p>
<p><strong>Privacy:</strong> every conversion runs in a fresh temp directory and
everything &mdash; upload, working files, result &mdash; is deleted before the
response is sent. Nothing is stored. Logs carry only anonymous sizes and
timings, never file names or contents.</p>
<p>API: <code>POST /convert</code> (multipart fields: <code>file</code> +
<code>to</code>=<code>pdf</code>|<code>docx</code>|<code>txt</code>)
&middot; <a href="/healthz">/healthz</a></p>
</body></html>"""


async def _read_capped(upload: UploadFile) -> bytes:
    data = bytearray()
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="File too large (max 50 MB).")
    return bytes(data)


@app.post("/convert")
async def convert(request: Request, file: UploadFile = File(...), to: str = Form(...)):
    target = to.strip().lower()
    if target not in TARGETS:
        raise HTTPException(status_code=400, detail="Param 'to' must be one of: pdf, docx, txt.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    # Fast reject on declared size (multipart overhead gets 1 MB slack).
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared = 0
    if declared > MAX_BYTES + 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext or 'unknown'}' cannot be converted here.",
        )

    data = await _read_capped(file)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=ACQUIRE_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=429,
            detail="Server is busy — please retry in a few seconds.",
            headers={"Retry-After": "10"},
        )
    try:
        result = await asyncio.to_thread(_convert_sync, data, ext, target)
    finally:
        semaphore.release()

    log.info("converted to=%s in=%dB out=%dB", target, len(data), len(result))

    mime, _, _, out_ext = TARGETS[target]
    stem = Path(file.filename).stem[:60] or "converted"
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]", "_", stem).strip() or "converted"
    return Response(
        content=result,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{safe_stem}{out_ext}"'},
    )


def _convert_sync(data: bytes, ext: str, target: str) -> bytes:
    """Blocking conversion in a worker thread.

    White-wash: the temp dir (upload + LibreOffice profile + output) is
    removed in `finally`, before any response is built.
    """
    _, filter_spec, _, out_ext = TARGETS[target]
    tmp = Path(tempfile.mkdtemp(prefix="conv-"))
    try:
        src = tmp / f"input{ext}"
        src.write_bytes(data)
        profile = tmp / "lo-profile"  # fresh profile per request: no lock clashes
        cmd = [
            "soffice",
            "--headless",
            "--nologo",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to",
            filter_spec,
            "--outdir",
            str(tmp),
            str(src),
        ]
        try:
            proc = subprocess.run(
                cmd, timeout=CONVERT_TIMEOUT, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=504, detail="Conversion timed out (file too complex or too large)."
            )
        outs = [p for p in sorted(tmp.glob(f"*{out_ext}")) if p.name != src.name]
        if proc.returncode != 0 or not outs:
            raise HTTPException(
                status_code=422, detail="Could not convert this file (unsupported or damaged)."
            )
        return outs[0].read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
