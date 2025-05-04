FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NYAI_ENV=production \
    # More conservative default Gunicorn settings for better memory usage
    GUNICORN_CMD_ARGS="--workers=3 --threads=2 --timeout=60 --worker-class=gthread --max-requests=800 --max-requests-jitter=50"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create and configure directories for the non-root user
RUN mkdir -p /app/logs /app/instance /app/instance/sessions /app/db \
    && chmod -R 777 /app/logs /app/instance /app/instance/sessions /app/db \
    && touch /app/logs/nyai_api.log \
    && chmod 666 /app/logs/nyai_api.log

# Create non-root user for security
RUN adduser --disabled-password --gecos "" nyai
USER nyai

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Run script that handles PORT environment variable
COPY --chown=nyai:nyai ./start.sh .
RUN chmod +x ./start.sh

# Use start script to handle PORT environment variable
CMD ["./start.sh"]

# Default port (Railway will override this with their PORT env var)
EXPOSE 8080 