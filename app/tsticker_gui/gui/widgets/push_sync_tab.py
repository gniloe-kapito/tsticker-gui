"""Push / Sync tab — the main "apply changes" workflow.

Features:
* Drag-and-drop image files directly onto the tab to copy them into the
  pack's ``stickers/`` folder.
* Live thumbnail grid of the local stickers folder (auto-refreshes on
  push/sync/drop).
* "Open folder" button to jump straight to the stickers directory.
* Remembers the last used working directory between launches (QSettings).
"""

from __future__ import annotations

import pathlib
import shutil

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core import ops
from ...core.emoji_store import get_emoji_override, set_emoji_override, count_overrides
from ...gui.async_bridge import AsyncJobRunner
from ...gui.widgets.common import DirectoryPicker, OperationCard
from ...gui.widgets.emoji_dialog import EmojiPickerDialog

# Image extensions we accept for drag-and-drop.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".webm", ".mov", ".mp4", ".tgs"}


def _draw_emoji_badge(pixmap: QPixmap, emojis: list[str]) -> QPixmap:
    """Draw up to 3 emoji as a badge in the bottom-right of a thumbnail.

    The badge has a semi-transparent dark rounded-rect background so the emoji
    are readable over any image. This makes it obvious at a glance which
    stickers have a custom emoji override set.
    """
    if pixmap.isNull() or not emojis:
        return pixmap
    pm = pixmap.copy()
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Pick a colour-emoji font.
    import sys as _sys
    families = (
        ["Segoe UI Emoji"] if _sys.platform == "win32"
        else (["Apple Color Emoji"] if _sys.platform == "darwin"
              else ["Noto Color Emoji", "Segoe UI Emoji"])
    )
    font = QFont()
    font.setFamily(families[0])
    font.setPointSize(11)
    font.setBold(True)
    painter.setFont(font)

    badge_text = "".join(emojis[:3])
    # Measure the text so we can size the background rectangle.
    fm = painter.fontMetrics()
    tw = fm.horizontalAdvance(badge_text)
    th = fm.height()
    pad_x, pad_y = 5, 2
    rect_w = tw + pad_x * 2
    rect_h = th + pad_y * 2
    # Position: bottom-right, 3px margin.
    from PySide6.QtCore import QRectF

    rx = pm.width() - rect_w - 3
    ry = pm.height() - rect_h - 3
    rect = QRectF(rx, ry, rect_w, rect_h)

    # Draw a rounded translucent dark background.
    painter.setBrush(QColor(0, 0, 0, 180))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(rect, 6, 6)

    # Draw the emoji text centred in the rect.
    painter.setPen(QColor(255, 255, 255, 255))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, badge_text)
    painter.end()
    return pm


class StickerThumbList(QListWidget):
    """A grid of sticker thumbnails with drag-and-drop support."""

    files_dropped = Signal(list)  # list[pathlib.Path]
    sticker_double_clicked = Signal(str)  # file stem

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(96, 96))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(8)
        self.setUniformItemSizes(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.setStyleSheet(
            """
            QListWidget {
                background-color: #0f1115;
                border: 1px dashed #2a3138;
                border-radius: 8px;
                padding: 8px;
                outline: 0;
            }
            QListWidget::item {
                background: #161a1f;
                border: 1px solid #1c2127;
                border-radius: 6px;
                padding: 4px;
                color: #c9d1d9;
            }
            QListWidget::item:selected {
                background: #134e4a;
                border-color: #14b8a6;
                color: #ffffff;
            }
            """
        )
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # --- drag and drop ---------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths: list[pathlib.Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            p = pathlib.Path(local)
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
                paths.append(p)
            elif p.is_dir():
                for child in p.iterdir():
                    if child.is_file() and child.suffix.lower() in _IMAGE_EXTS:
                        paths.append(child)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_item_double_clicked(self, item) -> None:  # noqa: N802 - Qt naming
        """Emit the file stem (no extension) of the double-clicked sticker."""
        stem = item.data(Qt.ItemDataRole.UserRole)
        if not stem:
            import pathlib as _p
            stem = _p.Path(item.text()).stem
        self.sticker_double_clicked.emit(stem)


class PushSyncTab(QWidget):
    """Main push/sync workflow tab with sticker preview and drag-and-drop."""

    log = Signal(str, str)  # (level, message)
    progress = Signal(int, int, str)  # (current, total, message)
    busy = Signal(bool)  # True when an operation is running

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Push & Sync")
        title.setObjectName("h1")
        root.addWidget(title)

        intro = QLabel(
            "<b>Push</b> uploads your local <code>stickers/</code> folder to Telegram. "
            "<b>Sync</b> does the reverse — downloads cloud stickers back to local. "
            "You can <b>drag image files</b> directly into the sticker grid below."
        )
        intro.setObjectName("hint")
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        root.addWidget(intro)

        # --- working directory picker (remembers last) --------------------
        from PySide6.QtCore import QSettings

        self._settings = QSettings("tsticker-gui", "push-sync")
        self._dir = DirectoryPicker(label="Working directory (must contain index.json)")
        last = self._settings.value("lastDir", "", type=str)
        if last and pathlib.Path(last).exists():
            self._dir.set_path(last)
        self._dir.changed.connect(self._on_dir_changed)
        root.addWidget(self._dir)

        # --- sticker preview grid -----------------------------------------
        preview_card = OperationCard(
            title="Local stickers",
            description="Drop new image files here, or use the “Add files…” button. "
            "Thumbnails refresh automatically.",
        )

        self._thumbs = StickerThumbList()
        self._thumbs.files_dropped.connect(self._on_files_dropped)
        self._thumbs.sticker_double_clicked.connect(self._on_sticker_double_click)
        self._thumbs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._thumbs.customContextMenuRequested.connect(self._on_context_menu)
        preview_card.add_body_widget(self._thumbs)

        # row of actions below the grid
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        from PySide6.QtWidgets import QPushButton

        self._add_btn = QPushButton("Add files…")
        self._add_btn.clicked.connect(self._on_add_files)
        actions_row.addWidget(self._add_btn)

        self._emoji_btn = QPushButton("Set emoji…")
        self._emoji_btn.setObjectName("primary")
        self._emoji_btn.setToolTip(
            "Assign one or more emoji to the selected sticker(s).\n"
            "Double-clicking a sticker also opens this dialog.\n"
            "Assigned emoji are used at Push time instead of any emoji in the file name."
        )
        self._emoji_btn.clicked.connect(self._on_set_emoji)
        actions_row.addWidget(self._emoji_btn)

        self._import_emoji_btn = QPushButton("Import emoji…")
        self._import_emoji_btn.setToolTip(
            "Load an emoji mapping from a .json file and merge it into this pack.\n"
            "Useful for copying emoji assignments between packs.\n"
            "Format: {\"sticker_stem\": [\"emoji1\", \"emoji2\", ...], ...}"
        )
        self._import_emoji_btn.clicked.connect(self._on_import_emoji)
        actions_row.addWidget(self._import_emoji_btn)

        self._export_emoji_btn = QPushButton("Export emoji…")
        self._export_emoji_btn.setToolTip(
            "Save this pack's emoji mapping to a .json file.\n"
            "You can then import it into another pack."
        )
        self._export_emoji_btn.clicked.connect(self._on_export_emoji)
        actions_row.addWidget(self._export_emoji_btn)

        self._open_folder_btn = QPushButton("Open stickers folder")
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        actions_row.addWidget(self._open_folder_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._refresh_preview)
        actions_row.addWidget(self._refresh_btn)

        self._clear_btn = QPushButton("Remove selected")
        self._clear_btn.setObjectName("danger")
        self._clear_btn.clicked.connect(self._on_remove_selected)
        actions_row.addWidget(self._clear_btn)

        actions_row.addStretch(1)

        self._count_label = QLabel("0 stickers")
        self._count_label.setObjectName("hint")
        actions_row.addWidget(self._count_label)

        # insert actions row into the card body
        preview_card.add_body_layout(actions_row)
        root.addWidget(preview_card, 1)

        # --- push & sync side-by-side cards -------------------------------
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        self._push_card = OperationCard(
            title="Push to Telegram",
            description="Uploads new stickers, deletes removed ones, fixes mismatches.",
        )
        self._push_card.primary_action("Push now", self._on_push)
        bottom_row.addWidget(self._push_card)

        self._sync_card = OperationCard(
            title="Sync from Telegram",
            description="Downloads every cloud sticker into your local folder.",
        )
        self._sync_card.primary_action("Sync now", self._on_sync)
        bottom_row.addWidget(self._sync_card)

        # --- emoji-sync card (changes emoji on already-uploaded stickers) ---
        self._emoji_sync_card = OperationCard(
            title="Sync emoji to Telegram",
            description=(
                "Updates the emoji of stickers that are ALREADY in Telegram — "
                "no re-upload needed. For every sticker where you used "
                "“Set emoji…”, this calls Telegram’s setStickerEmojiList. "
                "Use this when you already pushed a pack and only want to change "
                "the emoji on some stickers."
            ),
        )
        self._emoji_sync_card.primary_action("Sync emoji now", self._on_emoji_sync)
        bottom_row.addWidget(self._emoji_sync_card)

        root.addLayout(bottom_row)

        # initial preview
        self._refresh_preview()

    # ---------------------------------------------------------------------
    # directory change
    # ---------------------------------------------------------------------
    def _on_dir_changed(self, new_dir: str) -> None:
        self._settings.setValue("lastDir", new_dir)
        self._refresh_preview()

    # ---------------------------------------------------------------------
    # sticker preview
    # ---------------------------------------------------------------------
    def _stickers_dir(self) -> pathlib.Path | None:
        target = self._dir.path()
        index = target / "index.json"
        if not index.exists():
            return None
        return target / "stickers"

    def _refresh_preview(self) -> None:
        self._thumbs.clear()
        stickers_dir = self._stickers_dir()
        if stickers_dir is None or not stickers_dir.exists():
            self._count_label.setText("no index.json — open the Init tab first")
            return
        # Load emoji overrides once so we can badge each thumbnail.
        pack_dir = stickers_dir.parent
        overrides = {}
        try:
            from ...core.emoji_store import load_emoji_overrides
            overrides = load_emoji_overrides(pack_dir)
        except Exception:  # noqa: BLE001 - preview must never crash
            overrides = {}
        files = sorted(
            [f for f in stickers_dir.iterdir() if f.is_file() and f.suffix.lower() in _IMAGE_EXTS],
            key=lambda f: f.name.lower(),
        )
        for f in files:
            stem = f.stem
            override = overrides.get(stem)
            # Show assigned emoji as a prefix badge on the label, if any.
            if override:
                label = f"{''.join(override[:3])} {f.name}"
            else:
                label = f.name
            item = QListWidgetItem(label)
            item.setToolTip(
                f"{f.name}\n{f.stat().st_size // 1024} KB\n"
                + (f"Emoji: {' '.join(override)}" if override else "Emoji: (from file name)")
            )
            # load thumbnail (cheap for static images; for video just show icon)
            pm = QPixmap(str(f))
            if not pm.isNull():
                icon_pm = pm.scaled(
                    96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                # If there's an emoji override, draw it as a badge on the icon
                # so the user can see at a glance which stickers have custom emoji.
                if override:
                    icon_pm = _draw_emoji_badge(icon_pm, override)
                item.setIcon(icon_pm)
            # Store the stem as userData for easy retrieval on double-click.
            item.setData(Qt.ItemDataRole.UserRole, stem)
            self._thumbs.addItem(item)
        n = len(files)
        n_emoji = len(overrides)
        suffix = ""
        if n_emoji:
            suffix = f"  •  {n_emoji} with custom emoji"
        self._count_label.setText(f"{n} sticker{'s' if n != 1 else ''}{suffix}")

        # Update the emoji-sync card description so the user knows how many
        # overrides are pending and ready to push to Telegram.
        if hasattr(self, "_emoji_sync_card"):
            if n_emoji:
                self._emoji_sync_card._desc.setText(
                    f"{n_emoji} sticker(s) have custom emoji ready to sync. "
                    f"Click to update their emoji in Telegram (no re-upload)."
                )
            else:
                self._emoji_sync_card._desc.setText(
                    "No custom emoji assigned yet. Double-click a sticker "
                    "to set emoji, then click here to push it to Telegram."
                )

    # ---------------------------------------------------------------------
    # add / drop / remove
    # ---------------------------------------------------------------------
    def _on_files_dropped(self, paths: list[pathlib.Path]) -> None:
        self._copy_into_stickers(paths)

    def _on_add_files(self) -> None:
        stickers_dir = self._stickers_dir()
        if stickers_dir is None:
            QMessageBox.warning(
                self, "No working pack",
                "Pick a directory that contains index.json first (Init tab).",
            )
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select sticker images", str(pathlib.Path.home()),
            "Images & videos (*.png *.jpg *.jpeg *.gif *.webp *.webm *.mov *.mp4);;All files (*)",
        )
        if not files:
            return
        self._copy_into_stickers([pathlib.Path(f) for f in files])

    def _copy_into_stickers(self, paths: list[pathlib.Path]) -> None:
        stickers_dir = self._stickers_dir()
        if stickers_dir is None:
            QMessageBox.warning(
                self, "No working pack",
                "Pick a directory that contains index.json first (Init tab).",
            )
            return
        stickers_dir.mkdir(exist_ok=True)
        added = 0
        for src in paths:
            dst = stickers_dir / src.name
            if dst.exists():
                # Don't silently overwrite — log it.
                self.log.emit("warn", f"Skipped (already exists): {src.name}")
                continue
            try:
                shutil.copy2(src, dst)
                added += 1
            except OSError as e:
                self.log.emit("err", f"Failed to copy {src.name}: {e}")
        if added:
            self.log.emit("ok", f"Copied {added} file(s) into stickers/")
        self._refresh_preview()

    def _on_remove_selected(self) -> None:
        items = self._thumbs.selectedItems()
        if not items:
            QMessageBox.information(self, "Nothing selected", "Select stickers to remove first.")
            return
        if QMessageBox.question(
            self, "Remove stickers",
            f"Delete {len(items)} file(s) from the local stickers folder? "
            "(This does NOT affect Telegram — run Push afterwards to delete them there.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        stickers_dir = self._stickers_dir()
        if stickers_dir is None:
            return
        for it in items:
            target = stickers_dir / it.text()
            try:
                target.unlink(missing_ok=True)
                self.log.emit("ok", f"Removed local: {it.text()}")
            except OSError as e:
                self.log.emit("err", f"Failed to remove {it.text()}: {e}")
        self._refresh_preview()

    def _on_open_folder(self) -> None:
        stickers_dir = self._stickers_dir()
        if stickers_dir is None or not stickers_dir.exists():
            QMessageBox.information(self, "No folder", "No stickers folder exists yet for this pack.")
            return
        # Cross-platform "open in file manager"
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(stickers_dir)))

    # ---------------------------------------------------------------------
    # emoji assignment
    # ---------------------------------------------------------------------
    def _on_context_menu(self, pos) -> None:  # noqa: N802 - Qt naming
        """Right-click context menu on the sticker grid."""
        from PySide6.QtWidgets import QMenu

        item = self._thumbs.itemAt(pos)
        menu = QMenu(self._thumbs)
        act_set_emoji = menu.addAction("Set emoji…")
        act_set_emoji.setToolTip("Assign emoji to the selected sticker(s)")
        menu.addSeparator()
        act_open = menu.addAction("Open stickers folder")
        act_refresh = menu.addAction("Refresh")
        if item is None:
            # Right-click on empty space — only folder/refresh make sense.
            act_set_emoji.setEnabled(False)
        chosen = menu.exec(self._thumbs.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_set_emoji:
            # Make sure the item under the cursor is selected before opening the dialog.
            if item is not None and item not in self._thumbs.selectedItems():
                self._thumbs.clearSelection()
                item.setSelected(True)
            self._on_set_emoji()
        elif chosen is act_open:
            self._on_open_folder()
        elif chosen is act_refresh:
            self._refresh_preview()

    def _pack_dir(self) -> pathlib.Path | None:
        """The pack directory (parent of stickers/) that holds index.json."""
        target = self._dir.path()
        if not (target / "index.json").exists():
            return None
        return target

    def _on_sticker_double_click(self, stem: str) -> None:
        """Open the emoji picker for a single sticker (double-click)."""
        self._open_emoji_dialog([stem])

    def _on_set_emoji(self) -> None:
        """Open the emoji picker for the currently selected stickers."""
        items = self._thumbs.selectedItems()
        if not items:
            QMessageBox.information(
                self, "Nothing selected",
                "Select one or more stickers in the grid first, then click 'Set emoji…'.\n"
                "Tip: double-click a single sticker to edit its emoji quickly.",
            )
            return
        stems: list[str] = []
        for it in items:
            stem = it.data(Qt.ItemDataRole.UserRole)
            if not stem:
                stem = pathlib.Path(it.text()).stem
            stems.append(stem)
        self._open_emoji_dialog(stems)

    def _open_emoji_dialog(self, stems: list[str]) -> None:
        """Show the emoji picker for the given sticker stems.

        If multiple stickers are selected, the same emoji set is applied to all
        of them. The dialog pre-fills with the current override of the first
        sticker (if any).
        """
        pack_dir = self._pack_dir()
        if pack_dir is None:
            QMessageBox.warning(
                self, "No working pack",
                "Pick a directory that contains index.json first (Init tab).",
            )
            return

        # Pre-fill with the first sticker's current override.
        current: list[str] | None = None
        source_label = ""
        try:
            current = get_emoji_override(pack_dir, stems[0])
        except Exception:  # noqa: BLE001
            current = None

        # Also derive the filename-based emoji for the source label (informational).
        try:
            from ...utils import get_emojis_from_file_name
            fn_emojis = get_emojis_from_file_name(stems[0])
            if fn_emojis:
                source_label = f"From file name: {' '.join(fn_emojis)}"
        except Exception:  # noqa: BLE001
            pass

        if len(stems) == 1:
            title = stems[0]
        else:
            title = f"{len(stems)} selected stickers"

        dlg = EmojiPickerDialog(
            sticker_name=title,
            current_emojis=current,
            source_label=source_label,
            parent=self,
        )
        if dlg.exec() != EmojiPickerDialog.DialogCode.Accepted:
            return

        chosen = dlg.selected_emojis()
        # Apply to every selected sticker.
        applied = 0
        for stem in stems:
            try:
                set_emoji_override(pack_dir, stem, chosen)
                applied += 1
            except Exception as e:  # noqa: BLE001
                self.log.emit("err", f"Failed to save emoji for {stem}: {e}")

        if chosen:
            self.log.emit(
                "ok",
                f"Set emoji {' '.join(chosen)} for {applied} sticker(s). "
                f"They'll be used at Push time.",
            )
        else:
            self.log.emit(
                "info",
                f"Cleared custom emoji for {applied} sticker(s). "
                f"Filename-based emoji will be used at Push time.",
            )
        self._refresh_preview()

    # ---------------------------------------------------------------------
    # import / export emoji mapping
    # ---------------------------------------------------------------------
    def _on_export_emoji(self) -> None:
        """Save the current pack's emoji mapping to a user-chosen .json file."""
        import json as _json

        pack_dir = self._pack_dir()
        if pack_dir is None:
            QMessageBox.warning(
                self, "No working pack",
                "Pick a directory that contains index.json first (Init tab).",
            )
            return
        from ...core.emoji_store import load_emoji_overrides

        overrides = load_emoji_overrides(pack_dir)
        if not overrides:
            QMessageBox.information(
                self, "Nothing to export",
                "This pack has no custom emoji assignments yet.\n"
                "Set emoji on some stickers first.",
            )
            return
        default_name = f"{pack_dir.name}_emoji.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export emoji mapping", default_name,
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(overrides, f, ensure_ascii=False, indent=2)
            self.log.emit("ok", f"Exported {len(overrides)} emoji mapping(s) to {path}")
        except OSError as e:
            QMessageBox.critical(self, "Export failed", f"Could not write file:\n{e}")

    def _on_import_emoji(self) -> None:
        """Load an emoji mapping from a .json file and merge it into this pack."""
        import json as _json

        pack_dir = self._pack_dir()
        if pack_dir is None:
            QMessageBox.warning(
                self, "No working pack",
                "Pick a directory that contains index.json first (Init tab).",
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import emoji mapping", str(pathlib.Path.home()),
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
        except (OSError, _json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Import failed", f"Could not read file:\n{e}")
            return
        if not isinstance(data, dict):
            QMessageBox.critical(
                self, "Import failed",
                "File format is wrong: expected a JSON object "
                "{\"sticker_stem\": [\"emoji\", ...]}.",
            )
            return
        # Validate and clean.
        clean: dict[str, list[str]] = {}
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, list):
                continue
            emojis = [str(e) for e in v if isinstance(e, str)]
            if emojis:
                clean[k] = emojis
        if not clean:
            QMessageBox.information(self, "Nothing to import", "File contains no valid emoji entries.")
            return
        # Merge with existing overrides.
        from ...core.emoji_store import load_emoji_overrides, save_emoji_overrides

        existing = load_emoji_overrides(pack_dir)
        existing.update(clean)
        try:
            save_emoji_overrides(pack_dir, existing)
        except OSError as e:
            QMessageBox.critical(self, "Import failed", f"Could not save: {e}")
            return
        self.log.emit(
            "ok",
            f"Imported {len(clean)} emoji mapping(s). "
            f"Total now: {len(existing)}.",
        )
        self._refresh_preview()

    # ---------------------------------------------------------------------
    # push / sync
    # ---------------------------------------------------------------------
    def _on_push(self) -> None:
        target = self._dir.path()
        if not (target / "index.json").exists():
            QMessageBox.warning(
                self, "No index.json",
                f"{target} doesn't contain an index.json.\n"
                "Open the “Init” tab first or pick the right directory.",
            )
            return

        self._push_card.set_busy(True)
        self.busy.emit(True)
        self.progress.emit(0, 0, "Pushing to Telegram…")

        def confirm() -> bool:
            return bool(
                QMessageBox.question(
                    self, "Confirm large push",
                    "You're about to upload more than 30 stickers. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                ) == QMessageBox.StandardButton.Yes
            )

        async def _do():
            await ops.op_push(
                target_dir=target,
                log=self.log.emit,
                progress=lambda c, t, m: (
                    self._push_card.set_progress(c, t, m),
                    self.progress.emit(c, t, m),
                ),
                confirm=confirm,
            )

        def _done():
            self._push_card.set_busy(False)
            self.busy.emit(False)
            self._refresh_preview()

        AsyncJobRunner(
            _do,
            on_error=lambda e: self.log.emit("err", f"Push failed: {e}"),
            on_finished=_done,
        ).start()

    def _on_sync(self) -> None:
        target = self._dir.path()
        if not (target / "index.json").exists():
            QMessageBox.warning(
                self, "No index.json",
                f"{target} doesn't contain an index.json.\n"
                "Open the “Init” tab first or pick the right directory.",
            )
            return

        self._sync_card.set_busy(True)
        self.busy.emit(True)
        self.progress.emit(0, 0, "Syncing from Telegram…")

        async def _do():
            await ops.op_sync(
                target_dir=target,
                log=self.log.emit,
                progress=lambda c, t, m: (
                    self._sync_card.set_progress(c, t, m),
                    self.progress.emit(c, t, m),
                ),
            )

        def _done():
            self._sync_card.set_busy(False)
            self.busy.emit(False)
            self._refresh_preview()

        AsyncJobRunner(
            _do,
            on_error=lambda e: self.log.emit("err", f"Sync failed: {e}"),
            on_finished=_done,
        ).start()

    def _on_emoji_sync(self) -> None:
        """Push the locally-assigned emoji overrides to Telegram.

        This changes the emoji of stickers that are ALREADY in the cloud —
        no image re-upload. Uses Telegram's setStickerEmojiList.
        """
        target = self._dir.path()
        if not (target / "index.json").exists():
            QMessageBox.warning(
                self, "No index.json",
                f"{target} doesn't contain an index.json.\n"
                "Open the “Init” tab first or pick the right directory.",
            )
            return

        # Show how many overrides we're about to push.
        from ...core.emoji_store import load_emoji_overrides
        overrides = load_emoji_overrides(target)
        if not overrides:
            QMessageBox.information(
                self, "No emoji to sync",
                "You haven't assigned any custom emoji yet.\n"
                "Double-click a sticker (or select some and click “Set emoji…””) "
                "to assign emoji, then come back here.",
            )
            return

        confirm = QMessageBox.question(
            self, "Sync emoji to Telegram",
            f"This will update the emoji on {len(overrides)} sticker(s) that are "
            f"already in Telegram.\n\n"
            f"Stickers that exist locally but were never pushed will be skipped.\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._emoji_sync_card.set_busy(True)
        self.busy.emit(True)
        self.progress.emit(0, 0, "Syncing emoji to Telegram…")

        async def _do():
            return await ops.op_apply_emoji_to_cloud(
                target_dir=target,
                log=self.log.emit,
                progress=lambda c, t, m: (
                    self._emoji_sync_card.set_progress(c, t, m),
                    self.progress.emit(c, t, m),
                ),
            )

        def _done():
            self._emoji_sync_card.set_busy(False)
            self.busy.emit(False)

        AsyncJobRunner(
            _do,
            on_error=lambda e: self.log.emit("err", f"Emoji sync failed: {e}"),
            on_finished=_done,
        ).start()
