# converter-cloud — stateless file-conversion microservice (headless LibreOffice).
# Base: slim Debian (bookworm) + Python 3.12. Exposes 7860 (HF Spaces convention).

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SAL_DISABLE_OPENCL=1

# LibreOffice headless (Writer/Calc/Draw import filters cover office docs,
# PDFs and images) + common fonts. --no-install-recommends keeps it lean.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-draw \
        libreoffice-core \
        fonts-dejavu \
        fonts-liberation \
        fonts-noto-core \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /srv/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Non-root runtime. LibreOffice gets a fresh per-request profile dir
# (see app.py), so no shared state is ever needed.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/healthz', timeout=8)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
