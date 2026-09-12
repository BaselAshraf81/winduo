"""Logging, to the console and to a rolling file next to the settings."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

__all__ = ["APP_DIR", "get_logger", "setup_logging"]


def _app_dir() -> Path:
    base = os.environ.get("WINDUO_HOME") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "WinDuo"
    return Path.home() / ".winduo"


APP_DIR = _app_dir()

_configured = False


def setup_logging(verbose: bool = False) -> None:
    """Attach handlers once. Safe to call from any entry point."""
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger("winduo")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(levelname).1s %(name)s: %(message)s"))
    root.addHandler(console)

    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        rolling = logging.handlers.RotatingFileHandler(
            APP_DIR / "winduo.log", maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
        rolling.setFormatter(
            logging.Formatter("%(asctime)s %(levelname).1s %(name)s: %(message)s")
        )
        root.addHandler(rolling)
    except OSError:
        # A read-only or missing profile directory is not worth failing over.
        root.debug("file logging unavailable", exc_info=True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"winduo.{name}")
