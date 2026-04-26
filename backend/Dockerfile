FROM python:3.11-slim

WORKDIR /app

# System deps for pdf2image (poppler) and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create storage dirs
RUN mkdir -p storage/uploads storage/outputs storage/schemas/clients

EXPOSE 8000

# Use gunicorn in production, uvicorn in dev
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
