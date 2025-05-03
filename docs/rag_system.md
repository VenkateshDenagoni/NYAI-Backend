# RAG System Documentation

## Overview

The Retrieval Augmented Generation (RAG) system enhances AI responses by retrieving relevant information from a knowledge base before generating answers. This approach grounds the AI's responses in factual information, reducing hallucinations and improving accuracy.

## Architecture

The RAG system follows a modular architecture with these key components:

### 1. Knowledge Preparation

- **Data Ingestion**: CSV files containing legal documents are loaded from the `knowledge_base` directory
- **Text Chunking**: Documents are split into manageable chunks (500 tokens) with overlap (100 tokens)
- **Embedding Generation**: Each chunk is converted into a vector using the `all-MiniLM-L6-v2` model
- **Vector Storage**: Embeddings are indexed in ChromaDB for efficient semantic search

### 2. Query Processing

- **Query Embedding**: User questions are embedded using the same model
- **Semantic Retrieval**: ChromaDB finds the most semantically similar document chunks
- **Fallback Mechanism**: If vector search fails, keyword-based search is used as a backup

### 3. Context Assembly

- **System Prompt**: Defines the AI's behavior and response style
- **Retrieved Context**: Top relevant document chunks are formatted with source citations
- **User Query**: The original question is included in the final prompt

### 4. LLM Invocation

- **API Call**: The assembled prompt is sent to the Gemini model with appropriate parameters
- **Response Generation**: The model generates a response grounded in the retrieved context

## Components

### RAG Document Service

The `RAGDocumentService` handles:

- Loading and processing documents from CSV files
- Generating and storing vector embeddings in ChromaDB
- Performing semantic search to retrieve relevant context
- Providing fallback keyword search when vector search is unavailable

### RAG AI Service

The `RAGAIService` handles:

- Validating and preprocessing user queries
- Assembling prompts with system instructions and retrieved context
- Calling the LLM API with appropriate parameters
- Caching responses for improved performance

### Utility Functions

The `rag_utils.py` module provides:

- Text cleaning and normalization
- Document chunking with configurable overlap
- CSV preprocessing for RAG
- Query expansion for improved retrieval

## API Endpoints

### POST /api/rag/query

Generates an AI response using the RAG system.

**Request:**

```json
{
  "query": "What are the fundamental rights in the Indian Constitution?"
}
```

**Response:**

```json
{
  "response": "The fundamental rights in the Indian Constitution are...",
  "processing_time": 1.25,
  "request_id": "abc123"
}
```

### GET /api/rag/status

Returns the status of the RAG system components.

**Response:**

```json
{
  "status": "healthy",
  "components": {
    "chromadb": "healthy",
    "embedding_function": "healthy"
  },
  "documents": {
    "count": 1250
  },
  "version": "1.0.0"
}
```

## Best Practices

### Chunking Strategy

- Use 500-token chunks with 100-token overlap for optimal retrieval
- Balance chunk size against retrieval accuracy and latency

### Prompt Engineering

- Keep system prompts concise and domain-specific
- Format retrieved context with clear source citations
- Use a consistent structure for assembled prompts

### Fallback Mechanisms

- Implement keyword search as a backup for vector search
- Cache responses to handle service disruptions
- Log errors and monitor system performance

## Monitoring

The RAG system includes:

- Detailed logging of processing times and errors
- Health check endpoint for system status
- Performance metrics for retrieval and generation

## Future Improvements

- Implement query rewriting for better retrieval
- Add support for multi-modal documents
- Enhance context ranking with re-ranking models
- Implement user feedback mechanisms for continuous improvement
