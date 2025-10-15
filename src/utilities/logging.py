"""Logging configuration utilities using Loguru.

This module provides functions to set up and manage application logging
with file rotation, console output, and custom formatting using the Loguru
logging library.
"""

from pathlib import Path

from loguru import logger


def setup_logging(
    log_file="app.log",
    log_dir="logs",
    rotation="10 MB",  # rotate when file size exceeds 10 MB
    retention=5,  # keep last 5 log files
    log_level="INFO",
    console_output=True,
):
    """Set up loguru logger with rotating file and optional console output.

    Configure the application's logging system with file rotation, retention
    policies, and optional console output. Uses Loguru for enhanced logging
    features including multiprocessing safety and automatic backtrace.

    Args:
        log_file: Name of the log file. Defaults to "app.log".
        log_dir: Directory where log files are stored. Defaults to "logs".
        rotation: When to rotate the log file (e.g. '10 MB', '1 week').
            Defaults to "10 MB".
        retention: Number of rotated logs to keep or time-based retention
            (e.g., 5 or '10 days'). Defaults to 5.
        log_level: Minimum log level to record (e.g., 'INFO', 'DEBUG').
            Defaults to "INFO".
        console_output: Whether to also log to the console. Defaults to True.

    Returns:
        Configured logger instance.

    Example:
        >>> logger = setup_logging(
        ...     log_file="myapp.log",
        ...     log_dir="logs",
        ...     log_level="DEBUG",
        ...     console_output=True
        ... )
        >>> logger.info("Application started")

    Note:
        The function removes all existing handlers before setting up new ones.
        Log files are created with multiprocessing-safe enqueue option.
    """
    logger.remove()  # Clear default handler

    # Ensure log directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # File logging with rotation
    logger.add(
        log_path / log_file,
        rotation=rotation,
        retention=retention,
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
        enqueue=True,  # Safe for multiprocessing
        backtrace=True,
        diagnose=True,
    )

    # Console output
    if console_output:
        logger.add(
            sink=lambda msg: print(msg, end=""),
            level=log_level,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}:{function}:{line}</cyan> - <level>{message}</level>",
            backtrace=True,
            diagnose=True,
        )

    logger.info("Logger initialized")
    return logger


def cleanup_logging():
    """Clean up and remove all logging handlers.

    Remove all registered logging handlers. This is useful when shutting down
    the application to ensure all logs are flushed and resources are released.

    Note:
        Cleanup is rarely needed with Loguru as it handles resource management
        automatically, but this function is provided for explicit shutdown scenarios.

    Example:
        >>> setup_logging()
        >>> # ... application code ...
        >>> cleanup_logging()  # On application shutdown
    """
    logger.info("Cleaning up logging handlers")
    logger.remove()
