"""Init tab — initialise a new local sticker pack directory."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ...core import ops
from ...gui.async_bridge import AsyncJobRunner
from ...gui.widgets.common import DirectoryPicker, OperationCard

# Telegram pack_name rules: latin letters, digits, underscores; can't start with a digit.
_PACK_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")


class InitTab(QWidget):
    """Tab letting the user create a new sticker pack working directory."""

    log = Signal(str, str)  # (level, message)
    progress = Signal(int, int, str)  # (current, total, message)
    busy = Signal(bool)  # True when an operation is running

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        title = QLabel("Initialise a new pack")
        title.setObjectName("h1")
        root.addWidget(title)

        intro = QLabel(
            "Creates <code>&lt;workdir&gt;/&lt;pack_name&gt;/</code> with an "
            "<code>index.json</code> and an empty <code>stickers/</code> folder. "
            "Drop images into <code>stickers/</code> and run “Push”."
        )
        intro.setObjectName("hint")
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._dir = DirectoryPicker(label="Working directory (where the pack folder will be created)")
        self._dir.setToolTip(
            "Choose where the new pack folder will be created.\n"
            "A new subfolder named after your pack will appear here."
        )
        root.addWidget(self._dir)

        self._card = OperationCard(
            title="Pack settings",
            description=(
                "Pack name: ONLY latin letters, digits and underscores (a-z, A-Z, 0-9, _). "
                "No spaces, no Cyrillic, no @. Example: my_cats_2025"
            ),
        )

        self._name = QLineEdit()
        self._name.setPlaceholderText("my_pack  (latin letters, digits, _ only)")
        self._name.setToolTip(
            "Pack name — used in the Telegram link (t.me/addstickers/<name>_by_<bot>).\n"
            "Rules:\n"
            "  • Only latin letters (a-z, A-Z), digits (0-9) and underscore (_)\n"
            "  • Cannot start with a digit\n"
            "  • No spaces, no Cyrillic, no @, no special chars\n"
            "Examples: my_cats, meme_pack_2025, test1\n"
            "Bad: Бубенище, my pack, pack@bot"
        )
        self._name.textChanged.connect(self._validate_name_live)

        # Debounced async check: does this pack name already exist on Telegram?
        self._name_check_timer = QTimer(self)
        self._name_check_timer.setSingleShot(True)
        self._name_check_timer.timeout.connect(self._check_name_availability)
        self._name_check_timer.setInterval(800)  # ms

        self._name_hint = QLabel("")
        self._name_hint.setObjectName("hint")
        self._name_hint.setWordWrap(True)

        self._title = QLineEdit()
        self._title.setPlaceholderText("My Sticker Pack  (any language, 1-64 chars)")
        self._title.setToolTip(
            "Pack title — the human-readable name shown in Telegram.\n"
            "Any language is OK (Russian, English, etc.). 1-64 characters."
        )

        self._type = QComboBox()
        self._type.addItems(["regular", "mask", "custom_emoji"])
        self._type.setToolTip(
            "regular — normal stickers (default)\n"
            "mask — mask stickers (overlay on faces)\n"
            "custom_emoji — custom emoji pack (requires premium to use)"
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.addRow("Pack name", self._name)
        form.addRow("", self._name_hint)
        form.addRow("Pack title", self._title)
        form.addRow("Sticker type", self._type)
        self._card.add_body_layout(form)

        self._init_btn = self._card.primary_action("Initialise", self._on_init)
        root.addWidget(self._card)

        root.addStretch(1)

    # ---------------------------------------------------------------------
    def _validate_name_live(self, text: str) -> None:
        """Live-validate pack name and show a hint below the field."""
        text = text.strip()
        if not text:
            self._name_hint.setText("")
            self._name_hint.setStyleSheet("color: #7c8794;")
            self._name_check_timer.stop()
            return
        if not _PACK_NAME_RE.match(text):
            self._name_hint.setText(
                "✗ Only latin letters (a-z), digits (0-9) and underscore (_) allowed. "
                "No spaces, no Cyrillic, no @."
            )
            self._name_hint.setStyleSheet("color: #ff6b6b;")
            self._name_check_timer.stop()
            return
        if text[0].isdigit():
            self._name_hint.setText("✗ Can't start with a digit.")
            self._name_hint.setStyleSheet("color: #ff6b6b;")
            self._name_check_timer.stop()
            return
        # Valid name format — schedule an async availability check.
        self._name_hint.setText("✓ Valid name format. Checking Telegram availability…")
        self._name_hint.setStyleSheet("color: #f0b429;")
        self._name_check_timer.start()

    def _check_name_availability(self) -> None:
        """Async probe: does this pack name already exist on Telegram?

        Runs only if the user is logged in. Updates _name_hint with the result.
        """
        name = self._name.text().strip()
        if not name or not _PACK_NAME_RE.match(name) or name[0].isdigit():
            return

        creds = ops.get_credentials()
        if creds is None:
            # Not logged in — skip the cloud check, just show format-OK.
            self._name_hint.setText(
                "✓ Valid name. Pack link will be: t.me/addstickers/" + name + "_by_<bot>"
                "\n(Log in to check if the name is free on Telegram.)"
            )
            self._name_hint.setStyleSheet("color: #7ee787;")
            return

        full_name = name if "_by_" in name else f"{name}_by_{creds.bot_user.username}"

        async def _do():
            from ...utils import make_bot
            bot = make_bot(creds)
            try:
                from ...utils import limited_request
                existing = await limited_request(bot.get_sticker_set(full_name))
                return ("taken", existing.title, len(existing.stickers))
            except Exception as e:  # noqa: BLE001
                if "STICKERSET_INVALID" in str(e):
                    return ("free", None, 0)
                return ("error", str(e), 0)

        def _on_success(result):
            status, title, count = result
            if status == "taken":
                self._name_hint.setText(
                    f"⚠ Name ALREADY TAKEN on Telegram: '{title}' ({count} stickers).\n"
                    f"Use the Download tab → 'Trace' to import it, or pick another name."
                )
                self._name_hint.setStyleSheet("color: #f0b429;")
            elif status == "free":
                self._name_hint.setText(
                    "✓ Valid name and FREE on Telegram. Pack link will be: "
                    "t.me/addstickers/" + full_name
                )
                self._name_hint.setStyleSheet("color: #7ee787;")
            else:
                self._name_hint.setText(
                    f"✓ Valid name. (Could not check Telegram: {title})"
                )
                self._name_hint.setStyleSheet("color: #7ee787;")

        AsyncJobRunner(_do, on_success=_on_success).start()

    # ---------------------------------------------------------------------
    def _on_init(self) -> None:
        name = self._name.text().strip()
        title = self._title.text().strip()

        if not name:
            QMessageBox.warning(
                self, "Missing pack name",
                "Pack name is required.\n\n"
                "Rules:\n"
                "  • Only latin letters (a-z, A-Z), digits (0-9) and underscore (_)\n"
                "  • Cannot start with a digit\n"
                "  • No spaces, no Cyrillic, no @\n\n"
                "Example: my_cats",
            )
            return
        if not _PACK_NAME_RE.match(name):
            QMessageBox.warning(
                self, "Invalid pack name",
                f"Pack name '{name}' is invalid.\n\n"
                "Pack name rules:\n"
                "  • Only latin letters (a-z, A-Z), digits (0-9) and underscore (_)\n"
                "  • Cannot start with a digit\n"
                "  • NO spaces, NO Cyrillic, NO @, NO special characters\n\n"
                "Examples of valid names:\n"
                "  my_cats\n"
                "  meme_pack_2025\n"
                "  Test1\n\n"
                "Bad names:\n"
                "  Бубенище  (Cyrillic not allowed)\n"
                "  my pack   (space not allowed)\n"
                "  pack@bot  (@ not allowed)\n"
                "  1pack     (can't start with digit)",
            )
            return
        if name[0].isdigit():
            QMessageBox.warning(
                self, "Invalid pack name",
                f"Pack name '{name}' can't start with a digit.\n"
                "Use a letter or underscore first. Example: pack1, _1pack.",
            )
            return
        if not title:
            QMessageBox.warning(self, "Missing title", "Pack title is required.")
            return
        if not (1 <= len(title) <= 64):
            QMessageBox.warning(
                self, "Invalid title",
                f"Title length must be between 1 and 64 characters (now {len(title)}).",
            )
            return

        sticker_type = self._type.currentText()
        target = self._dir.path()

        self._card.set_busy(True)
        self.busy.emit(True)
        self.progress.emit(0, 0, "Initialising pack…")

        async def _do():
            await ops.op_init(
                pack_name=name,
                pack_title=title,
                sticker_type=sticker_type,
                target_dir=target,
                log=self.log.emit,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
            )

        def _done():
            self._card.set_busy(False)
            self.busy.emit(False)

        AsyncJobRunner(
            _do,
            on_error=lambda e: self.log.emit("err", f"Init failed: {e}"),
            on_finished=_done,
        ).start()
