from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import redis
import logging
from werkzeug.middleware.dispatcher import DispatcherMiddleware
import gc
import os

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
from src.utils.nltk_setup import download_nltk_data

# Initialize NLTK
logger.info("Setting up NLTK data...")
nltk_setup_success = download_nltk_data()
if nltk_setup_success:
    logger.info("NLTK setup completed successfully")
else:
    logger.warning("NLTK setup encountered issues - some NLP features may not work correctly")

# Initialize extensions
db = SQLAlchemy()

# Check Redis availability
redis_available = True
try:
    redis_client = redis.Redis.from_url(
        config.REDIS_URL, 
        socket_connect_timeout=1
    )
    redis_client.ping()
    logger.info("Redis connection successful")
except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
    redis_available = False
    logger.warning(f"Redis connection failed: {str(e)}")
    logger.warning("Using fallback in-memory storage for caching and session management.")
    logger.warning("To enable Redis (recommended for production):")
    logger.warning("1. Install Redis server: https://redis.io/docs/getting-started/")
    logger.warning("2. Start Redis server: 'redis-server'")
    logger.warning("3. Verify Redis is running: 'redis-cli ping' should return 'PONG'")
except Exception as e:
    redis_available = False
    logger.error(f"Unexpected Redis error: {str(e)}")
    logger.warning("Using fallback in-memory storage for caching and session management.")

# Configure caching based on Redis availability
if redis_available:
    cache = Cache()
else:
    cache = Cache(config={'CACHE_TYPE': 'SimpleCache'})

# Configure session based on Redis availability
session = Session()

# Configure rate limiter based on Redis availability
if redis_available:
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["200 per minute"],
        storage_uri=config.REDIS_URL
    )
else:
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
    
    # Override Redis-dependent settings if Redis is unavailable
    if not redis_available:
        app.config['CACHE_TYPE'] = 'SimpleCache'
        app.config['SESSION_TYPE'] = 'filesystem'
    
    # Initialize extensions
    CORS(app)
    db.init_app(app)
    cache.init_app(app)
    session.init_app(app)
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
        # Check database connection
        db_status = "healthy"
        try:
            db.session.execute("SELECT 1")
        except Exception as e:
            db_status = f"error: {str(e)}"
        
        # Check Redis status
        redis_status = "healthy" if redis_available else "unavailable (using fallback)"
        
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
        
        # Check NLTK status
        nltk_status = "healthy" if nltk_setup_success else "limited functionality"
        
        return {
            "status": "healthy",
            "dependencies": {
                "database": db_status,
                "redis": redis_status,
                "chromadb": chroma_status,
                "embedding_function": embedding_status,
                "rag_service": rag_status,
                "nltk": nltk_status
            },
            "version": config.VERSION
        }
    
    # Add metrics endpoint if prometheus is available
    if prometheus_available:
        app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
            '/metrics': make_wsgi_app()
        })
    
    # Create database tables
    with app.app_context():
        db.create_all()
    
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
