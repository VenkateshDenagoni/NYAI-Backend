# NYAI Deployment Guide

This guide will help you deploy the NYAI project with minimal effort, even if you have no prior deployment experience.

## Prerequisites

1. **Docker**: Install Docker on your system
   - Windows/Mac: Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop)
   - Linux: Follow the [installation instructions](https://docs.docker.com/engine/install/) for your distribution

2. **Google Gemini API Key**: 
   - Visit [Google AI Studio](https://aistudio.google.com/)
   - Sign up/login with your Google account
   - Go to the API keys section
   - Create a new API key

## Deployment Steps

### 1. Prepare Your Environment File

1. Locate the `.env.production` file in your project directory
2. Open it in any text editor
3. Replace `your_gemini_api_key_here` with your actual Google Gemini API key
4. Replace `change_this_to_a_secure_random_string` with a random string for security
   - You can generate one by running this command: `openssl rand -hex 32`

### 2. Run the Deployment Script

#### On Windows:

1. Open Command Prompt or PowerShell
2. Navigate to your project directory:
   ```
   cd path\to\nyai-backend
   ```
3. Run the deployment:
   ```
   docker build -t nyai-legal:latest .
   docker run -d --name nyai-legal --restart unless-stopped -p 8080:8080 --env-file .env.production nyai-legal:latest
   ```

#### On Mac/Linux:

1. Open Terminal
2. Navigate to your project directory:
   ```
   cd path/to/nyai-backend
   ```
3. Make the deployment script executable:
   ```
   chmod +x deploy.sh
   ```
4. Run the deployment script:
   ```
   ./deploy.sh
   ```

### 3. Verify Deployment

1. Open your web browser
2. Go to: `http://localhost:8080/health`
3. You should see a JSON response with system status information
4. If you see this response, your application is running successfully!

## Troubleshooting

### Docker Issues

- **Docker not running**: Make sure Docker Desktop (or Docker service on Linux) is running
- **Port already in use**: If port 8080 is already taken, modify the deployment script to use a different port (e.g., 8081)
- **Container not starting**: Check the logs with `docker logs nyai-legal`

### API Issues

- **Invalid API Key**: Ensure your Gemini API key is entered correctly in `.env.production`
- **API Quotas**: Google Gemini has usage limits; if you exceed them, the application will show errors

### Server Access

- **Local access only**: The default deployment only allows access from your computer
- **Network access**: To allow access from other devices on your network, you need to configure your firewall

## Cleanup

To stop the application:
```
docker stop nyai-legal
```

To remove the container:
```
docker rm nyai-legal
```

To remove the image:
```
docker rmi nyai-legal:latest
``` 