import logging
import os
from logging.handlers import RotatingFileHandler

_LOGGER_CACHE = {}


def get_logger(name="assistant"):
    """
    Return a shared structured logger writing to logs/assistant.log.
    """
    if name in _LOGGER_CACHE:
        return _LOGGER_CACHE[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "assistant.log")

        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            fmt='ts=%(asctime)s level=%(levelname)s logger=%(name)s event="%(message)s"',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _LOGGER_CACHE[name] = logger
    return logger
