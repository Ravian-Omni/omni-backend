# src/utils/logging.py
from loguru import logger
from pathlib import Path

def setup_logging(
    log_file="app.log",
    log_dir="logs",
    rotation="10 MB",  # rotate when file size exceeds 10 MB
    retention=5,        # keep last 5 log files
    log_level="INFO",
    console_output=True
):
    """
    Set up loguru logger with rotating file and optional console output.

    Args:
        log_file: Name of the log file
        log_dir: Directory where log files are stored
        rotation: When to rotate (e.g. '10 MB', '1 week')
        retention: Number of rotated logs to keep (or time-based like '10 days')
        log_level: Log level (e.g., 'INFO', 'DEBUG')
        console_output: Whether to also log to the console
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
        diagnose=True
    )

    # Console output
    if console_output:
        logger.add(
            sink=lambda msg: print(msg, end=""),
            level=log_level,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}:{function}:{line}</cyan> - <level>{message}</level>",
            backtrace=True,
            diagnose=True
        )

    logger.info("Logger initialized")
    return logger


def cleanup_logging():
    """
    Cleanup is rarely needed with loguru, but you can remove all handlers if shutting down.
    """
    logger.info("Cleaning up logging handlers")
    logger.remove()
