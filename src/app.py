from flask import Flask
from flask_cors import CORS
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging
from werkzeug.middleware.dispatcher import DispatcherMiddleware
import gc
import os
from pathlib import Path

try:
    from prometheus_client import make_wsgi_app
    prometheus_available = True
except ImportError:
    prometheus_available = False

from src.routes.rag_routes import rag_routes
from src.utils.errors import register_error_handlers
from src.middleware import request_middleware
from src.config import config
from src.utils.logger import logger

# Initialize simple in-memory cache
cache = Cache(config={'CACHE_TYPE': 'SimpleCache'})

# Configure rate limiter with memory storage
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri="memory://"
)

def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(config)
    
    # Use in-memory implementations instead of Redis
    app.config['CACHE_TYPE'] = 'SimpleCache'
    app.config['SESSION_TYPE'] = 'null'  # Disable sessions completely
    
    # Initialize extensions
    CORS(app)
    cache.init_app(app)
    limiter.init_app(app)
    
    # Register error handlers
    register_error_handlers(app)
    
    # Apply middleware
    request_middleware()(app)
    
    # Register blueprints
    app.register_blueprint(rag_routes)  # RAG routes already have /api/rag prefix
    
    # Add health check endpoint
    @app.route("/health")
    def health_check():
        # Check ChromaDB status from document service
        from src.services.document_service import document_service
        chroma_status = "healthy" if document_service.chroma_client else "unavailable (using keyword search only)"
        
        # Check embedding function status
        embedding_status = "healthy" if document_service.embedding_function else "unavailable (vector search disabled)"
        
        # Check RAG service status
        try:
            from src.services.rag_document_service_improved import rag_document_service
            from src.services.rag_ai_service_improved import rag_ai_service
            rag_status = "healthy" if rag_document_service and rag_ai_service else "unavailable"
        except Exception as e:
            rag_status = f"error: {str(e)}"
        
        return {
            "status": "healthy",
            "dependencies": {
                "chromadb": chroma_status,
                "embedding_function": embedding_status,
                "rag_service": rag_status
            },
            "version": config.VERSION
        }
    
    # Add metrics endpoint if prometheus is available
    if prometheus_available:
        app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
            '/metrics': make_wsgi_app()
        })
    
    # Memory optimization for Railway
    if os.environ.get("RAILWAY_SERVICE_ID"):
        # Force garbage collection after initialization to free memory
        gc.collect()
        app.logger.info("Forced garbage collection for Railway deployment")
    
    return app

# Create the app instance
app = create_app()

if __name__ == "__main__":
    app.run(port=5000, debug=True)
