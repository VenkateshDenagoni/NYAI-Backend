# NYAI Backend - Railway Deployment Guide

This guide provides step-by-step instructions to deploy the NYAI Backend to Railway directly from GitHub.

## Prerequisites

1. GitHub account with the NYAI Backend repository
2. Railway account ([sign up here](https://railway.app/))
3. Google Gemini API key ([get one here](https://aistudio.google.com/))

## Deployment Steps

### 1. Fork the Repository (if needed)

If you don't own the repository, fork it to your GitHub account.

### 2. Connect to Railway

1. Log in to [Railway](https://railway.app/)
2. Click "New Project" > "Deploy from GitHub repo"
3. Select the NYAI Backend repository
4. Railway will automatically detect the project configuration

### 3. Configure Environment Variables

In the Railway dashboard for your project:

1. Go to the "Variables" tab
2. Add the following environment variables:

```
GOOGLE_API_KEY=your_gemini_api_key_here
SECRET_KEY=your_secure_random_string
NYAI_ENV=production
PORT=8080
HOST=0.0.0.0
DEBUG=False
AUTH_REQUIRED=True
```

Generate a secure SECRET_KEY with: `openssl rand -hex 32` or any random string generator.

### 4. Configure Persistent Storage

The application requires persistent storage for the knowledge base and vector database:

1. Go to the "Volumes" tab
2. Create two volumes:
   - Name: `knowledge_base`, Mount Path: `/app/knowledge_base`
   - Name: `db`, Mount Path: `/app/db`

### 5. Deploy the Application

1. Go to the "Settings" tab
2. Click "Generate Domain" to get a public URL for your app
3. Railway will automatically deploy the application

### 6. Upload Knowledge Base Data

You need to upload your knowledge base files to the persistent volume. There are two ways to do this:

#### Option 1: Use Railway CLI

1. Install Railway CLI: `npm i -g @railway/cli`
2. Login: `railway login`
3. Link to your project: `railway link`
4. Upload CSV files: `railway upload /path/to/your/knowledge_base/*.csv /app/knowledge_base/`

#### Option 2: Use Docker and Railway Volumes

1. In the Railway dashboard, go to Volumes and find the volume ID
2. Use a custom container to copy files to the volume (using Railway's documentation)

### 7. Verify Deployment

1. Once deployed, open the generated Railway URL
2. Add `/health` to the URL to check the API status
3. You should see a JSON response showing components health status

## Troubleshooting

### API Key Issues

#### Google Gemini API Key (CRITICAL)
The GOOGLE_API_KEY is absolutely required for the application to function:
- The application will fail to start or respond to queries without a valid Google Gemini API key
- Obtain a key from [Google AI Studio](https://aistudio.google.com/)
- Ensure your API key has access to the Gemini model (gemini-2.0-flash-001)
- Set this as an environment variable in Railway

#### Authentication API Key
If you're seeing authentication errors with API requests:
- Verify API_KEY is set in Railway environment variables 
- Ensure your client is sending the API key in the X-API-Key header
- Check that ENABLE_AUTH is set to "true" if you want authentication

### Volume Issues

If the RAG system doesn't find documents:
- Check that the knowledge base volume is mounted correctly
- Verify CSV files are uploaded to the correct path

### Performance Issues

If the app is slow or crashes:
- Adjust workers and threads in the Dockerfile or railway.toml
- Consider upgrading your Railway instance for more resources

## Monitoring and Maintenance

- Railway provides logs and metrics under the "Metrics" tab
- Use `/health` endpoint to check system status
- Check application logs for any errors

## Scaling

To handle more traffic:
1. Go to "Settings" > "Resources"
2. Increase CPU and memory allocation
3. Adjust workers in the Dockerfile or railway.toml

## Final Notes

- The application uses lazy loading for embeddings and ChromaDB
- First requests may be slower as the system initializes
- Changes pushed to the connected GitHub repository will trigger automatic redeployments 