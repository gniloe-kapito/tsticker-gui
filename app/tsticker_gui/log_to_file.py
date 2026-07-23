"""File logging setup for tsticker-gui.

The GUI already has an in-app log panel (see :mod:`tsticker_gui.gui.widgets.log_panel`),
but when the app crashes — or when the user closes the window and later wants to
see what happened — a persistent file log is invaluable.

We use loguru (already a dependency) and write rotating logs to ``app.log``
next to the running script (or next to the frozen executable on Windows).
Only the last 5 MB is kept (2 rotating files of ~2.5 MB each).

Logs from this module are IN ADDITION to the in-app panel — both receive the
same messages. The file log captures everything (debug+), the panel only shows
what the GUI emits.
"""

from __future__ import annotations

import os
import pathlib
import sys
from typing import Optional

try:
    from loguru import logger as _logger
except Exception:  # pragma: no cover - loguru is a hard dep
    _logger = None  # type: ignore

_FILE_LOG_CONFIGURED = False
_LOG_PATH: Optional[pathlib.Path] = None


def configure_file_log(log_dir: pathlib.Path | None = None) -> Optional[pathlib.Path]:
    """Set up rotating file logging. Returns the log file path (or None on failure).

    ``log_dir`` defaults to the directory of the entry script (launch.py on
    Windows, the venv's site-packages on Linux). We write ``app.log`` there.
    """
    global _FILE_LOG_CONFIGURED, _LOG_PATH

    if _logger is None:
        return None
    if _FILE_LOG_CONFIGURED:
        return _LOG_PATH

    if log_dir is None:
        # Default: next to launch.py (sys.argv[0] in the deployed layout).
        try:
            entry = pathlib.Path(sys.argv[0]).resolve().parent
        except Exception:  # noqa: BLE001
            entry = pathlib.Path.cwd()
        log_dir = entry

    log_dir = pathlib.Path(log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fall back to the user's home dir if we can't write next to the script.
        log_dir = pathlib.Path.home() / ".tsticker-gui"
        log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / "app.log"
    try:
        # Remove the default loguru sink (stderr) so we don't double-log to
        # the console in Debug mode — keep only the file sink + the app panel.
        _logger.remove()
        _logger.add(
            str(log_path),
            rotation="2.5 MB",
            retention=2,
            encoding="utf-8",
            level="DEBUG",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | "
                "{name}:{function}:{line} | {message}"
            ),
            backtrace=True,
            diagnose=False,  # don't leak local vars (may contain tokens)
        )
        # Also keep a stderr sink for Debug.bat (console mode). Safe to add
        # even in pythonw mode — stderr is None and loguru handles it.
        _logger.add(
            sys.stderr,
            level="INFO",
            format="{time:HH:mm:ss} | {level: <7} | {message}",
        )
        _FILE_LOG_CONFIGURED = True
        _LOG_PATH = log_path
    except Exception:  # noqa: BLE001 - logging must never crash the app
        return None

    return _LOG_PATH


def get_log_path() -> Optional[pathlib.Path]:
    """Return the configured log file path (None if file logging isn't set up)."""
    return _LOG_PATH


def log_message(level: str, message: str) -> None:
    """Forward a GUI panel message to the file log.

    ``level`` is one of ``{"debug", "info", "ok", "warn", "err"}`` — the same
    vocabulary the GUI panel uses. We map ``ok`` → ``info`` and ``err`` →
    ``error`` for loguru.
    """
    if _logger is None:
        return
    mapping = {
        "debug": "DEBUG",
        "info": "INFO",
        "ok": "INFO",
        "warn": "WARNING",
        "err": "ERROR",
    }
    loguru_level = mapping.get(level, "INFO")
    try:
        _logger.log(loguru_level, message)
    except Exception:  # noqa: BLE001
        pass


__all__ = ["configure_file_log", "get_log_path", "log_message"]
