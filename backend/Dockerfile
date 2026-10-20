FROM python:3.11-slim

WORKDIR /app

# System deps for pdf2image (poppler) and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Copy source
COPY . .

# Create storage dirs and use the same unprivileged runtime identity as the
# canonical production image. Compose may still override CMD with --reload.
RUN groupadd --gid 10001 docagent \
    && useradd --uid 10001 --gid 10001 --create-home \
        --shell /usr/sbin/nologin docagent \
    && mkdir -p storage/uploads storage/outputs storage/schemas/clients \
    && chown -R docagent:docagent storage

EXPOSE 8000

USER docagent

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
