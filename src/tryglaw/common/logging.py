from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

STARTUP = 25
logging.addLevelName(STARTUP, "INFO")

_LEVEL_COLORS = {
    "DEBUG": "\033[32m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[31m",
}
_RESET = "\033[0m"


class ColoredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{_RESET}"
        return super().format(record)


def setup_logger(
    name: str,
    level: str = "DEBUG",
    payload_log_file: str | None = None,
) -> tuple[logging.Logger, logging.Logger | None]:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            ColoredFormatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
        )
        logger.addHandler(handler)

    payload_logger: logging.Logger | None = None
    if payload_log_file:
        payload_logger = logging.getLogger(f"{name}.payloads")
        payload_logger.setLevel(logging.DEBUG)
        payload_logger.propagate = False
        if not payload_logger.handlers:
            path = Path(payload_log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(str(path), encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
            payload_logger.addHandler(fh)

    return logger, payload_logger


def log_payload(payload_logger: logging.Logger | None, direction: str, data: dict) -> None:
    if payload_logger:
        payload_logger.info("%s | %s", direction, json.dumps(data, default=str))


def green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def startup_log(logger: logging.Logger, msg: str, *args: object) -> None:
    original_level = logger.level
    if original_level > logging.INFO:
        logger.setLevel(logging.INFO)
    logger.info(msg, *args)
    if original_level > logging.INFO:
        logger.setLevel(original_level)
