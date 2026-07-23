"""Sticker index file model and lock-namespace utilities.

Mirrors the original `tsticker.core.create` module but uses modern Pydantic v2
idioms and is fully Python 3.13 compatible.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Literal

from pydantic import BaseModel, Field, model_validator

EmoteStickerType = Literal["mask", "regular", "custom_emoji"]


class Emote(BaseModel):
    """A single (emoji, file_id) pair stored in the local index."""

    emoji: str
    file_id: str


class StickerIndexFile(BaseModel):
    """Local index.json schema.

    Only ``title`` is meant to be edited by the user; the rest is integrity-locked
    via ``lock_ns`` to prevent tampering.
    """

    title: str
    name: str
    sticker_type: EmoteStickerType
    operator_id: str
    lock_ns: str
    emotes: list[Emote] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_lock_ns(self) -> "StickerIndexFile":
        expected = generate_lock_ns(
            bot_id=self.operator_id,
            name=self.name,
            sticker_type=self.sticker_type,
        )
        if not hmac.compare_digest(self.lock_ns, expected):
            raise ValueError("metadata has been tampered")
        return self

    @classmethod
    def create(
        cls,
        *,
        title: str,
        name: str,
        sticker_type: str,
        operator_id: str,
    ) -> "StickerIndexFile":
        lock_ns = generate_lock_ns(
            bot_id=operator_id, name=name, sticker_type=sticker_type
        )
        return cls(
            title=title,
            name=name,
            sticker_type=sticker_type,  # type: ignore[arg-type]
            operator_id=operator_id,
            lock_ns=lock_ns,
        )


def generate_lock_ns(*, bot_id: str, name: str, sticker_type: str) -> str:
    """HMAC-SHA256 lock namespace so that index fields can't be silently edited."""
    secret_key = bot_id.encode("utf-8")
    message = f"{name}:{sticker_type}".encode("utf-8")
    return hmac.new(secret_key, message, hashlib.sha256).hexdigest()
