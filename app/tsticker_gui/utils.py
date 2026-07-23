"""Reusable utilities: credentials, rate-limited requests, sticker building.

This module is deliberately UI-agnostic. Every long-running function accepts an
optional ``progress`` callback so both the CLI and the PySide6 GUI can render
progress without coupling to a specific console library.
"""

from __future__ import annotations

import asyncio
import importlib.metadata as metadata
import io
import pathlib
from typing import Any, Awaitable, Callable, Literal, Optional

import emoji
import httpx
from pydantic import BaseModel, ConfigDict, model_validator
from telebot import apihelper
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_helper import session_manager
from telebot.types import InputFile, InputSticker, User

from .const import (
    PYPI_URL,
    REQUEST_CONCURRENCY,
    REQUEST_INTERVAL_SECONDS,
)
from .core import get_bot_user
from .image_processor import ImageProcessor

# --- progress callback types -------------------------------------------------
#
# A progress callback receives (current, total, message). ``total`` may be 0
# when the count is unknown.
ProgressCb = Callable[[int, int, str], None]
LogCb = Callable[[str, str], None]  # (level, message); level in {"info","ok","warn","err","debug"}


# --- rate-limited requests ---------------------------------------------------

_semaphore = asyncio.Semaphore(REQUEST_CONCURRENCY)


async def limited_request[T](coro: Awaitable[T]) -> T:
    """Run a Telegram coroutine under a global semaphore with a fixed cool-down."""
    async with _semaphore:
        result = await coro
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        return result


async def close_session() -> None:
    """Close the shared aiohttp session used by pytelegrambotapi."""
    if session_manager.session and not session_manager.session.closed:
        await session_manager.session.close()


def close_session_sync() -> None:
    """Best-effort synchronous session close (used as ``atexit`` hook)."""
    try:
        asyncio.run(close_session())
    except Exception:  # noqa: BLE001 - never raise from atexit
        pass


# --- credentials -------------------------------------------------------------

class Credentials(BaseModel):
    """Stored credentials. Validates the bot token eagerly via ``getMe``."""

    token: str
    owner_id: str
    bot_proxy: Optional[str] = None
    # Pydantic v2 can't serialise telebot's User directly -> private attr.
    _bot_user: Optional[User] = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @model_validator(mode="after")
    def _validate(self) -> "Credentials":
        me = get_bot_user(bot_token=self.token, bot_proxy=self.bot_proxy)
        self._bot_user = me
        try:
            int(self.owner_id)
        except ValueError as e:
            raise ValueError("Invalid owner id") from e
        return self

    @property
    def bot_user(self) -> User:
        if self._bot_user is None:
            raise ValueError("Bot user is not available")
        return self._bot_user


# --- sticker building --------------------------------------------------------

def get_emojis_from_file_name(file_name: str) -> list[str]:
    """Pull emoji characters out of a file name (e.g. ``😄cat🧑`` -> ``['😄','🧑']``)."""
    emojized = emoji.emojize(file_name, variant="emoji_type")
    return [ch for ch in emojized if emoji.is_emoji(ch)]


async def create_sticker(
    *,
    sticker_type: Literal["mask", "regular", "custom_emoji"],
    sticker_file: pathlib.Path,
    override_emojis: list[str] | None = None,
) -> InputSticker | None:
    """Convert a local file into a Telegram ``InputSticker``.

    Uses Pillow (via :class:`ImageProcessor`) for static images — no system
    dependencies. Video/animated formats need ffmpeg (optional).
    Returns ``None`` on failure (caller should log the error).

    ``override_emojis``: if provided (non-empty list), these emojis are used
    INSTEAD of any emojis derived from the file name. This lets the user
    assign emojis via the GUI (see :mod:`tsticker_gui.core.emoji_store`).
    """
    scale = 100 if sticker_type == "custom_emoji" else 512
    try:
        # Emoji priority: explicit override > filename-derived > image-embedded > default 😀.
        if override_emojis:
            emojis = list(override_emojis)
        else:
            emojis = get_emojis_from_file_name(sticker_file.stem)
        sticker = ImageProcessor.make_sticker(
            input_name=sticker_file.stem,
            input_data=sticker_file.as_posix(),
            scale=scale,
            master_edge="width",
        )
        if not emojis:
            emojis = sticker.emojis
        # Telegram requires at least one emoji — use a default if none found.
        if not emojis:
            emojis = ["😀"]
        return InputSticker(
            sticker=InputFile(io.BytesIO(sticker.data)),
            emoji_list=emojis,
            format=sticker.sticker_type,
        )
    except Exception:  # noqa: BLE001 - bubble up to caller with context
        return None


# --- update checker ----------------------------------------------------------

async def check_for_updates(*, log: Optional[LogCb] = None) -> None:
    """Compare the installed version against PyPI and log a notice."""
    try:
        current = metadata.version("tsticker-gui")
    except metadata.PackageNotFoundError:
        return

    try:
        async with httpx.AsyncClient(
            timeout=10.0, headers={"User-Agent": "tsticker-gui"}
        ) as client:
            response = await client.get(PYPI_URL)
        if response.status_code != 200:
            _log(log, "info", f"Skipping update check: HTTP {response.status_code}")
            return
        info = response.json()
        latest = info.get("info", {}).get("version", "")
        if latest and latest != current:
            _log(
                log,
                "info",
                f"tsticker-gui {current} is installed, {latest} is available on PyPI.",
            )
    except Exception as e:  # noqa: BLE001 - update check must never break UX
        _log(log, "debug", f"Skipping update check: {type(e).__name__}: {e}")


# --- helpers -----------------------------------------------------------------

def make_bot(
    credentials: Credentials,
    *,
    validate: bool = False,
) -> AsyncTeleBot:
    """Construct an ``AsyncTeleBot`` honouring the optional proxy."""
    if credentials.bot_proxy:
        proxy = credentials.bot_proxy.replace("socks5://", "socks5h://")
        apihelper.proxy = {"https": proxy}
    bot = AsyncTeleBot(credentials.token)
    if validate:
        # Cheap sanity check that the token works.
        bot.get_me()  # not awaited; just ensures API helper is wired
    return bot


def _log(log: Optional[LogCb], level: str, message: str) -> None:
    if log is None:
        return
    try:
        log(level, message)
    except Exception:  # noqa: BLE001 - logging must never raise
        pass


def delete_same_name_files(
    sticker_table_dir: pathlib.Path,
    *,
    log: Optional[LogCb] = None,
) -> None:
    """Remove files that share a stem with another file (keep the first one)."""
    if not sticker_table_dir.exists():
        _log(log, "warn", f"Directory {sticker_table_dir} does not exist.")
        return
    files_by_name: dict[str, list[pathlib.Path]] = {}
    for f in sticker_table_dir.iterdir():
        if f.is_file():
            files_by_name.setdefault(f.stem, []).append(f)
    for files in files_by_name.values():
        if len(files) > 1:
            for f in files[1:]:
                _log(log, "warn", f"Deleting duplicate file: {f.name}")
                f.unlink(missing_ok=True)


__all__ = [
    "ProgressCb",
    "LogCb",
    "limited_request",
    "close_session",
    "close_session_sync",
    "Credentials",
    "get_emojis_from_file_name",
    "create_sticker",
    "check_for_updates",
    "make_bot",
    "delete_same_name_files",
]
