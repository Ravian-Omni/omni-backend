# src/utils/logging.py
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

class SafeStreamHandler(logging.StreamHandler):
    """A StreamHandler that handles BlockingIOError gracefully."""
    
    def emit(self, record):
        try:
            super().emit(record)
        except BlockingIOError:
            # If we can't write immediately, skip this log message
            pass
        except (BrokenPipeError, OSError):
            # Handle other common IO errors
            pass

def setup_logging(
    log_level=logging.INFO,
    log_format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    log_dir="logs",
    log_file="app.log",
    max_file_size=10 * 1024 * 1024,  # 10 MB
    backup_count=5,
    console_output=True
):
    """
    Configure logging for FastAPI application.
    Creates rotating log files when size limit is exceeded.
    
    Args:
        log_level: Logging level (default: logging.INFO)
        log_format: Format string for log messages
        log_dir: Directory to store log files
        log_file: Name of the log file
        max_file_size: Maximum size of each log file in bytes (10MB default)
        backup_count: Number of backup files to keep (creates app.log, app.log.1, app.log.2, etc.)
        console_output: Whether to output logs to console as well
    
    Returns:
        Logger instance
    """
    # Create formatter
    formatter = logging.Formatter(log_format)
    
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Clear existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create logs directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Create rotating file handler
    # This automatically creates multiple files when size limit is exceeded
    # Files will be: app.log, app.log.1, app.log.2, etc.
    file_handler = RotatingFileHandler(
        log_path / log_file,
        maxBytes=max_file_size,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    logger.addHandler(file_handler)
    
    # Create safe console handler
    if console_output:
        console_handler = SafeStreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)
        logger.addHandler(console_handler)
    
    return logger

def setup_fastapi_logging(
    log_file="app.log",
    max_file_size=10 * 1024 * 1024,  # 10 MB
    backup_count=5
):
    """
    Quick setup function specifically for FastAPI applications.
    
    Args:
        log_file: Name of the log file
        max_file_size: Maximum size before rotating (10MB default)
        backup_count: Number of backup files to keep
    
    Returns:
        Logger instance
    """
    return setup_logging(
        log_file=log_file,
        max_file_size=max_file_size,
        backup_count=backup_count,
        console_output=True
    )
    
def cleanup_logging():
    """
    Clean up logging resources on application shutdown.
    Flushes and closes all handlers to ensure log messages are written.
    """
    logger = logging.getLogger()
    
    # Flush and close all handlers
    for handler in logger.handlers[:]:
        try:
            handler.flush()
            handler.close()
        except Exception:
            # Ignore errors during cleanup
            pass
        finally:
            logger.removeHandler(handler)