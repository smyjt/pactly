FROM python:3.11-slim

WORKDIR /app

# System deps: build-essential for asyncpg compilation, mupdf for pymupdf
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

# Copy application code
COPY . .

# Uploads directory (also volume-mounted in compose)
RUN mkdir -p /app/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
