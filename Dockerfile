FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better cache utilization
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/db/chroma_rag
RUN mkdir -p /app/logs

# Set environment variable for production
ENV NYAI_ENV=production
ENV PORT=8080
ENV HOST=0.0.0.0
ENV DEBUG=False

# Railway-specific environment variable to enable garbage collection
ENV RAILWAY_SERVICE_ID=nyai-backend

# Expose the port
EXPOSE 8080

# Run the application with Gunicorn for production
CMD gunicorn --bind $HOST:$PORT --workers 2 --threads 4 "src.app:app" 