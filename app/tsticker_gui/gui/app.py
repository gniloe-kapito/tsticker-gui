"""Main application window for tsticker-gui.

Layout:

    +-----------------+-----------------------------+
    |  sidebar        |  stacked tabs               |
    |  • Login        |  (each tab is a QWidget)    |
    |  • Init         |                             |
    |  • Push / Sync  +-----------------------------+
    |  • Download     |  log dock (collapsible)     |
    |  • Show         |                             |
    +-----------------+-----------------------------+
    |  status bar: [activity] [login state] [log ▼] |
    +------------------------------------------------+
"""

from __future__ import annotations

import asyncio
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
try:
    from qasync import QEventLoop  # type: ignore
except Exception:  # pragma: no cover - hard runtime dep
    QEventLoop = None  # type: ignore

from .. import __version__
from ..log_to_file import configure_file_log, get_log_path, log_message
from ..utils import close_session_sync
from .theme import apply_theme
from .widgets.download_tab import DownloadTab
from .widgets.init_tab import InitTab
from .widgets.log_panel import LogPanel
from .widgets.login_tab import LoginTab
from .widgets.push_sync_tab import PushSyncTab
from .widgets.show_tab import ShowTab


class MainWindow(QMainWindow):
    """Top-level window."""

    # Internal signal to marshal status updates from worker threads to the GUI thread.
    _status_signal = Signal(str, str, str)  # (state, message, detail)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"tsticker-gui — Telegram Sticker Manager {__version__}")
        self.resize(1320, 860)
        self.setMinimumSize(1040, 700)

        # central area -----------------------------------------------------
        central = QWidget(objectName="root")
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # sidebar ----------------------------------------------------------
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(220)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(14, 22, 14, 22)
        sb_layout.setSpacing(8)

        brand = QLabel("tsticker-gui")
        brand.setObjectName("brand")
        sb_layout.addWidget(brand)

        sub = QLabel("Telegram stickers")
        sub.setObjectName("hint")
        sb_layout.addWidget(sub)

        sb_layout.addSpacing(14)

        # content + nav --------------------------------------------------
        self._content = QStackedWidget()
        self._nav_btns: list[QToolButton] = []

        # Create tabs with descriptions for tooltips
        self._tabs = [
            ("Login", LoginTab(), "Log in with your Telegram bot token"),
            ("Init", InitTab(), "Create a new sticker pack folder"),
            ("Push/Sync", PushSyncTab(), "Upload local stickers to Telegram / download from Telegram"),
            ("Download", DownloadTab(), "Download or trace any public sticker pack by link"),
            ("Show", ShowTab(), "Inspect local index.json and cloud state"),
        ]
        for name, w, _desc in self._tabs:
            self._content.addWidget(w)

        for idx, (name, _w, desc) in enumerate(self._tabs):
            btn = QToolButton()
            btn.setText(name)
            btn.setCheckable(True)
            btn.setAutoRaise(True)
            btn.setMinimumHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(desc)
            btn.clicked.connect(lambda _checked=False, i=idx: self._switch(i))
            sb_layout.addWidget(btn)
            self._nav_btns.append(btn)

        sb_layout.addStretch(1)

        footer = QLabel(f"v{__version__} • PySide6")
        footer.setObjectName("hint")
        sb_layout.addWidget(footer)

        outer.addWidget(sidebar, 0)
        outer.addWidget(self._content, 1)

        self.setCentralWidget(central)

        # log panel as a collapsible dock widget ---------------------------
        self._log = LogPanel()
        self._log_dock = QDockWidget("Log", self)
        self._log_dock.setWidget(self._log)
        self._log_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self._log_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)
        self._log_dock.setMaximumHeight(220)
        self._log_dock.setMinimumHeight(100)

        # --- status bar: activity | login | log toggle --------------------
        # Order: [activity (left, stretches)] [permanent: login] [log button]
        self._status_activity = QLabel("Idle")
        self._status_activity.setStyleSheet("color: #7c8794; padding: 0 8px;")
        self._status_activity.setMinimumWidth(200)
        self.statusBar().addWidget(self._status_activity, 1)

        # log toggle button
        from PySide6.QtWidgets import QPushButton
        log_action = self._log_dock.toggleViewAction()
        log_action.setText("Show log panel")
        log_btn = QPushButton("Log ▼")
        log_btn.setFlat(True)
        log_btn.setToolTip("Show / hide the log panel")
        log_btn.clicked.connect(log_action.trigger)
        self.statusBar().addPermanentWidget(log_btn)

        # login state indicator
        self._status_login = QLabel("checking…")
        self._status_login.setStyleSheet("padding: 0 8px;")
        self.statusBar().addPermanentWidget(self._status_login)

        # Connect internal status signal (thread-safe marshalling)
        self._status_signal.connect(self._update_status_ui)

        # wire log signals from tabs --------------------------------------
        for _name, tab, _desc in self._tabs:
            sig = getattr(tab, "log", None)
            if sig is not None:
                # Show in the panel…
                sig.connect(self._log.log_signal.emit)
                # …and also persist to app.log on disk.
                sig.connect(lambda lvl, msg, _t=tab: log_message(lvl, msg))

        # Wire each tab's progress to the status bar. Tabs that emit a
        # ``progress`` signal (current, total, message) will update the
        # activity indicator in real time.
        for _name, tab, _desc in self._tabs:
            prog_sig = getattr(tab, "progress", None)
            if prog_sig is not None:
                prog_sig.connect(self._on_progress)

            # Also wire "busy started / finished" if the tab exposes it.
            busy_sig = getattr(tab, "busy", None)
            if busy_sig is not None:
                busy_sig.connect(self._on_busy)

        # initial state ----------------------------------------------------
        self._switch(2)  # default to Push/Sync (the most-used tab)
        self._refresh_login_state()

    # ---------------------------------------------------------------------
    def _switch(self, idx: int) -> None:
        self._content.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)

    def _refresh_login_state(self) -> None:
        from ..core import ops

        creds = ops.get_credentials()
        if creds is None:
            self._status_login.setText("● logged out")
            self._status_login.setStyleSheet("color: #ff6b6b; padding: 0 8px;")
            self._status_login.setToolTip("Not logged in. Open the Login tab.")
        else:
            try:
                user = creds.bot_user
                self._status_login.setText(f"● @{user.username}")
                self._status_login.setStyleSheet("color: #7ee787; padding: 0 8px;")
                self._status_login.setToolTip(
                    f"Logged in as bot @{user.username} ({user.first_name}).\n"
                    f"Owner id: {creds.owner_id}"
                )
            except Exception:
                self._status_login.setText("● token invalid")
                self._status_login.setStyleSheet("color: #f0b429; padding: 0 8px;")
                self._status_login.setToolTip("Stored bot token is invalid. Login again.")

    # --- status bar updates (thread-safe via signal) ---------------------
    def _update_status_ui(self, state: str, message: str, detail: str) -> None:
        """Update the activity indicator. Called on the GUI thread."""
        colors = {
            "idle": "#7c8794",
            "working": "#f0b429",
            "ok": "#7ee787",
            "err": "#ff6b6b",
        }
        color = colors.get(state, "#7c8794")
        icon = {"idle": "○", "working": "◐", "ok": "●", "err": "✗"}.get(state, "○")
        self._status_activity.setText(f"{icon} {message}")
        self._status_activity.setStyleSheet(f"color: {color}; padding: 0 8px;")
        if detail:
            self._status_activity.setToolTip(detail)
        # refresh login state too (in case it changed)
        if state in ("ok", "err", "idle"):
            self._refresh_login_state()

    def _on_progress(self, current: int, total: int, message: str) -> None:
        """Called when a tab emits a progress signal."""
        if total > 0:
            text = f"{message}  ({current}/{total})"
        else:
            text = message
        self._status_signal.emit("working", text, message)

    def _on_busy(self, busy: bool) -> None:
        """Called when a tab starts/stops a long operation."""
        if not busy:
            self._status_signal.emit("idle", "Idle", "")

    # ---------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Try to close the aiohttp session used by pytelegrambotapi.
        close_session_sync()
        super().closeEvent(event)


def main() -> int:
    """Entry point — starts Qt + qasync and shows the main window."""
    # Set up persistent file logging FIRST so any later error is captured.
    log_path = configure_file_log()

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)

    if QEventLoop is None:
        raise RuntimeError(
            "qasync is required for tsticker-gui. Run `uv sync` to install all deps."
        )
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    # Surface the log file path in the status bar tooltip so the user can find it.
    if log_path is not None:
        window.statusBar().setToolTip(
            f"App log file: {log_path}\nCrash log: {log_path.parent / 'crash.log'}"
        )
    window.show()

    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
