"""Per-sticker emoji override store.

Telegram stickers need at least one emoji each. By default we extract emojis
from the file name (see :func:`tsticker_gui.utils.get_emojis_from_file_name`),
but the user may want to assign emojis explicitly via the GUI — e.g. a sticker
named ``cat.png`` should get 🐱 even though the name has no emoji.

We persist these overrides in a sidecar JSON file next to ``index.json``:

    <pack_dir>/.sticker_emojis.json
    {
        "CAACAgIAA…": ["🐱", "😺"],   # keyed by file stem (file_unique_id)
        "photo_001": ["📷"]
    }

The file is read at push time and takes precedence over name-derived emojis.
If the user clears all emojis for a sticker, the entry is removed (so we fall
back to the filename/default behaviour).
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from typing import Optional

_SIDECAR_NAME = ".sticker_emojis.json"


def _sidecar_path(pack_dir: pathlib.Path) -> pathlib.Path:
    """Return the path to the emoji sidecar file for a pack directory."""
    return pack_dir / _SIDECAR_NAME


def load_emoji_overrides(pack_dir: pathlib.Path) -> dict[str, list[str]]:
    """Load the emoji override map. Returns ``{}`` if missing or corrupted.

    ``pack_dir`` is the folder that contains ``index.json`` (NOT the
    ``stickers/`` subfolder).
    """
    path = _sidecar_path(pack_dir)
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        # Validate: every value must be a list of strings.
        clean: dict[str, list[str]] = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if not isinstance(v, list):
                continue
            emojis = [str(e) for e in v if isinstance(e, str)]
            if emojis:
                clean[k] = emojis
        return clean
    except Exception:  # noqa: BLE001 - never crash on a sidecar read
        return {}


def save_emoji_overrides(pack_dir: pathlib.Path, overrides: dict[str, list[str]]) -> None:
    """Persist the emoji override map atomically (UTF-8)."""
    path = _sidecar_path(pack_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: temp file in same dir, then os.replace.
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{_SIDECAR_NAME}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(overrides, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_emoji_override(
    pack_dir: pathlib.Path, sticker_stem: str
) -> Optional[list[str]]:
    """Return the user-assigned emojis for a sticker stem, or ``None``.

    ``None`` means "no override — fall back to filename/default behaviour".
    An empty list would mean "user explicitly cleared" — but we treat that the
    same as no override (we never persist empty lists, see load_emoji_overrides).
    """
    overrides = load_emoji_overrides(pack_dir)
    return overrides.get(sticker_stem)


def set_emoji_override(
    pack_dir: pathlib.Path, sticker_stem: str, emojis: list[str]
) -> None:
    """Set (or clear, if ``emojis`` is empty) the override for one sticker."""
    overrides = load_emoji_overrides(pack_dir)
    if emojis:
        overrides[sticker_stem] = list(emojis)
    else:
        overrides.pop(sticker_stem, None)
    save_emoji_overrides(pack_dir, overrides)


def count_overrides(pack_dir: pathlib.Path) -> int:
    """How many stickers have an explicit emoji override (for UI display)."""
    return len(load_emoji_overrides(pack_dir))


__all__ = [
    "load_emoji_overrides",
    "save_emoji_overrides",
    "get_emoji_override",
    "set_emoji_override",
    "count_overrides",
]
