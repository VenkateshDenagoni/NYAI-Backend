import os
import logging
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

# Base application settings
class BaseConfig:
    """Base configuration class."""
    # Application settings
    APP_NAME = "NYAI Legal Assistant"
    VERSION = "1.0.0"
    
    # Cache settings
    CACHE_TYPE = "SimpleCache"
    CACHE_DEFAULT_TIMEOUT = 3600  # 1 hour
    
    # Rate limiting
    RATE_LIMIT_ENABLED = True
    RATE_LIMIT_WINDOW = 60  # seconds
    MAX_REQUESTS_PER_WINDOW = 100  # Increased for production
    
    # Session settings - Disable sessions
    SESSION_TYPE = "null"
    
    # Load balancing
    WORKER_COUNT = 4
    THREADS_PER_WORKER = 2
    
    # Log settings
    LOG_LEVEL = logging.INFO
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s'
    LOG_FILE = "nyai_api.log"
    LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "false").lower() == "true"
    
    # API settings
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    LLM_MODEL = "gemini-2.0-flash-001"
    
    # Token and request limits
    MAX_PROMPT_LENGTH = 4000
    MAX_HISTORY_LENGTH = 10
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 1
    RETRY_MIN_SECONDS = 4
    RETRY_MAX_SECONDS = 10
    
    # Security settings
    SECRET_KEY = os.getenv("SECRET_KEY")
    AUTH_REQUIRED = False
    API_KEY = os.getenv("API_KEY")
    
    # Prompt template paths
    PROMPT_TEMPLATES_DIR = Path(__file__).parent / "prompts"
    
    # Ensure prompt templates directory exists
    if not PROMPT_TEMPLATES_DIR.exists():
        PROMPT_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Feature flags
    ENABLE_CONTENT_SAFETY = True
    STATELESS_MODE = os.getenv("STATELESS_MODE", "false").lower() == "true"
    
    # Health checks
    HEALTH_CHECK_TIMEOUTS = 5  # seconds
    
    # Paths
    KNOWLEDGE_BASE_DIR = os.getenv("KNOWLEDGE_BASE_DIR", 
                                   Path(__file__).parent.parent / "knowledge_base")
    VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", 
                              Path(__file__).parent.parent / "db" / "chroma_rag")
    SESSION_DB_PATH = os.getenv("SESSION_DB_PATH", 
                               Path(__file__).parent.parent / "instance" / "sessions")

class DevelopmentConfig(BaseConfig):
    """Development configuration."""
    LOG_LEVEL = logging.DEBUG
    RATE_LIMIT_ENABLED = False
    LOG_TO_CONSOLE = True
    
class ProductionConfig(BaseConfig):
    """Production configuration."""
    LOG_LEVEL = logging.WARNING
    AUTH_REQUIRED = True
    
    # Production worker settings
    WORKER_COUNT = 8
    THREADS_PER_WORKER = 4
    
    # Production rate limiting
    MAX_REQUESTS_PER_WINDOW = 200  # Higher limit for production

class TestingConfig(BaseConfig):
    """Testing configuration."""
    LOG_LEVEL = logging.DEBUG
    CACHE_TTL = 1  # Short cache for testing
    ENABLE_CONTENT_SAFETY = False
    STATELESS_MODE = True

# Select config based on environment
def get_config():
    """Return the appropriate configuration based on environment."""
    env = os.getenv("NYAI_ENV", "development").lower()
    configs = {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
        "testing": TestingConfig
    }
    return configs.get(env, DevelopmentConfig)

# Export the active configuration
config = get_config()