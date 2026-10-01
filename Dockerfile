FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY app ./app
COPY db ./db
COPY examples ./examples
COPY scripts ./scripts

RUN mkdir -p /app/chroma_data /app/outputs /app/resume_uploads \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser

EXPOSE 8000

CMD ["/bin/sh", "-c", "python scripts/init_db.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
