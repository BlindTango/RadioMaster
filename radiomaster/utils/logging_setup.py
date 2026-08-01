"""Rotating file logger — portable, lives in <app_dir>/logs/ next to the executable."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from .paths import data_dir

LEVELS = ["off", "error", "warning", "info", "debug"]

_LEVEL_MAP = {
    "off": logging.CRITICAL + 10,  # effectively silences everything
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

_configured = False


def setup_logging(level: str = "info") -> None:
    global _configured
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # handlers below do the actual filtering

    if not _configured:
        log_path = os.path.join(data_dir("logs"), "radiomaster.log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
        root.addHandler(file_handler)

        # RadioMaster is built as a windowed (console=False) app, so there is
        # no console for stdout/stderr to attach to — both are None in that
        # case, and a StreamHandler pointed at a None stream raises on every
        # single log call. Only add the console handler when a real stream
        # exists (e.g. running from a terminal via `python main.py`).
        console_stream = sys.stderr
        if console_stream is not None:
            console_handler = logging.StreamHandler(console_stream)
            console_handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"))
            root.addHandler(console_handler)

        _configured = True

    set_level(level)


def set_level(level: str) -> None:
    resolved = _LEVEL_MAP.get(level, logging.INFO)
    for handler in logging.getLogger().handlers:
        handler.setLevel(resolved)
