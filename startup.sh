#!/bin/bash
set -e

echo "============================================="
echo "NYAI Backend - Stateless Mode Startup Script"
echo "============================================="

# Check environment variables
echo "Checking environment variables..."
if [ -z "$GOOGLE_API_KEY" ]; then
    echo "WARNING: GOOGLE_API_KEY is not set"
fi

if [ -z "$API_KEY" ]; then
    echo "WARNING: API_KEY is not set"
fi

# Verify knowledge base files
echo "Verifying knowledge base files..."
KB_DIR=${KNOWLEDGE_BASE_DIR:-/app/data/knowledge_base}

if [ -d "$KB_DIR" ]; then
    echo "Knowledge base directory found at: $KB_DIR"
    
    # Count and list files
    FILE_COUNT=$(find "$KB_DIR" -type f -name "*.csv" | wc -l)
    echo "Found $FILE_COUNT CSV files in knowledge base:"
    find "$KB_DIR" -type f -name "*.csv" -exec ls -lh {} \;
    
    if [ "$FILE_COUNT" -eq 0 ]; then
        echo "WARNING: No CSV files found in knowledge base directory!"
    fi
else
    echo "WARNING: Knowledge base directory not found at $KB_DIR"
    echo "Checking fallback directories..."
    
    # Check fallback directories
    for dir in "/app/knowledge_base" "./knowledge_base" "../knowledge_base"; do
        if [ -d "$dir" ]; then
            echo "Found fallback knowledge base at: $dir"
            FILE_COUNT=$(find "$dir" -type f -name "*.csv" | wc -l)
            echo "Found $FILE_COUNT CSV files in fallback directory"
            break
        fi
    done
fi

# Check if we're running in stateless mode
if [ "${STATELESS_MODE}" = "true" ]; then
    echo "Running in STATELESS MODE - using in-memory ChromaDB"
else
    echo "Running in PERSISTENT MODE - using disk-based ChromaDB"
fi

# Check if we're logging to console
if [ "${LOG_TO_CONSOLE}" = "true" ]; then
    echo "Console logging enabled"
fi

# Run garbage collection to clean memory before starting
echo "Running garbage collection..."
python -c "import gc; gc.collect()"

# Start the application
echo "Starting NYAI Backend application..."
exec gunicorn --bind ${HOST:-0.0.0.0}:${PORT:-8080} \
    --workers ${WORKERS:-2} \
    --threads ${THREADS:-4} \
    --timeout ${TIMEOUT:-120} \
    --log-level ${LOG_LEVEL:-info} \
    'src.app:app' 