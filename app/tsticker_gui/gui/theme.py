"""Dark, modern Qt stylesheet for the tsticker-gui window.

Influenced by GitHub's dark palette (no indigo/blue primaries per project rules)
— accents are emerald/teal with amber warnings and coral errors.
"""

from __future__ import annotations

QSS = """
* {
    font-family: 'Inter', 'SF Pro Text', 'Segoe UI', 'Roboto', sans-serif;
    font-size: 13px;
    color: #d7dde5;
}

QMainWindow, QWidget#root {
    background-color: #0b0d10;
}

QWidget#sidebar {
    background-color: #111418;
    border-right: 1px solid #1c2127;
}

QLabel {
    background: transparent;
    color: #c9d1d9;
}

QLabel#h1 {
    font-size: 22px;
    font-weight: 700;
    color: #f3f6f9;
}

QLabel#h2 {
    font-size: 16px;
    font-weight: 600;
    color: #e6edf3;
}

QLabel#hint {
    color: #7c8794;
    font-size: 12px;
}

QLabel#brand {
    font-size: 18px;
    font-weight: 800;
    color: #2dd4bf;
    letter-spacing: 1px;
}

QPushButton {
    background-color: #2a3138;
    border: 1px solid #3a434c;
    border-radius: 6px;
    padding: 8px 14px;
    color: #f3f6f9;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #3a434c;
    border-color: #5b6470;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #1a1f25;
    border-color: #2a3138;
    color: #f3f6f9;
}

QPushButton:disabled {
    color: #5b6470;
    background-color: #161a1f;
    border-color: #1c2127;
}

QPushButton#primary {
    background-color: #14b8a6;
    border: 1px solid #14b8a6;
    color: #06231f;
    font-weight: 700;
}

QPushButton#primary:hover {
    background-color: #2dd4bf;
    border-color: #2dd4bf;
    color: #06231f;
}

QPushButton#primary:pressed {
    background-color: #0d9488;
    border-color: #0d9488;
    color: #ffffff;
}

QPushButton#primary:disabled {
    background-color: #134e4a;
    border-color: #134e4a;
    color: #5eead4;
}

QPushButton#danger {
    background-color: #7f1d1d;
    border: 1px solid #991b1b;
    color: #fecaca;
    font-weight: 600;
}

QPushButton#danger:hover {
    background-color: #991b1b;
    border-color: #b91c1c;
    color: #fee2e2;
}

QPushButton#danger:pressed {
    background-color: #450a0a;
    border-color: #7f1d1d;
    color: #fecaca;
}

QPushButton#danger:disabled {
    background-color: #2a1417;
    border-color: #3a1d22;
    color: #6b4a4d;
}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
    background-color: #111418;
    border: 1px solid #232a31;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: #14b8a6;
    selection-color: #0b0d10;
}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid #14b8a6;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #111418;
    border: 1px solid #232a31;
    selection-background-color: #14b8a6;
    selection-color: #0b0d10;
}

QTabWidget::pane {
    border: 1px solid #1c2127;
    border-radius: 8px;
    top: -1px;
    background: #0d1014;
}

QTabBar::tab {
    background: #0b0d10;
    color: #7c8794;
    padding: 10px 18px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background: #0d1014;
    color: #2dd4bf;
    border-color: #1c2127;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    color: #c9d1d9;
}

QProgressBar {
    background-color: #111418;
    border: 1px solid #232a31;
    border-radius: 6px;
    height: 14px;
    text-align: center;
    color: #c9d1d9;
    font-size: 11px;
}

QProgressBar::chunk {
    background-color: #14b8a6;
    border-radius: 5px;
}

QGroupBox {
    border: 1px solid #1c2127;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 12px;
    background-color: #0d1014;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #2dd4bf;
    font-weight: 600;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #2a3138;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #3a434c;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #2a3138;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #3a434c;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QStatusBar {
    background: #0b0d10;
    border-top: 1px solid #1c2127;
    color: #7c8794;
}

QStatusBar QLabel {
    color: #7c8794;
}

QFrame#divider {
    background: #1c2127;
    max-height: 1px;
    min-height: 1px;
}

QToolButton {
    background: #111418;
    border: 1px solid transparent;
    color: #c9d1d9;
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 13px;
    text-align: left;
}

QToolButton:hover {
    background: #1c2127;
    border-color: #2a3138;
    color: #ffffff;
}

QToolButton:checked {
    background: #14b8a6;
    border-color: #14b8a6;
    color: #06231f;
    font-weight: 700;
}

QToolButton:checked:hover {
    background: #2dd4bf;
    border-color: #2dd4bf;
    color: #06231f;
}

QToolButton:pressed {
    background: #0d9488;
    color: #ffffff;
}
"""


def apply_theme(app) -> None:  # type: ignore[no-untyped-def]
    """Apply the dark stylesheet to a ``QApplication``."""
    app.setStyleSheet(QSS)


__all__ = ["QSS", "apply_theme"]
