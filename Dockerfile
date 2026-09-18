# =============================================================================
# GridWise Production Dockerfile
# BUP CSE Fest 2026 Microgrid Optimization Service
# =============================================================================
FROM python:3.11-slim

WORKDIR /app

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source
COPY app/ ./app/

# Copy pre-compiled static frontend demo assets
COPY static/ ./static/

# Expose HTTP port (default 8000, dynamically overridable by cloud platforms)
EXPOSE 8000

# Container healthcheck ensuring GET /health responds
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.getenv('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health')" || exit 1

# Start uvicorn supporting dynamic $PORT from Render, Railway, Fly.io, etc.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]