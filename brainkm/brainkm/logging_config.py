"""Structured logging setup for brainkm."""

import logging
import sys

from brainkm.config import get_settings


def configure_logging() -> None:
    """Configure root logger once (idempotent)."""
    settings = get_settings()
    root = logging.getLogger("brainkm")
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under brainkm."""
    configure_logging()
    return logging.getLogger(f"brainkm.{name}")
