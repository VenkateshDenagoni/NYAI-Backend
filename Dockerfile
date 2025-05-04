FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NYAI_ENV=production \
    LOG_TO_CONSOLE=true \
    USE_CHROMADB=false \
    CHROMA_ERROR_THRESHOLD=100

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create required directories with proper permissions before any code is copied
RUN mkdir -p /app/logs /app/instance /app/instance/sessions /app/db/chroma \
    && chmod -R 777 /app/logs /app/instance /app/instance/sessions /app/db

# Copy requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create empty log file with proper permissions
RUN touch /app/logs/nyai_api.log && chmod 666 /app/logs/nyai_api.log

# Create non-root user and set ownership
RUN chown -R 1000:1000 /app/db /app/logs /app/instance \
    && adduser --disabled-password --gecos "" --uid 1000 nyai
USER nyai

# Simple health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Create a simplified startup script
RUN echo '#!/bin/bash' > /app/start_app.sh \
    && echo 'PORT="${PORT:-8080}"' >> /app/start_app.sh \
    && echo 'echo "Starting app on port $PORT with reduced feature set"' >> /app/start_app.sh \
    && echo 'exec gunicorn --workers=1 --threads=1 --timeout=120 --bind "0.0.0.0:$PORT" "src.app:app" --log-level=info' >> /app/start_app.sh \
    && chmod +x /app/start_app.sh

# Default port
EXPOSE 8080

# Run simplified startup script
CMD ["/app/start_app.sh"] 