FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data

USER appuser
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/healthz')" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
