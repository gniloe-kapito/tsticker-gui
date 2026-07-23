"""Colorful log panel widget.

Mirrors the original Rich-based CLI output: each level gets its own colour and
the panel auto-scrolls. Acts as a ``LogCb`` for the ``core.ops`` functions.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

# Level -> hex colour. Dark-theme friendly.
LEVEL_COLORS: dict[str, str] = {
    "debug": "#7c8794",
    "info": "#7fb3ff",
    "ok": "#7ee787",
    "warn": "#f0b429",
    "err": "#ff6b6b",
}


class LogPanel(QWidget):
    """A read-only, colourised, auto-scrolling log view."""

    log_signal = Signal(str, str)  # (level, message)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(5000)
        self._view.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        # Dark, mono-spaced.
        self._view.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #0f1115;
                color: #c9d1d9;
                border: 1px solid #1f242c;
                border-radius: 6px;
                padding: 8px;
                font-family: 'JetBrains Mono', 'Cascadia Mono', 'Menlo', 'Consolas', monospace;
                font-size: 12px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        # Marshals cross-thread log calls onto the GUI thread.
        self.log_signal.connect(self._append)

    # Public API -----------------------------------------------------------
    def as_callback(self) -> Callable[[str, str], None]:
        """Return a LogCb-safe closure (thread-safe)."""
        return lambda level, message: self.log_signal.emit(level, message)

    def clear(self) -> None:
        self._view.clear()

    # Implementation -------------------------------------------------------
    def _append(self, level: str, message: str) -> None:
        color_hex = LEVEL_COLORS.get(level, "#c9d1d9")
        timestamp = datetime.now().strftime("%H:%M:%S")
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt_ts = QTextCharFormat()
        fmt_ts.setForeground(QColor("#5b6470"))
        cursor.insertText(f"{timestamp} ", fmt_ts)

        fmt_lvl = QTextCharFormat()
        fmt_lvl.setForeground(QColor(color_hex))
        fmt_lvl.setFontWeight(700)
        label = level.upper().ljust(5)
        cursor.insertText(f"{label} ", fmt_lvl)

        fmt_msg = QTextCharFormat()
        fmt_msg.setForeground(QColor("#d7dde5"))
        cursor.insertText(message + "\n", fmt_msg)

        self._view.setTextCursor(cursor)
        self._view.ensureCursorVisible()
