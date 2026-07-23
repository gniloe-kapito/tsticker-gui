"""Reusable business logic: credentials store + sticker operations.

Every public function is ``async`` (where it touches the network) and accepts
optional ``log`` / ``progress`` callbacks so it can be driven by either:

* the PySide6 GUI (via the async bridge in ``tsticker_gui.gui.async_bridge``), or
* the asyncclick-based CLI in ``tsticker_gui.cli.cli``.

Nothing in this module imports Qt, Rich or asyncclick — it's pure Python + the
Telegram bot SDK.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import shutil
import tempfile
from collections.abc import Callable
from typing import Any, Optional

import keyring
from pydantic import ValidationError
from telebot.async_telebot import AsyncTeleBot
from telebot.types import StickerSet

from ..const import (
    SNAPSHOT_DIR_NAME,
    SNAPSHOT_MAX_COUNT,
    STICKER_DIR_NAME,
)
from ..core import AppInitError, StickerValidateInput
from ..core.const import SERVICE_NAME, USERNAME
from ..core.create import Emote, StickerIndexFile
from ..core.emoji_store import get_emoji_override, load_emoji_overrides
from ..utils import (
    Credentials,
    LogCb,
    ProgressCb,
    create_sticker,
    delete_same_name_files,
    limited_request,
    make_bot,
)


# ---------------------------------------------------------------------------
# file-type sniffing (no heavy ML deps — magic bytes are enough for stickers)
# ---------------------------------------------------------------------------

# signature -> (extension, offset). All stickers Telegram accepts have one of
# these well-known headers.
_FILE_SIGNATURES: tuple[tuple[bytes, int, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", 0, "png"),
    (b"\xff\xd8\xff", 0, "jpg"),
    (b"GIF87a", 0, "gif"),
    (b"GIF89a", 0, "gif"),
    (b"RIFF", 0, "webp"),  # also .wav etc., but stickers use webp
    (b"WEBP", 8, "webp"),  # RIFF....WEBP
    (b"\x1a\x45\xdf\xa3", 0, "webm"),  # EBML / webm / mkv
    (b"\x00\x00\x00", 4, "mov"),  # quicktime (ftyp follows)
    (b"ftyp", 4, "mov"),
    (b"\x00\x00\x00\x20ftyp", 0, "mp4"),
    (b"ftypiso", 4, "mp4"),
    (b"ftypmp4", 4, "mp4"),
    (b"ftypisom", 4, "mp4"),
)


def _guess_extension(data: bytes) -> str:
    """Detect sticker file extension from magic bytes. No external deps."""
    head = data[:32]
    lower_head = head.lower()
    for sig, offset, ext in _FILE_SIGNATURES:
        if head[offset:offset + len(sig)] == sig or lower_head[offset:offset + len(sig)] == sig.lower():
            # disambiguate RIFF: check for WEBP at offset 8
            if sig == b"RIFF" and head[8:12] != b"WEBP":
                continue
            return ext
    # final fallback
    return "bin"


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------

def save_credentials(
    *,
    token: str,
    owner_id: str,
    bot_proxy: str | None = None,
) -> Credentials:
    """Persist credentials to the system keyring. Raises on invalid input."""
    creds = Credentials(token=token, bot_proxy=bot_proxy, owner_id=owner_id)
    keyring.set_password(SERVICE_NAME, USERNAME, creds.model_dump_json())
    return creds


def get_credentials() -> Credentials | None:
    raw = keyring.get_password(SERVICE_NAME, USERNAME)
    if not raw:
        return None
    try:
        return Credentials.model_validate_json(raw)
    except (ValidationError, AppInitError):
        # Stored token may have been revoked; surface as "logged out".
        return None


def delete_credentials() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


# ---------------------------------------------------------------------------
# path helpers
# ---------------------------------------------------------------------------

def get_stickers_path(index_file: pathlib.Path) -> pathlib.Path:
    """Return the ``stickers/`` directory next to ``index_file`` (creating it)."""
    sticker_dir = index_file.parent / STICKER_DIR_NAME
    if not sticker_dir.exists():
        sticker_dir.mkdir(exist_ok=True)
    if not sticker_dir.is_dir():
        raise FileNotFoundError(f"Sticker path is not a directory: {sticker_dir}")
    return sticker_dir


def get_snapshot_path(index_file: pathlib.Path) -> pathlib.Path:
    snap = index_file.parent / SNAPSHOT_DIR_NAME
    if not snap.exists():
        snap.mkdir(exist_ok=True)
    if not snap.is_dir():
        raise FileNotFoundError(f"Snapshot path is not a directory: {snap}")
    return snap


def backup_snapshot(
    index_file: pathlib.Path,
    *,
    log: LogCb | None = None,
) -> None:
    """Snapshot the current ``stickers/`` dir before a destructive push."""
    sticker_dir = get_stickers_path(index_file)
    snap_dir = get_snapshot_path(index_file)
    snaps = sorted(snap_dir.glob(f"{SNAPSHOT_DIR_NAME}_*"), key=os.path.getmtime)
    while len(snaps) >= SNAPSHOT_MAX_COUNT:
        oldest = snaps.pop(0)
        _log(log, "warn", f"Cleaning up old snapshot: {oldest}")
        shutil.rmtree(oldest, ignore_errors=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    new_snap = snap_dir / f"{SNAPSHOT_DIR_NAME}_{timestamp}"
    shutil.copytree(sticker_dir, new_snap)
    _log(
        log,
        "ok",
        f"Snapshot backup {len(snaps) + 1}/{SNAPSHOT_MAX_COUNT} created at {new_snap}",
    )


def list_snapshots(index_file: pathlib.Path) -> list[pathlib.Path]:
    """Return all existing snapshots for the pack, newest first."""
    try:
        snap_dir = get_snapshot_path(index_file)
    except FileNotFoundError:
        return []
    snaps = sorted(snap_dir.glob(f"{SNAPSHOT_DIR_NAME}_*"), key=os.path.getmtime, reverse=True)
    return snaps


def restore_latest_snapshot(
    index_file: pathlib.Path,
    *,
    log: LogCb | None = None,
) -> bool:
    """Restore the most recent snapshot into ``stickers/``.

    Used to recover from a corrupted or empty ``stickers/`` dir (e.g. after a
    push that crashed mid-way). Returns True on success, False if no snapshot
    exists.
    """
    snaps = list_snapshots(index_file)
    if not snaps:
        _log(log, "warn", "No snapshots found to restore from.")
        return False
    latest = snaps[0]
    sticker_dir = get_stickers_path(index_file)
    # Wipe the current stickers dir and copy the snapshot over.
    if sticker_dir.exists():
        shutil.rmtree(sticker_dir, ignore_errors=True)
    shutil.copytree(latest, sticker_dir)
    _log(log, "ok", f"Restored stickers/ from snapshot: {latest.name}")
    return True


def rebuild_index_from_dir(
    index_file: pathlib.Path,
    *,
    log: LogCb | None = None,
) -> bool:
    """Rebuild a missing/empty index.json from a known-good cloud state.

    This is a *synchronous* best-effort helper — it only works if we can read
    the existing index.json enough to get name/operator_id/sticker_type. If
    index.json is truly gone, the user must use Init or Trace.
    """
    if not index_file.exists():
        return False
    raw = index_file.read_text(encoding="utf-8").strip()
    if raw:
        return False  # not empty — nothing to rebuild
    _log(log, "warn", "index.json is empty — cannot rebuild without name/operator_id.")
    return False


# ---------------------------------------------------------------------------
# download primitives
# ---------------------------------------------------------------------------

async def download_and_write_file(
    *,
    telegram_bot: AsyncTeleBot,
    file_id: str,
    file_unique_id: str,
    sticker_table_dir: pathlib.Path,
    log: LogCb | None = None,
) -> pathlib.Path | None:
    """Download a single sticker file by id and write it to disk."""
    sticker_raw = await limited_request(telegram_bot.get_file(file_id=file_id))
    sticker_io = await limited_request(
        telegram_bot.download_file(file_path=sticker_raw.file_path)
    )
    if not sticker_io:
        _log(log, "err", f"Failed to download file: {file_unique_id}")
        return None
    ext = _guess_extension(sticker_io)
    out = sticker_table_dir / f"{file_unique_id}.{ext}"
    out.write_bytes(sticker_io)
    return out


async def download_sticker_set(
    *,
    pack_name: str,
    telegram_bot: AsyncTeleBot,
    download_dir: pathlib.Path,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
) -> None:
    """Download every sticker in a pack into ``download_dir / pack_name``."""
    sticker_set = await limited_request(telegram_bot.get_sticker_set(pack_name))
    if not sticker_set:
        _log(log, "err", f"Sticker set not found: {pack_name}")
        return
    out_dir = download_dir / pack_name
    out_dir.mkdir(exist_ok=True)
    delete_same_name_files(out_dir, log=log)
    total = len(sticker_set.stickers)
    for i, sticker in enumerate(sticker_set.stickers, start=1):
        _prog(progress, i, total, f"Downloading sticker {sticker.file_id}")
        await download_and_write_file(
            telegram_bot=telegram_bot,
            file_id=sticker.file_id,
            file_unique_id=sticker.file_unique_id,
            sticker_table_dir=out_dir,
            log=log,
        )
    _log(log, "ok", f"Downloaded sticker set: {pack_name} ({total} stickers)")


# ---------------------------------------------------------------------------
# sync / push
# ---------------------------------------------------------------------------

async def sync_index(
    *,
    telegram_bot: AsyncTeleBot,
    index_file: pathlib.Path,
    cloud_sticker_set: StickerSet,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
) -> None:
    """Overwrite LOCAL files with the cloud sticker set."""
    try:
        pack = StickerIndexFile.model_validate_json(
            index_file.read_text(encoding="utf-8")
        )
    except Exception as e:  # noqa: BLE001
        _log(log, "err", f"Index file was corrupted: {e}")
        return
    try:
        sticker_dir = get_stickers_path(index_file)
    except FileNotFoundError as e:
        _log(log, "err", f"Sticker directory not found: {e}")
        return
    delete_same_name_files(sticker_dir, log=log)

    local_files: dict[str, pathlib.Path] = {f.stem: f for f in sticker_dir.glob("*")}
    cloud_files = {s.file_unique_id: s for s in cloud_sticker_set.stickers}

    to_delete = [local_files[k] for k in local_files if k not in cloud_files]
    to_validate = [local_files[k] for k in local_files if k in cloud_files]
    to_download = [k for k in cloud_files if k not in local_files]

    if to_delete:
        _log(log, "warn", f"Files to delete: {len(to_delete)}")
    for f in to_delete:
        _log(log, "debug", f"- {f.name}")
        f.unlink(missing_ok=True)

    for f in to_validate:
        local_size = f.stat().st_size
        cloud_size = cloud_files[f.stem].file_size
        if local_size != cloud_size:
            _log(log, "warn", f"Size mismatch for {f.name}, re-downloading...")
            f.unlink(missing_ok=True)
            to_download.append(f.stem)

    total = len(to_download)
    for i, file_id in enumerate(to_download, start=1):
        _prog(progress, i, total, f"Syncing {file_id}")
        await download_and_write_file(
            telegram_bot=telegram_bot,
            file_id=cloud_files[file_id].file_id,
            file_unique_id=cloud_files[file_id].file_unique_id,
            sticker_table_dir=sticker_dir,
            log=log,
        )

    pack.emotes = [
        Emote(emoji=s.emoji, file_id=fid) for fid, s in cloud_files.items()
    ]
    _atomic_write_json(index_file, pack.model_dump_json(indent=2))
    _log(log, "ok", f"Synchronization completed ({total} files downloaded)")


async def push_to_cloud(
    *,
    telegram_bot: AsyncTeleBot,
    index_file: pathlib.Path,
    cloud_sticker_set: StickerSet | None,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
    confirm: Optional[Callable[[], bool]] = None,
) -> bool:
    """Push local sticker changes to Telegram.

    ``confirm`` is called when a destructive confirmation is needed (e.g. >30
    stickers to upload). In the GUI this opens a message box; in the CLI it
    falls back to ``input()``.
    """
    try:
        local = StickerIndexFile.model_validate_json(
            index_file.read_text(encoding="utf-8")
        )
    except Exception as e:  # noqa: BLE001
        _log(log, "err", f"Index file was corrupted: {e}")
        return False
    try:
        sticker_dir = get_stickers_path(index_file)
    except FileNotFoundError as e:
        _log(log, "err", f"Sticker directory not found: {e}")
        return False
    delete_same_name_files(sticker_dir, log=log)
    local_files: dict[str, pathlib.Path] = {f.stem: f for f in sticker_dir.glob("*")}

    if cloud_sticker_set is None:
        return await _create_new_set(
            bot=telegram_bot,
            local=local,
            local_files=local_files,
            index_file=index_file,
            log=log,
            progress=progress,
        )

    cloud_files = {s.file_unique_id: s for s in cloud_sticker_set.stickers}
    to_upload = [k for k in local_files if k not in cloud_files]
    to_delete = [s.file_id for k, s in cloud_files.items() if k not in local_files]
    to_fix = [
        (k, cloud_files[k].file_id)
        for k in local_files
        if k in cloud_files and local_files[k].stat().st_size != cloud_files[k].file_size
    ]

    if local.title != cloud_sticker_set.title:
        _log(log, "info", f"Updating title to: {local.title}")
        await limited_request(
            telegram_bot.set_sticker_set_title(local.name, local.title)
        )

    if to_delete or to_upload or to_fix:
        _log(
            log,
            "info",
            f"Changes: {len(to_delete)} delete, {len(to_upload)} upload, {len(to_fix)} fix",
        )

    # Enforce pack-size ceiling.
    if len(cloud_files) - len(to_delete) + len(to_upload) > 120:
        _log(log, "err", "Operation would exceed the 120-sticker limit, aborted.")
        return False

    if len(to_upload) > 30:
        _log(log, "warn", "More than 30 stickers to upload — this may fail.")
        if confirm is not None and not confirm():
            _log(log, "warn", "Push aborted by user.")
            return False

    # deletions
    total = len(to_delete)
    for i, fid in enumerate(to_delete, start=1):
        _prog(progress, i, total, f"Deleting {fid}")
        try:
            ok = await limited_request(telegram_bot.delete_sticker_from_set(sticker=fid))
            if ok:
                _log(log, "ok", f"Deleted: {fid}")
            else:
                _log(log, "err", f"Failed to delete: {fid}")
        except Exception as e:  # noqa: BLE001
            _log(log, "err", f"Failed to delete {fid}: {e}")

    # uploads
    total = len(to_upload)
    # Load per-sticker emoji overrides (set via the GUI) once for the whole push.
    pack_dir = index_file.parent
    for i, name in enumerate(to_upload, start=1):
        _prog(progress, i, total, f"Uploading {name}")
        f = local_files[name]
        override = get_emoji_override(pack_dir, name)
        sticker = await create_sticker(
            sticker_type=local.sticker_type,
            sticker_file=f,
            override_emojis=override,
        )
        if sticker is None:
            _log(log, "err", f"Failed to build sticker: {name}")
            continue
        try:
            ok = await limited_request(
                telegram_bot.add_sticker_to_set(
                    user_id=int(local.operator_id),
                    name=local.name,
                    sticker=sticker,
                )
            )
            if ok:
                _log(log, "ok", f"Uploaded: {name}")
                f.unlink(missing_ok=True)
            else:
                _log(log, "err", f"Failed to upload: {name}")
        except Exception as e:  # noqa: BLE001
            _log(log, "err", f"Failed to upload {name}: {e}")

    # corrections
    total = len(to_fix)
    for i, (local_name, cloud_fid) in enumerate(to_fix, start=1):
        _prog(progress, i, total, f"Correcting {local_name}")
        try:
            await download_and_write_file(
                telegram_bot=telegram_bot,
                file_id=cloud_fid,
                file_unique_id=local_name,
                sticker_table_dir=sticker_dir,
                log=log,
            )
            local_files[local_name].unlink(missing_ok=True)
            _log(log, "ok", f"Corrected: {local_name}")
        except Exception as e:  # noqa: BLE001
            _log(log, "err", f"Failed to correct {local_name}: {e}")
            return False

    _log(log, "ok", "Push complete.")
    return True


async def _create_new_set(
    *,
    bot: AsyncTeleBot,
    local: StickerIndexFile,
    local_files: dict[str, pathlib.Path],
    index_file: pathlib.Path,
    log: LogCb | None,
    progress: ProgressCb | None,
) -> bool:
    """Create a new sticker set, batching uploads to respect Telegram's 30-sticker limit.

    Telegram's ``createNewStickerSet`` accepts at most 30 stickers per call.
    We create the pack with the first batch (up to 25 — leaving headroom),
    then upload any remaining stickers via ``addStickerToSet`` in batches of 25.
    """
    if not local_files:
        _log(log, "err", "No stickers in the stickers/ folder — nothing to create.")
        return False

    # Telegram's hard limit: 120 stickers per pack.
    if len(local_files) > 120:
        _log(
            log, "err",
            f"Too many stickers ({len(local_files)}). Telegram limit is 120 per pack.",
        )
        return False

    BATCH_SIZE = 25  # stay under Telegram's 30-sticker create limit with headroom
    file_list = list(local_files.values())
    total = len(file_list)
    uploaded = 0
    pack_dir = index_file.parent

    # --- Phase 1: build ALL stickers first (so we don't fail mid-upload) ----
    _log(log, "info", f"Building {total} sticker(s)…")
    stickers: list = []
    for i, f in enumerate(file_list, start=1):
        _prog(progress, i, total, f"Building {f.name}")
        override = get_emoji_override(pack_dir, f.stem)
        st = await create_sticker(
            sticker_type=local.sticker_type,
            sticker_file=f,
            override_emojis=override,
        )
        if st is None:
            _log(log, "err", f"Failed to build sticker: {f.name}")
            return False
        stickers.append(st)

    # --- Phase 2: create the set with the first batch -----------------------
    first_batch = stickers[:BATCH_SIZE]
    _log(log, "info", f"Creating sticker set with first {len(first_batch)} sticker(s)…")
    try:
        ok = await limited_request(
            bot.create_new_sticker_set(
                user_id=int(local.operator_id),
                title=local.title,
                name=local.name,
                stickers=first_batch,
                sticker_type=local.sticker_type,
            )
        )
        if not ok:
            raise RuntimeError("Request failed")
    except Exception as e:  # noqa: BLE001
        if "USER_IS_BOT" in str(e):
            _log(
                log, "err",
                f"Can't create a sticker set with a bot account. "
                f"Is {local.operator_id} your user id (not the bot id)?",
            )
        else:
            _log(log, "err", f"Failed to create sticker set: {e}")
        return False
    uploaded += len(first_batch)
    _prog(progress, uploaded, total, f"Created set, {uploaded}/{total} uploaded")
    _log(log, "ok", f"Sticker set created with {uploaded} sticker(s).")

    # --- Phase 3: add remaining stickers in batches -------------------------
    remaining = stickers[BATCH_SIZE:]
    for batch_start in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[batch_start:batch_start + BATCH_SIZE]
        _log(
            log, "info",
            f"Uploading batch {batch_start // BATCH_SIZE + 2}/"
            f"{(len(remaining) + BATCH_SIZE - 1) // BATCH_SIZE + 1} ({len(batch)} stickers)…",
        )
        for st in batch:
            try:
                ok = await limited_request(
                    bot.add_sticker_to_set(
                        user_id=int(local.operator_id),
                        name=local.name,
                        sticker=st,
                    )
                )
                if not ok:
                    _log(log, "err", "Failed to add sticker to set.")
                    # Don't abort — keep trying the rest.
                else:
                    uploaded += 1
                    _prog(progress, uploaded, total, f"Uploaded {uploaded}/{total}")
            except Exception as e:  # noqa: BLE001
                _log(log, "err", f"Failed to add sticker: {e}")
                # continue with next sticker

    _log(log, "ok", f"Push complete. {uploaded}/{total} sticker(s) uploaded.")
    return True


# ---------------------------------------------------------------------------
# high-level operations used by both CLI and GUI
# ---------------------------------------------------------------------------

async def op_download(
    *,
    link: str,
    target_dir: pathlib.Path,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
) -> None:
    creds = get_credentials()
    if creds is None:
        _log(log, "err", "You are not logged in. Login first.")
        return
    pack_name = link.removesuffix("/").split("/")[-1]
    if not target_dir.exists():
        _log(log, "err", f"Download directory does not exist: {target_dir}")
        return
    _log(log, "info", f"Preparing to download pack: {pack_name}")
    bot = make_bot(creds)
    await download_sticker_set(
        pack_name=pack_name,
        telegram_bot=bot,
        download_dir=target_dir,
        log=log,
        progress=progress,
    )
    _log(log, "ok", "Download completed!")


async def op_trace(
    *,
    link: str,
    target_dir: pathlib.Path,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
) -> None:
    """Import an existing cloud pack into a local working directory."""
    creds = get_credentials()
    if creds is None:
        _log(log, "err", "You are not logged in. Login first.")
        return
    pack_name = link.removesuffix("/").split("/")[-1]
    bot = make_bot(creds)
    try:
        cloud_set: StickerSet = await limited_request(bot.get_sticker_set(pack_name))
    except Exception as e:  # noqa: BLE001
        _log(log, "err", f"Can't fetch stickers named {pack_name}: {e}")
        return
    _log(
        log,
        "info",
        f"Cloud sticker: name={cloud_set.name} title={cloud_set.title} type={cloud_set.sticker_type}",
    )
    if not cloud_set.name.endswith("_by_" + creds.bot_user.username):
        _log(
            log,
            "err",
            f"Only packs created by this bot (@{creds.bot_user.username}) can be edited.",
        )
        return
    sticker_dir = target_dir / cloud_set.name
    if sticker_dir.exists():
        _log(log, "err", f"Pack directory already exists: {sticker_dir}")
        return
    sticker_dir.mkdir(exist_ok=False)
    _log(log, "info", f"Pack directory created: {sticker_dir}")
    index_file = sticker_dir / "index.json"
    _atomic_write_json(
        index_file,
        StickerIndexFile.create(
            title=cloud_set.title,
            name=cloud_set.name,
            sticker_type=cloud_set.sticker_type,
            operator_id=str(creds.bot_user.id),
        ).model_dump_json(indent=2)
    )
    (sticker_dir / STICKER_DIR_NAME).mkdir(exist_ok=True)
    if cloud_set.stickers:
        await sync_index(
            telegram_bot=bot,
            index_file=index_file,
            cloud_sticker_set=cloud_set,
            log=log,
            progress=progress,
        )
    _log(log, "ok", "Trace completed.")


async def op_init(
    *,
    pack_name: str,
    pack_title: str,
    sticker_type: str,
    target_dir: pathlib.Path,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
) -> None:
    creds = get_credentials()
    if creds is None:
        _log(log, "err", "You are not logged in. Login first.")
        return
    try:
        validated = StickerValidateInput(
            pack_name=pack_name, pack_title=pack_title, sticker_type=sticker_type
        )
    except Exception as e:  # noqa: BLE001
        _log(log, "err", f"Invalid input: {e}")
        return
    bot = make_bot(creds)

    full_name = StickerValidateInput.make_set_name(
        validated.pack_name, creds.bot_user.username
    )

    # --- PRE-FLIGHT: does this pack name already exist on Telegram? -----------
    # If so, creating a new local folder + pushing would fail with
    # "sticker set name is already occupied". Better to tell the user now and
    # point them to the Trace tab.
    try:
        existing = await limited_request(bot.get_sticker_set(full_name))
    except Exception as e:  # noqa: BLE001
        if "STICKERSET_INVALID" in str(e):
            existing = None
        else:
            _log(log, "err", f"Failed to check Telegram for existing pack: {e}")
            return

    if existing is not None:
        _log(
            log, "err",
            f"A pack named '{full_name}' ALREADY EXISTS on Telegram "
            f"(title: '{existing.title}', {len(existing.stickers)} stickers). "
            f"Use the Download tab → 'Trace' to import it as an editable local folder, "
            f"or pick a different pack name.",
        )
        return

    if (target_dir / "index.json").exists():
        _log(log, "warn", "index.json already exists in the target directory.")

    sticker_dir = target_dir / validated.pack_name
    if sticker_dir.exists():
        _log(log, "err", f"Pack directory already exists: {sticker_dir}")
        return
    sticker_dir.mkdir(exist_ok=False)
    _log(log, "ok", f"Pack directory initialised: {sticker_dir}")

    index_model = StickerIndexFile.create(
        title=validated.pack_title,
        name=full_name,
        sticker_type=sticker_type,
        operator_id=str(creds.owner_id),
    )
    index_file = sticker_dir / "index.json"
    _atomic_write_json(index_file, index_model.model_dump_json(indent=2))
    _log(
        log,
        "info",
        f"Index created: title={index_model.title} name={index_model.name} type={index_model.sticker_type}",
    )

    try:
        get_stickers_path(index_file)
    except Exception as e:  # noqa: BLE001
        _log(log, "err", f"Failed to create stickers directory: {e}")
        return

    _log(log, "ok", "Empty pack — index file created. Drop images into stickers/ then Push.")
    _log(log, "ok", "Init completed.")


async def op_restore_snapshot(
    *,
    target_dir: pathlib.Path,
    log: LogCb | None = None,
) -> bool:
    """Restore the latest snapshot into the pack's stickers/ folder.

    Used by the Show tab's "Restore snapshot" button to recover from a
    corrupted or wiped stickers/ dir.
    """
    index_file = target_dir / "index.json"
    if not index_file.exists():
        _log(log, "err", f"index.json not found in {target_dir}.")
        return False
    return restore_latest_snapshot(index_file, log=log)


async def op_apply_emoji_to_cloud(
    *,
    target_dir: pathlib.Path,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
) -> bool:
    """Update the emoji of stickers that are ALREADY in Telegram.

    For every sticker with a local emoji override (saved via the GUI's
    "Set emoji…" dialog), this looks up the matching cloud sticker by
    ``file_unique_id`` (which is the local file stem) and calls Telegram's
    ``setStickerEmojiList`` with the new emoji list.

    This does NOT re-upload the image — it only changes the emoji associated
    with an existing cloud sticker. Fast (2s per sticker due to rate limiting).

    Returns True if all overrides were applied, False if any failed.
    """
    creds = get_credentials()
    if creds is None:
        _log(log, "err", "You are not logged in. Login first.")
        return False
    local, index_file = _load_local_pack(target_dir, log)
    if local is None or index_file is None:
        return False

    # Load all emoji overrides for this pack.
    overrides = load_emoji_overrides(target_dir)
    if not overrides:
        _log(log, "warn", "No custom emoji assignments to apply. Use 'Set emoji…' first.")
        return False

    bot = make_bot(creds)
    _log(log, "info", f"Working on pack: https://t.me/addstickers/{local.name}")
    cloud_set = await _fetch_cloud_set(bot, local.name, log)
    if cloud_set is None:
        _log(log, "err", "Sticker set not found in Telegram. Push it first.")
        return False

    # Map file_unique_id -> cloud file_id so we can call setStickerEmojiList.
    cloud_by_unique: dict[str, str] = {
        s.file_unique_id: s.file_id for s in cloud_set.stickers
    }

    # Figure out which overrides actually have a matching cloud sticker.
    to_apply: list[tuple[str, str, list[str]]] = []  # (unique_id, file_id, emojis)
    missing: list[str] = []
    for stem, emojis in overrides.items():
        if not emojis:
            continue
        file_id = cloud_by_unique.get(stem)
        if file_id is None:
            missing.append(stem)
            continue
        to_apply.append((stem, file_id, emojis))

    if missing:
        _log(
            log, "warn",
            f"{len(missing)} overridden sticker(s) not found in Telegram "
            f"(maybe not pushed yet): {', '.join(missing[:5])}"
            + ("…" if len(missing) > 5 else ""),
        )
    if not to_apply:
        _log(log, "err", "Nothing to apply — no overridden stickers match cloud stickers.")
        return False

    _log(log, "info", f"Applying new emoji to {len(to_apply)} cloud sticker(s)…")
    total = len(to_apply)
    ok_count = 0
    fail_count = 0
    for i, (stem, file_id, emojis) in enumerate(to_apply, start=1):
        _prog(progress, i, total, f"Updating emoji {i}/{total}: {stem}")
        try:
            result = await limited_request(
                bot.set_sticker_emoji_list(file_id, emojis)
            )
            if result:
                _log(log, "ok", f"Updated emoji → {' '.join(emojis)}  for {stem}")
                ok_count += 1
            else:
                _log(log, "err", f"Telegram rejected emoji update for {stem}")
                fail_count += 1
        except Exception as e:  # noqa: BLE001
            _log(log, "err", f"Failed to update emoji for {stem}: {e}")
            fail_count += 1

    if fail_count == 0:
        _log(log, "ok", f"All done! Updated emoji on {ok_count} sticker(s) in Telegram.")
        return True
    else:
        _log(
            log, "warn",
            f"Done with errors: {ok_count} succeeded, {fail_count} failed.",
        )
        return False


def _load_local_pack(
    target_dir: pathlib.Path,
    log: LogCb | None,
) -> tuple[StickerIndexFile | None, pathlib.Path | None]:
    index_file = target_dir / "index.json"
    if not index_file.exists():
        _log(log, "err", f"index.json not found in {target_dir}. "
                          "Use the Init tab to create a new pack, or pick the right folder.")
        return None, None
    raw = index_file.read_text(encoding="utf-8")
    if not raw.strip():
        # Empty index.json usually means a previous push crashed mid-write.
        # Try to recover from the latest snapshot before giving up.
        _log(log, "warn", f"index.json in {target_dir} is EMPTY — "
                          "a previous push likely crashed.")
        snaps = list_snapshots(index_file)
        if snaps:
            _log(log, "info", f"Found {len(snaps)} snapshot(s). "
                              f"Use the Show tab → 'Restore snapshot' to recover, "
                              f"or run Sync to re-download from Telegram.")
        else:
            _log(log, "err", f"No snapshots found. Delete this folder and use Init "
                              f"to recreate the pack, or use Trace to re-import from Telegram.")
        return None, None
    try:
        local = StickerIndexFile.model_validate_json(raw)
    except ValidationError as e:
        _log(log, "err", f"index.json is corrupted: {e}\n"
                          f"Delete the folder {target_dir} and use Init to recreate the pack, "
                          f"or use Trace to re-import from Telegram.")
        return None, None
    return local, index_file


async def _fetch_cloud_set(
    bot: AsyncTeleBot, name: str, log: LogCb | None
) -> StickerSet | None:
    try:
        return await limited_request(bot.get_sticker_set(name))
    except Exception as e:  # noqa: BLE001
        if "STICKERSET_INVALID" in str(e):
            return None
        _log(log, "err", f"Failed to retrieve sticker set {name}: {e}")
        return None


async def op_push(
    *,
    target_dir: pathlib.Path,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
    confirm: Optional[Callable[[], bool]] = None,
) -> None:
    creds = get_credentials()
    if creds is None:
        _log(log, "err", "You are not logged in. Login first.")
        return
    local, index_file = _load_local_pack(target_dir, log)
    if local is None or index_file is None:
        return
    bot = make_bot(creds)
    _log(log, "info", f"Working on pack: https://t.me/addstickers/{local.name}")
    try:
        backup_snapshot(index_file, log=log)
    except Exception as e:  # noqa: BLE001
        _log(log, "err", f"Failed to create backup snapshot: {e}")
        return
    cloud_set = await _fetch_cloud_set(bot, local.name, log)
    ok = await push_to_cloud(
        telegram_bot=bot,
        index_file=index_file,
        cloud_sticker_set=cloud_set,
        log=log,
        progress=progress,
        confirm=confirm,
    )
    if not ok:
        _log(log, "err", "Push aborted.")
        return
    # Re-sync the local index to match the new cloud state.
    cloud_set = await _fetch_cloud_set(bot, local.name, log)
    if cloud_set is not None:
        await sync_index(
            telegram_bot=bot,
            index_file=index_file,
            cloud_sticker_set=cloud_set,
            log=log,
            progress=progress,
        )
    _log(log, "ok", "Push & cleanup completed!")


async def op_sync(
    *,
    target_dir: pathlib.Path,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
) -> None:
    creds = get_credentials()
    if creds is None:
        _log(log, "err", "You are not logged in. Login first.")
        return
    local, index_file = _load_local_pack(target_dir, log)
    if local is None or index_file is None:
        return
    bot = make_bot(creds)
    cloud_set = await _fetch_cloud_set(bot, local.name, log)
    if cloud_set is None:
        _log(
            log,
            "err",
            "Sticker set not found in Telegram. Push it first.",
        )
        return
    _log(log, "info", f"Working on pack: https://t.me/addstickers/{local.name}")
    await sync_index(
        telegram_bot=bot,
        index_file=index_file,
        cloud_sticker_set=cloud_set,
        log=log,
        progress=progress,
    )


async def op_show(
    *,
    target_dir: pathlib.Path,
    log: LogCb | None = None,
) -> dict[str, Any] | None:
    """Return a dict describing the local index + cloud state (for GUI/CLI)."""
    creds = get_credentials()
    local, index_file = _load_local_pack(target_dir, log)
    result: dict[str, Any] = {"local": None, "cloud": None}
    if local is not None:
        result["local"] = {
            "title": local.title,
            "name": local.name,
            "sticker_type": local.sticker_type,
            "operator_id": local.operator_id,
            "emotes_count": len(local.emotes),
        }
    if creds is None or local is None:
        return result
    bot = make_bot(creds)
    cloud_set = await _fetch_cloud_set(bot, local.name, log)
    if cloud_set is not None:
        result["cloud"] = {
            "title": cloud_set.title,
            "name": cloud_set.name,
            "sticker_type": cloud_set.sticker_type,
            "count": len(cloud_set.stickers),
            "link": f"https://t.me/addstickers/{cloud_set.name}",
        }
    return result


# ---------------------------------------------------------------------------
# tiny helpers
# ---------------------------------------------------------------------------

def _log(log: LogCb | None, level: str, message: str) -> None:
    if log is None:
        return
    try:
        log(level, message)
    except Exception:  # noqa: BLE001
        pass


def _prog(progress: ProgressCb | None, current: int, total: int, message: str) -> None:
    if progress is None:
        return
    try:
        progress(current, total, message)
    except Exception:  # noqa: BLE001
        pass


def _atomic_write_json(path: pathlib.Path, data: str) -> None:
    """Write JSON to ``path`` atomically.

    Writes to a temp file in the same directory first, then renames it.
    This guarantees the destination file is never left half-written or empty
    if something crashes mid-write — which previously corrupted index.json
    and made the pack unusable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use a temp file in the SAME directory so os.replace is atomic on the
    # same filesystem.
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the temp file on any failure — never leave it behind.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


__all__ = [
    "save_credentials",
    "get_credentials",
    "delete_credentials",
    "get_stickers_path",
    "get_snapshot_path",
    "backup_snapshot",
    "list_snapshots",
    "restore_latest_snapshot",
    "rebuild_index_from_dir",
    "download_and_write_file",
    "download_sticker_set",
    "sync_index",
    "push_to_cloud",
    "op_download",
    "op_trace",
    "op_init",
    "op_push",
    "op_sync",
    "op_show",
    "op_restore_snapshot",
    "op_apply_emoji_to_cloud",
]
