# src/utils/logging.py
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
    Configure logging to write to both file and console.
    
    Args:
        log_level: Logging level (default: logging.INFO)
        log_format: Format string for log messages
        log_dir: Directory to store log files
        log_file: Name of the log file
        max_file_size: Maximum size of each log file in bytes
        backup_count: Number of backup files to keep
        console_output: Whether to output logs to console as well
    
    Returns:
        Logger instance
    """
    # Create formatter
    formatter = logging.Formatter(log_format)
    
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create logs directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Create file handler for logging to file
    file_handler = RotatingFileHandler(
        log_path / log_file,
        maxBytes=max_file_size,
        backupCount=backup_count
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    logger.addHandler(file_handler)
    
    # Create console handler for logging to console
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)
        logger.addHandler(console_handler)
    
    return logger

# Default configuration
logger = setup_logging()