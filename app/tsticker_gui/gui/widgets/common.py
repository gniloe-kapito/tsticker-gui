"""Shared composite widgets used across tabs."""

from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DirectoryPicker(QWidget):
    """A label + read-only line edit + browse button."""

    changed = Signal(str)

    def __init__(
        self,
        *,
        label: str = "Working directory",
        default: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._path = pathlib.Path(default).expanduser() if default else pathlib.Path.cwd()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        caption = QLabel(label)
        caption.setObjectName("hint")
        layout.addWidget(caption)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._edit = QLineEdit(str(self._path))
        self._edit.setReadOnly(True)
        self._edit.setPlaceholderText("Select a directory…")
        row.addWidget(self._edit, 1)

        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick)
        row.addWidget(browse, 0)
        layout.addLayout(row)

    def path(self) -> pathlib.Path:
        return pathlib.Path(self._edit.text() or ".").expanduser()

    def set_path(self, p: str | pathlib.Path) -> None:
        self._edit.setText(str(p))
        self.changed.emit(str(p))

    def _pick(self) -> None:
        start = str(self._path) if self._path.exists() else str(pathlib.Path.home())
        choice = QFileDialog.getExistingDirectory(self, "Select directory", start)
        if choice:
            self._path = pathlib.Path(choice)
            self._edit.setText(choice)
            self.changed.emit(choice)


class OperationCard(QFrame):
    """A bordered card containing a title, body widget and an action button row.

    The card exposes a :class:`QProgressBar` and helpers to enable/disable the
    action buttons while a job is running.
    """

    def __init__(
        self,
        *,
        title: str,
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(
            """
            QFrame#card {
                background: #0d1014;
                border: 1px solid #1c2127;
                border-radius: 10px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        h = QLabel(title)
        h.setObjectName("h2")
        root.addWidget(h)

        if description:
            d = QLabel(description)
            d.setObjectName("hint")
            d.setWordWrap(True)
            root.addWidget(d)
            self._desc = d

        self._body = QVBoxLayout()
        self._body.setSpacing(8)
        root.addLayout(self._body)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
        self._actions.addStretch(1)
        root.addLayout(self._actions)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        root.addWidget(self._progress)

    # API ------------------------------------------------------------------
    def add_body_widget(self, w: QWidget) -> None:
        self._body.addWidget(w)

    def add_body_layout(self, layout) -> None:  # type: ignore[no-untyped-def]
        self._body.addLayout(layout)

    def add_action(self, button: QPushButton) -> None:
        self._actions.insertWidget(self._actions.count() - 1, button)

    def primary_action(self, text: str, handler=None) -> QPushButton:  # type: ignore[no-untyped-def]
        btn = QPushButton(text)
        btn.setObjectName("primary")
        if handler is not None:
            btn.clicked.connect(handler)
        self.add_action(btn)
        return btn

    def secondary_action(self, text: str, handler=None) -> QPushButton:  # type: ignore[no-untyped-def]
        btn = QPushButton(text)
        if handler is not None:
            btn.clicked.connect(handler)
        self.add_action(btn)
        return btn

    def danger_action(self, text: str, handler=None) -> QPushButton:  # type: ignore[no-untyped-def]
        btn = QPushButton(text)
        btn.setObjectName("danger")
        if handler is not None:
            btn.clicked.connect(handler)
        self.add_action(btn)
        return btn

    # progress helpers -----------------------------------------------------
    def show_progress(self, visible: bool = True) -> None:
        self._progress.setVisible(visible)
        if not visible:
            self._progress.setValue(0)

    def set_progress(self, current: int, total: int, message: str = "") -> None:
        if total <= 0:
            self._progress.setRange(0, 0)  # indeterminate
        else:
            self._progress.setRange(0, total)
            self._progress.setValue(current)
        self._progress.setFormat(message or f"{current}/{total}")

    def set_busy(self, busy: bool) -> None:
        """Disable every button while busy, restore when done."""
        for i in range(self._actions.count()):
            item = self._actions.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setEnabled(not busy)
        self.show_progress(busy)


class FormRow(QWidget):
    """A two-column row: label on the left, input on the right."""

    def __init__(self, label: str, widget: QWidget, *, hint: str = "") -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lbl = QLabel(label)
        lbl.setMinimumWidth(140)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(lbl, 0)
        lay.addWidget(widget, 1)
        if hint:
            h = QLabel(hint)
            h.setObjectName("hint")
            lay.addWidget(h, 0)


__all__ = ["DirectoryPicker", "OperationCard", "FormRow"]
