"""Show tab: pretty-prints the local index.json and the cloud pack state."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core import ops
from ...gui.async_bridge import AsyncJobRunner
from ...gui.widgets.common import DirectoryPicker, OperationCard


class ShowTab(QWidget):
    """Displays pack info (local + cloud) and the raw ``index.json``."""

    log = Signal(str, str)  # (level, message) — required so app.py can connect
    progress = Signal(int, int, str)  # (current, total, message)
    busy = Signal(bool)  # True when an operation is running

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        title = QLabel("Sticker pack info")
        title.setObjectName("h1")
        root.addWidget(title)

        intro = QLabel(
            "Shows the local <code>index.json</code> for the working directory and the "
            "matching cloud sticker set (if any)."
        )
        intro.setObjectName("hint")
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._dir = DirectoryPicker(label="Working directory (must contain index.json)")
        root.addWidget(self._dir)

        # --- summary card -------------------------------------------------
        self._summary = OperationCard(
            title="Summary",
            description="Local index vs. cloud state.",
        )
        self._summary_label = QLabel("Press “Refresh” to load.")
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextFormat(Qt.TextFormat.RichText)
        self._summary.add_body_widget(self._summary_label)
        self._summary.primary_action("Refresh", self._on_refresh)
        self._restore_btn = self._summary.secondary_action("Restore snapshot", self._on_restore)
        self._restore_btn.setToolTip(
            "Restore the latest snapshot into the stickers/ folder.\n"
            "Use this if your stickers/ folder was wiped or corrupted."
        )
        self._restore_btn.setEnabled(False)
        root.addWidget(self._summary)

        # --- raw index card ----------------------------------------------
        self._raw = OperationCard(
            title="Raw index.json",
            description="Pretty-printed contents of the local index file.",
        )
        self._raw_view = QTextEdit()
        self._raw_view.setReadOnly(True)
        self._raw_view.setMinimumHeight(220)
        self._raw_view.setStyleSheet(
            "QTextEdit { background: #0f1115; color: #c9d1d9; "
            "border: 1px solid #1f242c; border-radius: 6px; padding: 8px; "
            "font-family: 'JetBrains Mono', 'Cascadia Mono', monospace; font-size: 12px; }"
        )
        self._raw.add_body_widget(self._raw_view)
        root.addWidget(self._raw)

        root.addStretch(1)

    # ---------------------------------------------------------------------
    def _on_refresh(self) -> None:
        target = self._dir.path()
        self._summary.set_busy(True)
        self.busy.emit(True)
        self.progress.emit(0, 0, "Loading pack info…")

        async def _do():
            return await ops.op_show(target_dir=target, log=self.log.emit)

        def _done():
            self._summary.set_busy(False)
            self.busy.emit(False)

        AsyncJobRunner(
            _do,
            on_success=self._on_done,
            on_error=self._on_err,
            on_finished=_done,
        ).start()

    def _on_done(self, data: dict | None) -> None:
        if data is None:
            self._summary_label.setText(
                "<span style='color:#ff6b6b'>●</span> Not logged in or no index.json found."
            )
            self._raw_view.setPlainText("")
            return

        local = data.get("local")
        cloud = data.get("cloud")
        if local is None:
            self._summary_label.setText(
                "<span style='color:#f0b429'>●</span> No <b>index.json</b> in the working directory."
            )
            self._raw_view.setPlainText("")
            return

        rows = [
            ("Title", local.get("title", "")),
            ("Link name", local.get("name", "")),
            ("Sticker type", local.get("sticker_type", "")),
            ("Bot owner", local.get("operator_id", "")),
            ("Local emotes", str(local.get("emotes_count", 0))),
        ]

        # Show snapshot availability so the user knows recovery is possible.
        from ...core import ops as _ops
        index_path = self._dir.path() / "index.json"
        snaps = _ops.list_snapshots(index_path) if index_path.exists() else []
        if snaps:
            rows.append(("Snapshots", f"{len(snaps)} (newest: {snaps[0].name})"))
            self._restore_btn.setEnabled(True)
            self._restore_btn.setToolTip(
                f"Restore the latest snapshot ({snaps[0].name}) into stickers/.\n"
                f"{len(snaps)} snapshot(s) available."
            )
        else:
            rows.append(("Snapshots", "<i style='color:#7c8794'>none</i>"))
            self._restore_btn.setEnabled(False)

        if cloud is not None:
            rows += [
                ("Cloud title", cloud.get("title", "")),
                ("Cloud count", str(cloud.get("count", 0))),
                (
                    "Cloud link",
                    f"<a href='{cloud.get('link','')}'>{cloud.get('link','')}</a>",
                ),
            ]
        else:
            rows.append(("Cloud", "<i style='color:#f0b429'>not created yet</i>"))

        html = "<table cellspacing='6' style='color:#c9d1d9'>"
        for k, v in rows:
            html += (
                f"<tr><td style='color:#7c8794; padding-right:14px'>{k}</td>"
                f"<td>{v}</td></tr>"
            )
        html += "</table>"
        self._summary_label.setText(html)

        # pretty-print the raw json
        try:
            raw = (self._dir.path() / "index.json").read_text(encoding="utf-8")
            parsed = json.loads(raw)
            self._raw_view.setPlainText(json.dumps(parsed, indent=2, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            self._raw_view.setPlainText(f"<could not read index.json: {e}>")

    def _on_err(self, exc: BaseException) -> None:
        self._summary_label.setText(
            f"<span style='color:#ff6b6b'>●</span> Failed: {exc}"
        )

    def _on_restore(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        target = self._dir.path()
        if not (target / "index.json").exists():
            QMessageBox.warning(self, "No index.json", "Pick a working directory first.")
            return
        confirm = QMessageBox.question(
            self, "Restore snapshot",
            "This will REPLACE the current stickers/ folder with the latest snapshot.\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self.busy.emit(True)
        self.progress.emit(0, 0, "Restoring snapshot…")

        async def _do():
            return await ops.op_restore_snapshot(target_dir=target, log=self.log.emit)

        def _done():
            self.busy.emit(False)
            self._on_refresh()  # reload the panel

        AsyncJobRunner(
            _do,
            on_success=lambda ok: self.log.emit(
                "ok" if ok else "warn",
                "Snapshot restored." if ok else "No snapshot to restore.",
            ),
            on_error=lambda e: self.log.emit("err", f"Restore failed: {e}"),
            on_finished=_done,
        ).start()
