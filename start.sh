#!/bin/bash
# This script ensures the application binds to the PORT provided by Railway
# and performs necessary checks before starting the application

# Enable verbose mode for debugging
set -x

# Get PORT from environment or default to 8080
PORT="${PORT:-8080}"

echo "Starting NYAI on port $PORT..."

# Check directory permissions
echo "Checking directory permissions..."
ls -la /app

# Ensure db directory is accessible
mkdir -p /app/db || echo "Warning: Could not create /app/db - may already exist"
touch /app/db/test_file.txt || echo "Warning: Permission issue with /app/db"
ls -la /app/db

# Check if we're in a containerized environment
if [ -n "$RAILWAY_STATIC_URL" ] || [ -n "$RAILWAY_SERVICE_ID" ] || [ -n "$RAILWAY_PROJECT_ID" ]; then
  echo "Detected Railway environment"
  
  # Force console-only logging in Railway (avoid file permission issues)
  export LOG_TO_CONSOLE=true
  
  # Optimize for Railway's memory constraints
  # Reduce worker count but maintain functionality
  export GUNICORN_CMD_ARGS="--workers=1 --threads=1 --timeout=90 --max-requests=300 --max-requests-jitter=50 --worker-class=gthread --log-level=debug"
  echo "Optimized worker configuration for Railway environment"
  
  # Set a very high error threshold for ChromaDB to prevent failures
  export CHROMA_ERROR_THRESHOLD=100
  
  # Force garbage collection to free memory
  echo "Running initial garbage collection"
  python -c "import gc; gc.collect()"
  
  # Disable ChromaDB to save memory - uncomment this line to save memory
  export USE_CHROMADB=false
  echo "ChromaDB disabled to save memory"
fi

# Make sure health endpoint is available
echo "Setting up Flask environment for production"
export FLASK_ENV=production
export NYAI_ENV=production

# Test if Python can import the app
echo "Testing Flask app import..."
python -c "from src.app import app; print('App imported successfully')" || echo "Warning: Failed to import app"

# Run the Gunicorn server with proper logging
echo "Starting Gunicorn server..."
exec gunicorn --bind "0.0.0.0:$PORT" "src.app:app" --log-level=debug 