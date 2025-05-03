#!/bin/bash
# This script ensures the application binds to the PORT provided by Railway

# Get PORT from environment or default to 8080
PORT="${PORT:-8080}"

echo "Starting NYAI on port $PORT..."

# Run the Gunicorn server, binding to the specified port
exec gunicorn --bind "0.0.0.0:$PORT" "src.app:app" 