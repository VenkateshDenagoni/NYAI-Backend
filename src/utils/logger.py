import logging
import uuid
import sys
import os
from logging.handlers import RotatingFileHandler
from functools import wraps
from pathlib import Path
from flask import request, g, has_request_context

from src.config import config

# Add request_id filter
class RequestIdFilter(logging.Filter):
    """Add request_id to log records."""
    
    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, 'request_id', 'no_request_id')
        else:
            record.request_id = 'no_request_id'
        return True

# Configure logger
def setup_logger(name="nyai"):
    """Configure logger with file and console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(config.LOG_LEVEL)
    
    # Remove existing handlers if any
    if logger.handlers:
        logger.handlers.clear()
    
    # Get log file path from environment or config
    log_file = os.getenv("LOG_FILE", config.LOG_FILE)
    
    # Check if we should log to console only (default to true in containerized environments)
    # This is important for platforms like Railway where file system permissions may be restrictive
    log_to_console = os.getenv("LOG_TO_CONSOLE", "false").lower() == "true"
    
    # Force console logging in containerized environments by default
    if os.getenv("RAILWAY_STATIC_URL") or os.getenv("RAILWAY_SERVICE_ID") or os.getenv("RAILWAY_PROJECT_ID"):
        log_to_console = True
        logger.info("Detected Railway environment - defaulting to console-only logging")
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    
    # Add filter to handlers
    request_id_filter = RequestIdFilter()
    console_handler.addFilter(request_id_filter)
    
    # Create formatter and add it to handlers
    formatter = logging.Formatter(config.LOG_FORMAT)
    console_handler.setFormatter(formatter)
    
    # Add console handler
    logger.addHandler(console_handler)
    
    # Attempt to create file handler if not console-only mode
    if not log_to_console:
        try:
            # Ensure the log directory exists
            log_path = Path(log_file)
            if not log_path.is_absolute():
                # If relative path, put it in logs directory under app root
                logs_dir = Path(__file__).parent.parent.parent / "logs"
                logs_dir.mkdir(exist_ok=True)
                log_path = logs_dir / log_file
            
            # Make sure parent directory exists
            log_path.parent.mkdir(exist_ok=True, parents=True)
            
            # Try creating an empty file to test write permissions
            try:
                if not log_path.exists():
                    log_path.touch()
                elif not os.access(str(log_path), os.W_OK):
                    raise PermissionError(f"No write permission for log file: {log_path}")
            except (IOError, PermissionError) as e:
                raise PermissionError(f"Cannot write to log file {log_path}: {str(e)}")
            
            # Create file handler
            file_handler = RotatingFileHandler(
                str(log_path), 
                maxBytes=10485760,  # 10MB
                backupCount=5
            )
            file_handler.addFilter(request_id_filter)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            
            logger.info(f"Logging to file: {log_path}")
        except (IOError, PermissionError) as e:
            logger.warning(f"Could not set up file logging: {e}. Falling back to console logging only.")
    else:
        logger.info("Console-only logging mode enabled")
    
    return logger

# Generate a request ID
def generate_request_id():
    """Generate a unique request ID."""
    return str(uuid.uuid4())

# Decorator to log function calls with timing
def log_function_call(logger):
    """Decorator to log function calls with timing."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import time
            start_time = time.time()
            
            # Generate function signature for logging
            func_args = ", ".join([str(arg) for arg in args])
            func_kwargs = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
            func_signature = f"{func.__name__}({func_args}, {func_kwargs})"
            
            # Log function call
            logger.debug(f"Calling {func_signature}")
            
            try:
                result = func(*args, **kwargs)
                execution_time = (time.time() - start_time) * 1000
                logger.debug(f"Finished {func.__name__} in {execution_time:.2f}ms")
                return result
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {str(e)}")
                raise
                
        return wrapper
    return decorator

# Create and export logger
logger = setup_logger() 