# syntax=docker/dockerfile:1
# Applination backend — FastAPI (uvicorn) on :8000
#
# Includes LibreOffice (docx -> pdf; src/pdf_convert.py falls back to `soffice`
# because docx2pdf needs Word/AppleScript and is a no-op on Linux) and the
# Playwright Chromium runtime (src/job_extractor.py renders JS-heavy job pages).

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# LibreOffice Writer covers docx->pdf. fonts-liberation gives Arial/Times
# metric-compatible substitutes so the one-page ATS layout doesn't reflow.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-core \
        fonts-liberation \
        fonts-dejavu-core \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Chromium + its system libs. Kept in its own layer so a requirements change
# doesn't re-download the browser.
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# These four are bind-mounted from /mnt/apps-pool/appconfig/applination on the
# NAS. Create them so a first boot without mounts still starts cleanly.
RUN mkdir -p /app/data /app/output /app/master_data

ENV PYTHON_ENV=production \
    TZ=America/Los_Angeles \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
