# NYAI Backend Deployment on Railway

This document provides detailed technical information about the stateless deployment approach for the NYAI Backend on Railway.

## Stateless Architecture Overview

The NYAI Backend application has been redesigned to support a stateless deployment model that eliminates the need for persistent volumes on Railway. This approach:

1. Packages knowledge base files with the Docker image
2. Uses an in-memory ChromaDB database
3. Rebuilds the vector database on each deploy/restart

## Key Components

### 1. Dockerfile

The Dockerfile is configured to:
- Use Python 3.10 as the base image
- Copy knowledge base files into the image
- Set up environment variables for stateless operation
- Use a startup script to verify the knowledge base and perform garbage collection

Key sections in the Dockerfile:
```dockerfile
# Copy knowledge base files (do this early for better caching)
COPY knowledge_base/*.csv /app/data/knowledge_base/

# Set environment variables
ENV STATELESS_MODE=true
ENV KNOWLEDGE_BASE_DIR=/app/data/knowledge_base
```

### 2. ChromaDB Configuration

The RAG document service has been updated to support both stateless and persistent modes:

```python
def _initialize_chromadb(self):
    if self.stateless_mode:
        # Use in-memory ChromaDB for stateless mode
        self.chroma_client = chromadb.Client()
        logger.info("Initialized ChromaDB in stateless in-memory mode")
    else:
        # Use persistent ChromaDB
        self.chroma_client = chromadb.PersistentClient(path=self.vector_db_path)
        logger.info(f"Initialized ChromaDB with persistent storage at {self.vector_db_path}")
```

### 3. Railway Configuration

The `railway.toml` file has been simplified to remove persistent volumes:

```toml
[build]
builder = "NIXPACKS"
buildCommand = "echo Building NYAI Backend..."

[deploy]
startCommand = "gunicorn --bind $HOST:$PORT --workers 2 --threads 8 'src.app:app'"
healthcheckPath = "/health"
restartPolicyType = "ON_FAILURE"

[deploy.envVars]
NYAI_ENV = "production"
LOG_TO_CONSOLE = "true"
STATELESS_MODE = "true"
```

## Technical Details

### Knowledge Base Fallback Mechanism

The application implements a fallback mechanism for finding knowledge base files:

```python
# First try environment variable location
if Path(self.knowledge_base_dir).exists() and list(Path(self.knowledge_base_dir).glob("*.csv")):
    logger.info(f"Using knowledge base directory: {self.knowledge_base_dir}")
# Then try packaged location in Docker image
elif Path("/app/data/knowledge_base").exists() and list(Path("/app/data/knowledge_base").glob("*.csv")):
    self.knowledge_base_dir = "/app/data/knowledge_base"
    logger.info(f"Using packaged knowledge base at: {self.knowledge_base_dir}")
# Then try relative directory
elif Path("./knowledge_base").exists() and list(Path("./knowledge_base").glob("*.csv")):
    self.knowledge_base_dir = "./knowledge_base"
    logger.info(f"Using knowledge base at: {self.knowledge_base_dir}")
else:
    logger.warning("No valid knowledge base directory found after trying fallbacks")
```

### Startup Process

The startup script performs several important functions:
1. Verifies environment variables
2. Checks for knowledge base files
3. Performs garbage collection
4. Starts the application with the optimized parameters

```bash
# Verify knowledge base files
echo "Verifying knowledge base files..."
KB_DIR=${KNOWLEDGE_BASE_DIR:-/app/data/knowledge_base}
if [ -d "$KB_DIR" ]; then
    echo "Knowledge base directory found at: $KB_DIR"
    FILE_COUNT=$(find "$KB_DIR" -type f -name "*.csv" | wc -l)
    echo "Found $FILE_COUNT CSV files in knowledge base"
fi
```

### Memory Management

The application includes specific memory optimization for Railway:

1. Garbage collection is forced after initialization
2. The default worker count is reduced from 8 to 2
3. Thread count is increased from 4 to 8 for better resource usage

## Deployment Process

### Quick Deployment Steps

1. Ensure knowledge base CSV files are in the `knowledge_base/` directory
2. Push code to GitHub
3. Connect repository to Railway
4. Set required environment variables (especially `GOOGLE_API_KEY` and `API_KEY`)
5. Deploy

### Required Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| GOOGLE_API_KEY | Google Gemini API key | Yes |
| API_KEY | API authentication key | Yes |
| STATELESS_MODE | Set to "true" | No (default: true) |
| LOG_TO_CONSOLE | Set to "true" | No (default: true) |

## Monitoring and Debugging

### Health Check Endpoint

The application provides a `/health` endpoint that returns detailed information about the application status:

```json
{
  "status": "healthy",
  "mode": "stateless",
  "environment": "production",
  "dependencies": {
    "chromadb": "healthy",
    "embedding_function": "healthy",
    "rag_service": "healthy",
    "knowledge_base": "found 3 files at /app/data/knowledge_base"
  },
  "config": {
    "stateless_mode": true,
    "log_to_console": true,
    "auth_required": true
  },
  "version": "1.0.0"
}
```

### Logging

Logs are streamed to console and can be viewed in the Railway dashboard.

### Common Issues and Solutions

1. **Knowledge base files not found**
   - Verify `.dockerignore` does not exclude knowledge base files
   - Check Docker build logs to confirm files are copied
   - Check startup logs to confirm files are found

2. **ChromaDB errors**
   - If you see "embeddings_queue table already exists", this is a normal warning
   - In-memory ChromaDB will rebuild on each restart

3. **Slow first request**
   - The first request after deployment will be slower as it builds the vector database
   - Subsequent requests will be faster

## Performance Considerations

### Tradeoffs

The stateless approach has these tradeoffs:

**Advantages:**
- Simplified deployment (no volumes to manage)
- No risk of database corruption
- Easier to upgrade (just redeploy)
- Automatic self-healing on restart

**Disadvantages:**
- Longer cold start (rebuilding vector DB)
- Slightly higher memory usage
- Need to redeploy to update knowledge base

### Optimizations

1. Knowledge base files are copied early in the Dockerfile for better layer caching
2. Worker and thread counts are optimized for Railway resource limits
3. Garbage collection is performed at startup to free memory
4. ChromaDB is initialized only when needed (lazy loading)

## Future Improvements

Potential improvements for the stateless deployment:

1. Implement pre-built vector database packaging
2. Add support for knowledge base updates through API
3. Improve error recovery mechanisms
4. Add support for external vector database services

---

For simpler deployment instructions, see [README_RAILWAY.md](./README_RAILWAY.md).
