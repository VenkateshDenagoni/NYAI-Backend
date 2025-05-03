#!/bin/bash
# Simple deployment script for NYAI

# Stop any existing container
echo "Stopping any existing NYAI container..."
docker stop nyai-legal 2>/dev/null || true
docker rm nyai-legal 2>/dev/null || true

# Build the Docker image
echo "Building Docker image..."
docker build -t nyai-legal:latest .

# Check if .env.production exists
if [ ! -f .env.production ]; then
    echo "ERROR: .env.production file not found!"
    echo "Please create .env.production with your configuration settings."
    exit 1
fi

# Check if Gemini API key is set
if grep -q "your_gemini_api_key_here" .env.production; then
    echo "WARNING: You need to set your Google Gemini API key in .env.production!"
    echo "Replace 'your_gemini_api_key_here' with your actual API key."
    exit 1
fi

# Run the container
echo "Starting NYAI container..."
docker run -d \
    --name nyai-legal \
    --restart unless-stopped \
    -p 8080:8080 \
    --env-file .env.production \
    nyai-legal:latest

# Check if container is running
if [ "$(docker ps -q -f name=nyai-legal)" ]; then
    echo "✅ NYAI is now running on http://localhost:8080"
    echo "Check logs with: docker logs nyai-legal"
else
    echo "❌ Failed to start NYAI container. Check logs with: docker logs nyai-legal"
    exit 1
fi 