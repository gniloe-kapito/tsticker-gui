"""Core validation primitives and bot-user bootstrap."""

from __future__ import annotations

import re
from typing import Literal, Optional

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from telebot import TeleBot, apihelper
from telebot.types import User

from .create import Emote  # noqa: F401  (re-exported for convenience)
from .create import StickerIndexFile  # noqa: F401

StickerType = Literal["mask", "regular", "custom_emoji"]

_PACK_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")


class StickerValidateInput(BaseModel):
    """Validated user input used to initialise a new sticker pack."""

    pack_name: str
    pack_title: str
    sticker_type: StickerType
    needs_repainting: Optional[bool] = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @staticmethod
    def make_set_name(pack_name: str, username: str) -> str:
        """Append ``_by_<bot_username>`` if not already present."""
        if "_by_" in pack_name:
            return pack_name
        return f"{pack_name}_by_{username}"

    @field_validator("pack_name", mode="before")
    @classmethod
    def _validate_pack_name(cls, value: str) -> str:
        if not isinstance(value, str) or not _PACK_NAME_RE.match(value):
            raise ValueError(
                f"Invalid pack_name {value!r}: must match {_PACK_NAME_RE.pattern}"
            )
        if value[0].isdigit():
            raise ValueError(f"Invalid pack_name {value!r}: must not start with a digit")
        return value

    @field_validator("pack_title", mode="before")
    @classmethod
    def _validate_pack_title(cls, value: str) -> str:
        if not isinstance(value, str) or not (1 <= len(value) <= 64):
            raise ValueError("pack_title length must be between 1 and 64 characters")
        return value

    @model_validator(mode="after")
    def _validate_setting(self) -> "StickerValidateInput":
        if self.needs_repainting is not None and self.sticker_type != "custom_emoji":
            logger.warning("needs_repainting is only available for custom_emoji sticker type")
            self.needs_repainting = None
        return self


class AppInitError(Exception):
    """Raised when the Telegram bot can't be bootstrapped."""


def get_bot_user(bot_token: str, bot_proxy: str | None = None) -> User:
    """Validate the bot token by calling ``getMe``.

    :raises AppInitError: if the token is invalid or the bot has no username.
    """
    if bot_proxy:
        # telebot needs socks5h:// for DNS-resolving SOCKS proxies.
        proxy = bot_proxy.replace("socks5://", "socks5h://")
        apihelper.proxy = {"https": proxy}
    apihelper.CONNECT_TIMEOUT = 20
    bot = TeleBot(bot_token)
    try:
        me = bot.get_me()
        assert me.id, "Bot token is invalid"
        assert me.username, "Bot username is invalid"
    except AssertionError as e:
        raise AppInitError(str(e)) from e
    except Exception as e:
        if "404" in str(e):
            raise AppInitError("Bot token is invalid") from e
        raise AppInitError(str(e)) from e
    return me


__all__ = [
    "Emote",
    "StickerIndexFile",
    "StickerValidateInput",
    "StickerType",
    "AppInitError",
    "get_bot_user",
]
