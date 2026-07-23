"""Download / Trace tab — fetch any cloud pack by link."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from ...core import ops
from ...gui.async_bridge import AsyncJobRunner
from ...gui.widgets.common import DirectoryPicker, OperationCard


class DownloadTab(QWidget):
    """Download (read-only) or trace (editable copy) a cloud pack by URL."""

    log = Signal(str, str)  # (level, message)
    progress = Signal(int, int, str)  # (current, total, message)
    busy = Signal(bool)  # True when an operation is running

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        title = QLabel("Download & Trace")
        title.setObjectName("h1")
        root.addWidget(title)

        intro = QLabel(
            "<b>Download</b> saves a read-only copy of any public pack into the chosen "
            "directory.<br><b>Trace</b> clones a pack created by your bot so you can edit it."
        )
        intro.setObjectName("hint")
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._dir = DirectoryPicker(label="Destination directory")
        self._dir.setToolTip(
            "Where to save the downloaded pack.\n"
            "A new subfolder named after the pack will be created here."
        )
        root.addWidget(self._dir)

        self._link = QLineEdit()
        self._link.setPlaceholderText("https://t.me/addstickers/SomePackName")
        self._link.setToolTip(
            "Full link to a Telegram sticker pack.\n"
            "Example: https://t.me/addstickers/MyCoolPack\n\n"
            "You can get this link by opening any sticker pack in Telegram\n"
            "and clicking the share button."
        )
        link_row_label = QLabel("Sticker pack link")
        link_row_label.setObjectName("hint")

        # --- download card -----------------------------------------------
        self._download_card = OperationCard(
            title="Download (read-only)",
            description="Just downloads the stickers. You can't push back changes from this folder.",
        )
        self._download_card.add_body_widget(link_row_label)
        self._download_card.add_body_widget(self._link)
        self._download_card.primary_action("Download", self._on_download)
        root.addWidget(self._download_card)

        # --- trace card --------------------------------------------------
        self._trace_card = OperationCard(
            title="Trace (editable)",
            description="Creates a working copy of a pack created by your bot, so you can edit & push.",
        )
        self._trace_card.primary_action("Trace", self._on_trace)
        root.addWidget(self._trace_card)

        root.addStretch(1)

    # ---------------------------------------------------------------------
    def _on_download(self) -> None:
        link = self._link.text().strip()
        if not link:
            QMessageBox.warning(self, "No link", "Paste a sticker pack link first (https://t.me/addstickers/...).")
            return
        if "t.me/addstickers/" not in link and "telegram.me/addstickers/" not in link:
            QMessageBox.warning(
                self, "Invalid link",
                f"The link doesn't look like a sticker pack URL.\n"
                f"It should be: https://t.me/addstickers/PackName\n\nGot: {link}",
            )
            return
        target = self._dir.path()
        self._download_card.set_busy(True)
        self.busy.emit(True)
        self.progress.emit(0, 0, "Downloading…")

        async def _do():
            await ops.op_download(
                link=link,
                target_dir=target,
                log=self.log.emit,
                progress=lambda c, t, m: (
                    self._download_card.set_progress(c, t, m),
                    self.progress.emit(c, t, m),
                ),
            )

        def _done():
            self._download_card.set_busy(False)
            self.busy.emit(False)

        AsyncJobRunner(
            _do,
            on_error=lambda e: self.log.emit("err", f"Download failed: {e}"),
            on_finished=_done,
        ).start()

    def _on_trace(self) -> None:
        link = self._link.text().strip()
        if not link:
            QMessageBox.warning(self, "No link", "Paste a sticker pack link first (https://t.me/addstickers/...).")
            return
        if "t.me/addstickers/" not in link and "telegram.me/addstickers/" not in link:
            QMessageBox.warning(
                self, "Invalid link",
                f"The link doesn't look like a sticker pack URL.\n"
                f"It should be: https://t.me/addstickers/PackName\n\nGot: {link}",
            )
            return
        target = self._dir.path()
        self._trace_card.set_busy(True)
        self.busy.emit(True)
        self.progress.emit(0, 0, "Tracing…")

        async def _do():
            await ops.op_trace(
                link=link,
                target_dir=target,
                log=self.log.emit,
                progress=lambda c, t, m: (
                    self._trace_card.set_progress(c, t, m),
                    self.progress.emit(c, t, m),
                ),
            )

        def _done():
            self._trace_card.set_busy(False)
            self.busy.emit(False)

        AsyncJobRunner(
            _do,
            on_error=lambda e: self.log.emit("err", f"Trace failed: {e}"),
            on_finished=_done,
        ).start()
