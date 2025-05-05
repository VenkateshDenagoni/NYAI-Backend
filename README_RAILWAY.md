# NYAI Backend Deployment on Railway - Simplified Version

This document provides a streamlined guide for deploying the NYAI Backend application on Railway without persistent volumes for maximum simplicity.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deployment Files](#deployment-files)
- [Quick Start](#quick-start)
- [Step-by-Step Deployment Guide](#step-by-step-deployment-guide)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before deploying to Railway, ensure you have:

1. A GitHub account with your NYAI Backend repository
2. A Railway account (sign up at [railway.app](https://railway.app))
3. Google Gemini API key

## Deployment Files

The following files are essential for Railway deployment:

- `Dockerfile` - Container definition with knowledge base files included
- `railway.toml` - Railway-specific configuration (simplified)
- `.dockerignore` - Ensures knowledge base files are included in the build

## Quick Start

For a quick deployment, follow these steps:

1. Push your code to GitHub:
   ```bash
   git push origin main
   ```

2. Connect your GitHub repository to Railway

3. Create a new service and select your repository

4. Set required environment variables (see [Environment Variables](#environment-variables))

5. Deploy your application

## Step-by-Step Deployment Guide

### 1. Verify Your Repository Contains Knowledge Base Files

Make sure your repository includes the knowledge base CSV files in the `knowledge_base/` directory.

### 2. Connect to Railway

1. Sign in to [Railway Dashboard](https://railway.app/dashboard)
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose your NYAI Backend repository

### 3. Configure Environment Variables

1. In your Railway project, click on your service
2. Navigate to the "Variables" tab
3. Add required environment variables (see [Environment Variables](#environment-variables))
4. Click "Deploy" to apply changes

### 4. Verify Deployment

1. Wait for deployment to complete
2. Test the application with the `/health` endpoint

## Environment Variables

The following environment variables are required:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| GOOGLE_API_KEY | Google Gemini API key for LLM functionality | Yes | - |
| API_KEY | Authentication key for API access | Yes | - |
| STATELESS_MODE | Enable stateless mode (no persistent volumes) | No | true |
| LOG_TO_CONSOLE | Enable console logging | No | true |

Example environment variables setup in Railway:

```
GOOGLE_API_KEY=your_gemini_api_key_here
API_KEY=your_api_key_here
STATELESS_MODE=true
LOG_TO_CONSOLE=true
```

## Troubleshooting

### Common Issues

#### API Key Issues

**Symptoms**:
- Application not responding to queries
- Errors in logs about missing API key

**Solutions**:
1. Verify GOOGLE_API_KEY is set in Railway environment variables
2. Check API_KEY is set for authentication

#### Knowledge Base Files Not Found

**Symptoms**:
- Warning in logs: "No valid knowledge base directory found after trying fallbacks"
- RAG functionality not working properly

**Solutions**:
1. Check startup logs to confirm knowledge base files were found
2. Verify the Docker build included the knowledge base files
3. Make sure `.dockerignore` doesn't exclude knowledge base files

#### Performance Issues

**Symptoms**:
- Slow response times, especially after deployment or cold starts

**Solutions**:
1. First request after deployment will be slower as it builds the vector database
2. Subsequent requests should be faster

#### Health Check

If you encounter issues, check the health endpoint:
```
https://your-railway-url.app/health
```

This will show the status of all components, including ChromaDB and embedding function availability.

---

## Important Note

This deployment uses a **stateless approach** meaning:
- No persistent volumes are used
- Knowledge base files are packaged with the application
- ChromaDB runs in memory instead of with persistent storage
- The database is rebuilt on each deployment

This approach maximizes simplicity and reliability at the cost of:
- Slightly slower cold starts
- Need to redeploy to update knowledge base files

For most use cases, this simplicity is worth the tradeoff! 