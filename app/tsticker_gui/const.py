"""Project-wide constants for tsticker-gui."""

from __future__ import annotations

PYPI_URL = "https://pypi.org/pypi/tsticker/json"
STICKER_DIR_NAME = "stickers"
SNAPSHOT_DIR_NAME = "snapshot"
SNAPSHOT_MAX_COUNT = 12

# Telegram API rate-limit safety: ~30 req/min => 2s between requests.
REQUEST_INTERVAL_SECONDS: float = 2.0
REQUEST_CONCURRENCY: int = 20

# Pack constraints enforced by Telegram.
MAX_STICKERS_PER_PACK = 120
MAX_STICKERS_PER_CREATE = 30
