#!/bin/bash
# This script ensures the application binds to the PORT provided by Railway
# and performs necessary checks before starting the application

# Get PORT from environment or default to 8080
PORT="${PORT:-8080}"

echo "Starting NYAI on port $PORT..."

# Check if we're in a containerized environment
if [ -n "$RAILWAY_STATIC_URL" ] || [ -n "$RAILWAY_SERVICE_ID" ] || [ -n "$RAILWAY_PROJECT_ID" ]; then
  echo "Detected Railway environment"
  
  # Force console-only logging in Railway (avoid file permission issues)
  export LOG_TO_CONSOLE=true
  
  # Check NLTK data access
  if [ -d "/app/nltk_data" ]; then
    echo "NLTK data directory exists at /app/nltk_data"
    # Set NLTK_DATA environment variable
    export NLTK_DATA=/app/nltk_data
  else
    echo "Warning: NLTK data directory not found. NLP features may be limited."
  fi
  
  # Set a very high error threshold for ChromaDB to prevent failures
  export CHROMA_ERROR_THRESHOLD=100
fi

# Run the Gunicorn server, binding to the specified port
exec gunicorn --bind "0.0.0.0:$PORT" "src.app:app" 