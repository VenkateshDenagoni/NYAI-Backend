FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create data directories
RUN mkdir -p /app/data/knowledge_base /app/logs

# Copy knowledge base files (do this early for better caching)
COPY knowledge_base/*.csv /app/data/knowledge_base/

# Copy startup script and make it executable
COPY startup.sh .
RUN chmod +x startup.sh

# Copy application code
COPY . .

# Set environment variables
ENV NYAI_ENV=production \
    PORT=8080 \
    HOST=0.0.0.0 \
    DEBUG=False \
    STATELESS_MODE=true \
    LOG_TO_CONSOLE=true \
    KNOWLEDGE_BASE_DIR=/app/data/knowledge_base \
    RAILWAY_SERVICE_ID=nyai_backend_simplified

# Expose port
EXPOSE 8080

# Start the application using our startup script
CMD ["./startup.sh"] 