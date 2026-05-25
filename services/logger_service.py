import logging
from pathlib import Path


LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

PIPELINE_LOG = LOG_DIR / "pipeline.log"
ERROR_LOG = LOG_DIR / "errors.log"


def get_logger(name: str = "radarballena") -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    file_handler = logging.FileHandler(PIPELINE_LOG, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    error_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)

    return logger