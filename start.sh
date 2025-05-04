#!/bin/bash
# Simple script to start the application with Gunicorn

# Get PORT from environment or default to 8080
PORT="${PORT:-8080}"

echo "Starting application on port $PORT..."

# Set environment variables
export FLASK_ENV=production
export NYAI_ENV=production
export LOG_TO_CONSOLE=true
export USE_CHROMADB=false

# Create required directories
mkdir -p /app/logs /app/db /app/instance

# Run the application
exec gunicorn --bind "0.0.0.0:$PORT" "src.app:app" \
  --workers=1 \
  --threads=2 \
  --timeout=90 \
  --log-level=debug \
  --access-logfile=- \
  --error-logfile=- 