# NYAI Backend Deployment on Railway

This document provides comprehensive information for deploying the NYAI Backend application on Railway, a modern PaaS (Platform as a Service) that simplifies the deployment process.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deployment Files](#deployment-files)
- [Quick Start](#quick-start)
- [Step-by-Step Deployment Guide](#step-by-step-deployment-guide)
- [Environment Variables](#environment-variables)
- [Persistent Storage](#persistent-storage)
- [Monitoring and Scaling](#monitoring-and-scaling)
- [Deployment Scripts](#deployment-scripts)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

## Prerequisites

Before deploying to Railway, ensure you have:

1. A GitHub account with your NYAI Backend repository
2. A Railway account (sign up at [railway.app](https://railway.app))
3. Knowledge base files prepared for deployment
4. Python 3.8+ (for running local preparation scripts)

## Deployment Files

The following files are essential for Railway deployment:

- `Dockerfile` - Container definition for the application
- `railway.toml` - Railway-specific configuration
- `.dockerignore` - Specifies files to exclude from the container
- `.env.production` - Environment variables for production (don't commit secrets)
- `RAILWAY_DEPLOYMENT.md` - Detailed deployment guide

## Quick Start

For a quick deployment, follow these steps:

1. Run the preparation script:
   ```bash
   python scripts/update_for_railway.py
   ```

2. Push your code to GitHub:
   ```bash
   git push origin main
   ```

3. Connect your GitHub repository to Railway

4. Create a new service and select your repository

5. Add persistent volumes according to railway.toml:
   - One mounted at `/app/knowledge_base` for knowledge base files
   - One mounted at `/app/db` for the database files

6. Set required environment variables (see [Environment Variables](#environment-variables))

7. Deploy your application

8. Verify deployment:
   ```bash
   python scripts/check_deployment.py --url https://your-app-url.railway.app
   ```

## Step-by-Step Deployment Guide

### 1. Prepare Your Repository

Before deploying to Railway, ensure your repository has all the necessary deployment files:

```bash
# Clone the repository (if you haven't already)
git clone https://github.com/yourusername/nyai-backend.git
cd nyai-backend

# Run the preparation script
python scripts/update_for_railway.py
```

This script will:
- Check for required deployment files
- Update the `.env.production` file with Railway-compatible settings
- Ensure your knowledge base is prepared for deployment
- Offer to commit and push changes to GitHub

### 2. Connect to Railway

1. Sign in to [Railway Dashboard](https://railway.app/dashboard)
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose your NYAI Backend repository
5. Railway will automatically detect the Dockerfile and build your application

### 3. Configure Environment Variables

1. In your Railway project, click on your service
2. Navigate to the "Variables" tab
3. Add required environment variables (see [Environment Variables](#environment-variables))
4. Click "Deploy" to apply changes

### 4. Add Persistent Storage

1. In your Railway project, click on "New"
2. Select "Add Volume"
3. Set the mount path to `/app/knowledge_base` for knowledge base files
4. Set an appropriate size for your needs (start with at least 1GB)
5. Repeat to add another volume mounted at `/app/db` for database files
6. Click "Add Volume"

### 5. Verify Deployment

1. Wait for deployment to complete
2. Run the verification script:
   ```bash
   python scripts/check_deployment.py --url https://your-app-url.railway.app
   ```
3. Test the application with sample queries

## Environment Variables

The following environment variables are required:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| API_KEY | Authentication key for API access | Yes | - |
| PORT | Application port (provided by Railway) | No | Set by Railway |
| FLASK_ENV | Flask environment | No | production |
| LOG_LEVEL | Logging level | No | INFO |
| KNOWLEDGE_BASE_DIR | Path to knowledge base | No | /app/knowledge_base |
| VECTOR_DB_PATH | Path to vector database | No | /app/db/chroma_rag |
| SESSION_DB_PATH | Path to session database | No | /app/instance/sessions |
| ENABLE_AUTH | Enable API key authentication | No | true |
| CORS_ORIGINS | Allowed CORS origins | No | * |

## Persistent Storage

Railway provides persistent volumes that can be mounted in your container. For NYAI Backend, we mount volumes at:

- `/app/knowledge_base` - For knowledge base files
- `/app/db` - For vector database and ChromaDB files

These volumes persist across deployments and restarts, ensuring data durability.

## Monitoring and Scaling

### Monitoring

Railway provides basic monitoring capabilities:

1. Navigate to your service in the Railway dashboard
2. Click on the "Metrics" tab to view:
   - CPU usage
   - Memory usage
   - Disk usage
   - Network I/O

For more detailed monitoring, consider integrating with:
- Prometheus for metrics collection
- Grafana for visualization
- Sentry for error tracking

### Scaling

To scale your application on Railway:

1. Navigate to your service in the Railway dashboard
2. Click on "Settings"
3. Adjust resources as needed:
   - CPU
   - Memory
   - Disk space

## Deployment Scripts

The repository includes several scripts to facilitate deployment:

1. `scripts/update_for_railway.py` - Prepares your repository for Railway deployment
2. `scripts/prepare_for_railway.py` - Optimizes knowledge base files for deployment
3. `scripts/check_deployment.py` - Verifies deployment status and health

### Usage Examples

```bash
# Update environment and prepare for deployment
python scripts/update_for_railway.py

# Prepare knowledge base files
python scripts/prepare_for_railway.py

# Check deployment (basic)
python scripts/check_deployment.py --url https://your-app-url.railway.app

# Check deployment (with authentication)
python scripts/check_deployment.py --url https://your-app-url.railway.app --api-key YOUR_API_KEY

# Monitor deployment startup (check every 30 seconds, maximum 20 checks)
python scripts/check_deployment.py --url https://your-app-url.railway.app --check-interval 30 --max-checks 20
```

## Troubleshooting

### Common Issues

#### Application Fails to Start

**Symptoms**:
- Railway shows deployment failed
- Logs show application crash during startup

**Solutions**:
1. Check Railway logs for error messages
2. Verify environment variables are correctly set
3. Ensure persistent volumes are mounted at `/app/knowledge_base` and `/app/db`
4. Check if knowledge base files are available

#### Memory Issues

**Symptoms**:
- Application crashes under load
- Out of memory errors in logs

**Solutions**:
1. Increase memory allocation in Railway settings
2. Optimize knowledge base files using `scripts/prepare_for_railway.py`
3. Adjust application configuration to use less memory

#### API Authentication Failures

**Symptoms**:
- API requests return 401 Unauthorized
- Cannot access protected endpoints

**Solutions**:
1. Verify API_KEY is set in Railway environment variables
2. Ensure client is sending API key in X-API-Key header
3. Check if ENABLE_AUTH is set to "true"

### Getting Help

If you encounter issues not covered here:

1. Check the Railway logs for error messages
2. Review the [NYAI Backend documentation](./docs/)
3. Open an issue on the GitHub repository

## FAQ

**Q: How much does it cost to run on Railway?**
A: Railway offers various pricing tiers. The NYAI Backend typically requires at least the Hobby tier with added storage depending on your knowledge base size.

**Q: Can I use my own domain name?**
A: Yes. Railway allows custom domains. Navigate to your service settings to configure a custom domain.

**Q: How do I update my deployment?**
A: Simply push changes to your connected GitHub repository. Railway will automatically rebuild and deploy.

**Q: How do I rollback to a previous version?**
A: In the Railway dashboard, navigate to your deployment history and select a previous deployment to restore.

**Q: Can I schedule automatic backups?**
A: Railway doesn't provide built-in scheduled backups. Consider implementing a custom backup solution using GitHub Actions or a separate scheduled task.

---

For more detailed information, please refer to the [RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md) file and [Railway Documentation](https://docs.railway.app/). 