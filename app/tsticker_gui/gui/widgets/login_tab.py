"""Login / logout tab.

Wraps :func:`tsticker_gui.core.ops.save_credentials` /
:func:`tsticker_gui.core.ops.delete_credentials`. Because ``Credentials``
validates the token eagerly (it calls ``getMe``) we run the save in a worker
asyncio task and only flip the UI to "logged in" on success.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core import ops
from ...gui.async_bridge import AsyncJobRunner
from ...gui.widgets.common import OperationCard
from ...utils import Credentials


class LoginTab(QWidget):
    """Tab letting the user log in or out and showing the bot identity."""

    status_changed = Signal(bool)  # True if logged in

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        title = QLabel("Login to Telegram")
        title.setObjectName("h1")
        root.addWidget(title)

        intro = QLabel(
            "tsticker-gui needs a <b>bot token</b> (from @BotFather) and your "
            "<b>personal Telegram user id</b> (from @getidsbot). The bot can only "
            "manage sticker packs <i>it created itself</i>."
        )
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        # --- credentials form card ----------------------------------------
        self._card = OperationCard(
            title="Bot credentials",
            description="Your token is stored in the system keyring (never on disk in plaintext).",
        )

        self._token = QLineEdit()
        self._token.setPlaceholderText("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
        self._token.setEchoMode(QLineEdit.EchoMode.Password)
        self._token.setToolTip(
            "Bot token from @BotFather.\n"
            "Format: 1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11\n\n"
            "How to get it:\n"
            "  1. Open Telegram, find @BotFather\n"
            "  2. Send /newbot\n"
            "  3. Follow the prompts to name your bot\n"
            "  4. Copy the token it gives you"
        )

        self._user = QLineEdit()
        self._user.setPlaceholderText("Your personal Telegram user id (digits only)")
        self._user.setToolTip(
            "Your PERSONAL Telegram user id (not the bot id!).\n"
            "This is who will 'own' the sticker pack.\n\n"
            "How to get it:\n"
            "  1. Open Telegram, find @getidsbot\n"
            "  2. Send /my_id\n"
            "  3. Copy the number it replies with\n\n"
            "Must be digits only, e.g. 123456789"
        )

        self._proxy = QLineEdit()
        self._proxy.setPlaceholderText("Optional — e.g. socks5://127.0.0.1:1080 or http://…")
        self._proxy.setToolTip(
            "Optional proxy for the bot API.\n"
            "Formats:\n"
            "  socks5://host:port\n"
            "  http://host:port\n"
            "  https://host:port\n\n"
            "Leave empty if you don't use a proxy."
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.addRow("Bot token", self._token)
        form.addRow("User id", self._user)
        form.addRow("Proxy", self._proxy)
        self._card.add_body_layout(form)

        self._save_btn = self._card.primary_action("Save & log in", self._on_save)
        self._logout_btn = self._card.danger_action("Log out", self._on_logout)
        root.addWidget(self._card)

        # --- status card --------------------------------------------------
        self._status_card = OperationCard(
            title="Current session",
            description="Active bot identity, refreshed after every successful login.",
        )
        self._status_label = QLabel("Not logged in.")
        self._status_label.setWordWrap(True)
        self._status_label.setTextFormat(Qt.TextFormat.RichText)
        self._status_card.add_body_widget(self._status_label)
        root.addWidget(self._status_card)

        root.addStretch(1)

        self._refresh_status()

    # ---------------------------------------------------------------------
    def _refresh_status(self) -> None:
        creds = ops.get_credentials()
        if creds is None:
            self._status_label.setText(
                "<span style='color:#ff6b6b'>●</span> &nbsp;<b>Not logged in.</b><br>"
                "<span style='color:#7c8794'>Fill the form above and press “Save &amp; log in”.</span>"
            )
            self._save_btn.setEnabled(True)
            self._logout_btn.setEnabled(False)
            self.status_changed.emit(False)
            return
        try:
            user = creds.bot_user
            self._status_label.setText(
                f"<span style='color:#7ee787'>●</span> &nbsp;<b>Logged in</b> as bot "
                f"<span style='color:#2dd4bf'>@{user.username}</span> "
                f"({user.first_name}).<br>"
                f"<span style='color:#7c8794'>Owner id: {creds.owner_id}</span>"
            )
        except Exception:  # noqa: BLE001
            self._status_label.setText(
                "<span style='color:#f0b429'>●</span> &nbsp;<b>Stored token is invalid.</b><br>"
                "<span style='color:#7c8794'>Please log in again.</span>"
            )
            self._save_btn.setEnabled(True)
            self._logout_btn.setEnabled(True)
            self.status_changed.emit(False)
            return
        self._save_btn.setEnabled(False)
        self._logout_btn.setEnabled(True)
        self.status_changed.emit(True)

    # ---------------------------------------------------------------------
    def _on_save(self) -> None:
        token = self._token.text().strip()
        user = self._user.text().strip()
        proxy = self._proxy.text().strip() or None
        if not token or not user:
            self._status_label.setText(
                "<span style='color:#ff6b6b'>●</span> &nbsp;Both token and user id are required."
            )
            return
        try:
            int(user)
        except ValueError:
            self._status_label.setText(
                "<span style='color:#ff6b6b'>●</span> &nbsp;User id must be numeric digits."
            )
            return

        self._card.set_busy(True)

        async def _do_save() -> Credentials:
            return ops.save_credentials(token=token, owner_id=user, bot_proxy=proxy)

        AsyncJobRunner(
            _do_save,
            on_success=self._on_save_ok,
            on_error=self._on_save_err,
            on_finished=lambda: self._card.set_busy(False),
        ).start()

    def _on_save_ok(self, creds: Credentials) -> None:
        self._token.clear()
        self._user.clear()
        self._proxy.clear()
        self._refresh_status()

    def _on_save_err(self, exc: BaseException) -> None:
        self._status_label.setText(
            f"<span style='color:#ff6b6b'>●</span> &nbsp;<b>Login failed:</b> {exc}"
        )

    # ---------------------------------------------------------------------
    def _on_logout(self) -> None:
        ops.delete_credentials()
        self._refresh_status()
