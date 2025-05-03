# Deploying NYAI on Railway

This guide will walk you through deploying your NYAI project on [Railway](https://railway.app/), a modern platform that makes deployment simple.

## Prerequisites

1. **GitHub Account**: Make sure you have a GitHub account
2. **Railway Account**: Sign up for a free account on [Railway](https://railway.app/) (you can sign up with your GitHub account)
3. **Google Gemini API Key**: Get your API key from [Google AI Studio](https://aistudio.google.com/)

## Preparation Steps

### 1. Create a GitHub Repository

1. Create a new private GitHub repository
2. Push your NYAI project to this repository:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```

### 2. Set Up Your Environment Variables

IMPORTANT: For security reasons, we DO NOT store actual API keys in the repository. Instead:

1. Copy `.env.example` to create a new file called `.env.production` (this file should NOT be committed to Git)
2. In your local `.env.production` file, update:
   - Your actual Google Gemini API key
   - A secure random string for SECRET_KEY

3. These sensitive values should ONLY be set in the Railway dashboard, not in files committed to your repository.

## Deployment Steps

### 1. Create a New Project on Railway

1. Log in to [Railway Dashboard](https://railway.app/dashboard)
2. Click "New Project"
3. Choose "Deploy from GitHub repo"
4. Select your GitHub repository with the NYAI project
5. Choose the main branch

### 2. Configure Environment Variables in Railway (IMPORTANT)

1. After creating the project, go to the "Variables" tab
2. Add these environment variables:
   - `GOOGLE_API_KEY`: Your Google Gemini API key
   - `SECRET_KEY`: A secure random string
   - `NYAI_ENV`: production
   - `AUTH_REQUIRED`: true or false (depending on if you want API authentication)
   - `FLASK_APP`: src/app.py
   - `FLASK_ENV`: production
   - `DEBUG`: False

   Note: Railway will automatically set the PORT variable for you.

### 3. Monitor Deployment

1. Go to the "Deployments" tab
2. You'll see your application building and deploying
3. Railway will automatically detect your Dockerfile and build using it

### 4. Access Your Application

1. Once deployment completes, click on the "Settings" tab
2. Find your app's URL in the "Domains" section
3. Open this URL and add `/health` to check if your app is running
   - Example: `https://your-app-name.railway.app/health`

## Troubleshooting

### Deployment Failures

If your deployment fails:
1. Check the build logs in the "Deployments" tab
2. Make sure all your environment variables are set correctly in Railway
3. Verify your Dockerfile is valid

### API or Database Issues

1. Check the logs in the "Deployments" tab
2. Consider adding a Redis service to your project for better performance:
   - Click "New" → "Database" → "Redis"
   - Railway will automatically link it to your application

### Knowledge Base Issues

1. Make sure your knowledge base CSV files are correctly committed to your GitHub repository
2. Check that the files are in the `knowledge_base` directory
3. Verify the files are properly formatted

## Scaling Your Application

Railway's free tier is sufficient for a college project demonstration. If you need more resources:

1. Go to "Project Settings" → "Usage"
2. Adjust the resource limits (note: this may incur charges)

## Updating Your Application

To update your deployed application:

1. Make changes to your code
2. Commit and push to GitHub:
   ```bash
   git add .
   git commit -m "Update app"
   git push
   ```
3. Railway will automatically detect changes and redeploy

## Security Best Practices

1. NEVER commit API keys, secrets, or passwords to your GitHub repository
2. Always use Railway's environment variables for sensitive information
3. Keep your repository private
4. Regularly rotate your API keys and secrets

## Important Railway Features

1. **Metrics**: View your application's CPU, memory, and network usage
2. **Logs**: Access application logs for debugging
3. **Variables**: Manage environment variables securely
4. **Custom Domains**: Connect your own domain if needed (premium feature)

## Railway Limitations (Free Tier)

- **Usage**: Railway provides $5 of free credits per month
- **Sleeping**: Projects on the free tier may sleep after inactivity
- **Limits**: There are limits on compute, storage, and bandwidth 