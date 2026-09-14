FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Two server processes, so one long request (a full rescore) doesn't hold
# up everyone else's pages.
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    WEB_CONCURRENCY=2

EXPOSE 8000

# Railway sets PORT. Proxy headers keep FastAPI's redirects on https.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips "*"
