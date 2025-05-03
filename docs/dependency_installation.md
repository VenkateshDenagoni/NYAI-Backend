# Dependencies Installation Guide

This guide will help you install and configure the key dependencies required for NYAI.

## Prerequisites

- Python 3.8+ with pip
- Ability to install packages via pip and system package manager

## Required Libraries

### ChromaDB and Sentence Transformers

ChromaDB is used for vector search capabilities, allowing the system to find semantically similar documents beyond keyword matching.

```bash
# Install ChromaDB and its dependencies
pip install chromadb sentence-transformers
```

If you encounter errors with sentence-transformers, you may need additional system dependencies:

#### On Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y python3-dev
```

#### On Windows:

Make sure you have the latest Visual C++ Redistributable installed and the Microsoft Build Tools.

#### Verification

To verify that ChromaDB and sentence-transformers are working:

```bash
python -c "import chromadb; from chromadb.utils import embedding_functions; print('ChromaDB works!')"
```

### Redis

Redis is used for caching responses, session management, and rate limiting. It's recommended for production use.

#### On Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

#### On macOS (using Homebrew):

```bash
brew install redis
brew services start redis
```

#### On Windows:

Download and install from [Redis Windows](https://github.com/microsoftarchive/redis/releases)

#### Verification

To verify Redis is running:

```bash
redis-cli ping
```

Should return: `PONG`

## Configuration

### Environment Variables

Create a `.env` file in the root directory with:

```
GOOGLE_API_KEY=your_google_api_key
REDIS_URL=redis://localhost:6379/0
NYAI_ENV=development
```

## Fallback Behavior

The application will work with minimal dependencies, with the following fallbacks:

1. Without Redis: Uses in-memory storage for caching and sessions
2. Without ChromaDB/sentence-transformers: Uses keyword-based search only

## Health Check

After installation, visit `/health` endpoint to verify all dependencies are working properly.
