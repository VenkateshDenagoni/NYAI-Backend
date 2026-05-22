# NyAI - Multilingual Legal AI Assistant

## Project Overview

NyAI is an AI-powered legal assistance platform focused on providing accurate legal insights for the Indian legal system in multiple Indian languages.

## Features

- **Legal Domain Expertise**: Specialized in Indian legal matters including consumer rights, property laws, business compliance, and more
- **Multilingual Support**: Fully supports English, Hindi, Tamil, Telugu, Marathi, and Bengali
- **Contextual Responses**: Remembers conversation history to provide relevant, personalized assistance
- **RAG Architecture**: Uses Retrieval-Augmented Generation for accurate legal information
- **Production-Ready**: Includes error handling, rate limiting, and safety features

## Setup Instructions

### Local Development

1. Clone the repository
2. Create virtual environment: `python -m venv venv`
3. Activate the environment:
   - Windows: `venv\Scripts\activate`
   - Linux/Mac: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and configure:
   ```
   GOOGLE_API_KEY=your_gemini_api_key
   NYAI_ENV=development  # or production
   ```
6. Run the application: `python run.py`

### Docker Deployment

Build and run the application using Docker:

```bash
docker build -t nyai-legal .
docker run -p 8080:8080 -e GOOGLE_API_KEY=your_key nyai-legal
```

### Railway Deployment

For deploying to Railway:

1. Follow the instructions in [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md)
2. **IMPORTANT**: Never commit API keys or secrets to GitHub
3. Use Railway's environment variables for sensitive information

## API Routes

### Base Routes
- `GET /health`: Health check endpoint

### RAG Routes
- `POST /api/rag/query`: Main endpoint for conversational responses
- `GET /api/rag/status`: System status information
- `DELETE /api/rag/sessions/<session_id>`: Delete a specific conversation session
- `DELETE /api/rag/sessions`: Delete all conversation sessions
- `POST /api/rag/feedback`: Submit feedback on responses

## Technologies

- **Backend**: Flask, Python 3.11+
- **AI**: Google Gemini Pro (LLM)
- **Vector Search**: ChromaDB with SentenceTransformer embeddings
- **Caching**: Redis (optional)
- **Containerization**: Docker
- **Deployment**: Railway-ready

## Language Support

NyAI supports the following languages:

- English (eng_Latn)
- Hindi (hin_Deva)
- Tamil (tam_Taml)
- Telugu (tel_Telu)
- Marathi (mar_Deva)
- Bengali (ben_Beng)

The assistant automatically detects the language of user queries and responds in the same language. It can also adapt to language changes mid-conversation.

## Security Best Practices

1. **API Keys**: Never commit API keys to Git
2. **Environment Variables**: Store sensitive information as environment variables
3. **Authentication**: Enable API authentication in production
4. **Deployment**: Follow security recommendations in deployment guides

## Contributors

D. Venkatesh
D. Prashanth
K. Kalyan
J. Vagdevi
Ch. Anusha
