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
    
    # Validate and set Flask SECRET_KEY from environment (required for security)
    if not config.SECRET_KEY:
        raise ValueError(
            "SECRET_KEY environment variable is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    app.secret_key = config.SECRET_KEY
    
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
    
    # Setup logger
    if config.LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(config.LOG_LEVEL)
        formatter = logging.Formatter(config.LOG_FORMAT)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        logger.info("Console logging enabled")
    
    # Add root route
    @app.route("/")
    def index():
        return {
            "name": "NYAI Backend API",
            "version": config.VERSION,
            "status": "running",
            "endpoints": {
                "health": "/health",
                "rag_query": "/api/rag/query",
                "rag_status": "/api/rag/status"
            },
            "docs": "See README.md for API documentation"
        }
    
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
            
            # Check knowledge base status
            kb_path = rag_document_service.knowledge_base_dir
            kb_files = list(Path(kb_path).glob("*.csv")) if Path(kb_path).exists() else []
            kb_status = f"found {len(kb_files)} files at {kb_path}" if kb_files else f"no files found at {kb_path}"
        except Exception as e:
            rag_status = f"error: {str(e)}"
            kb_status = "error: could not check knowledge base"
        
        return {
            "status": "healthy",
            "mode": "stateless" if config.STATELESS_MODE else "persistent",
            "environment": os.getenv("NYAI_ENV", "development"),
            "dependencies": {
                "chromadb": chroma_status,
                "embedding_function": embedding_status,
                "rag_service": rag_status,
                "knowledge_base": kb_status
            },
            "config": {
                "stateless_mode": config.STATELESS_MODE,
                "log_to_console": config.LOG_TO_CONSOLE,
                "auth_required": config.AUTH_REQUIRED
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
        logger.info("Forced garbage collection for Railway deployment")
        logger.info(f"Running in {'stateless' if config.STATELESS_MODE else 'persistent'} mode")
    
    return app

# Create the app instance
app = create_app()

if __name__ == "__main__":
    app.run(port=5000, debug=True)
