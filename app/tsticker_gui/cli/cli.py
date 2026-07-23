"""asyncclick-based CLI — mirrors the original ``tsticker`` commands.

Kept for backward compatibility. The GUI is the primary interface; this CLI
shares the same :mod:`tsticker_gui.core.ops` business logic.
"""

from __future__ import annotations

import atexit
import os
import pathlib
from typing import Literal, Optional

import asyncclick
from rich.console import Console
from rich.panel import Panel

from ..core import StickerValidateInput  # noqa: F401  (re-exported for downstream use)
from ..core import ops
from ..utils import close_session_sync

console = Console()
atexit.register(close_session_sync)


def _print(level: str, msg: str) -> None:
    color = {
        "debug": "gray42",
        "info": "cyan",
        "ok": "bold dark_green",
        "warn": "bold yellow",
        "err": "bold red",
    }.get(level, "white")
    console.print(f"[{color}]{msg}[/{color}]")


def _log_cb(level: str, msg: str) -> None:
    _print(level, msg)


def _prog_cb(current: int, total: int, msg: str) -> None:
    if total > 0:
        console.print(f"[grey42]{current}/{total}[/] [cyan]{msg}[/]")


@asyncclick.group()
async def cli() -> None:
    """TSticker CLI (rewritten, Python 3.13+)."""
    pass


@asyncclick.command()
@asyncclick.option("-t", "--token", required=True, help="Bot token from @BotFather")
@asyncclick.option("-u", "--user", required=True, help="Your Telegram user id")
@asyncclick.option("-p", "--proxy", required=False, help="Optional bot proxy")
async def login(token: str, user: str, proxy: Optional[str] = None) -> None:
    """Log in using a bot token and optional proxy."""
    try:
        int(user)
    except ValueError:
        console.print("[bold red]Invalid user id[/]")
        return
    try:
        ops.save_credentials(token=token, owner_id=user, bot_proxy=proxy)
    except Exception as e:  # noqa: BLE001
        console.print(f"[bold red]Failed to save credentials: {e}[/]")
        return
    console.print("[bold yellow]NOTE:[/] Sticker packs created by this bot can only be managed by this bot.")
    console.print("[bold dark_green]You are now logged in.[/]")


@asyncclick.command()
async def logout() -> None:
    """Log out."""
    ops.delete_credentials()
    console.print("[bold yellow]✔ You are now logged out.[/]")


@asyncclick.command()
@asyncclick.option("-s", "--sticker-type", type=asyncclick.Choice(["mask", "regular", "custom_emoji"], case_sensitive=False), default="regular")
@asyncclick.option("-n", "--pack-name", required=True, help="Pack name (alphanumeric + underscore)")
@asyncclick.option("-t", "--pack-title", required=True, help="Pack title (1-64 chars)")
async def init(
    pack_name: str,
    pack_title: str,
    sticker_type: Literal["mask", "regular", "custom_emoji"] = "regular",
) -> None:
    """Initialise a new local sticker pack."""
    target = pathlib.Path(os.getcwd())
    await ops.op_init(
        pack_name=pack_name,
        pack_title=pack_title,
        sticker_type=sticker_type,
        target_dir=target,
        log=_log_cb,
        progress=_prog_cb,
    )


@asyncclick.command()
async def sync() -> None:
    """Override local files with the cloud sticker set."""
    target = pathlib.Path(os.getcwd())
    await ops.op_sync(target_dir=target, log=_log_cb, progress=_prog_cb)


@asyncclick.command()
async def push() -> None:
    """Push local sticker changes to Telegram."""
    target = pathlib.Path(os.getcwd())

    def confirm() -> bool:
        return asyncclick.confirm("More than 30 stickers to upload. Continue?")

    await ops.op_push(
        target_dir=target,
        log=_log_cb,
        progress=_prog_cb,
        confirm=confirm,
    )


@asyncclick.command()
@asyncclick.option("-l", "--link", required=True, help="Sticker pack link")
async def download(link: str) -> None:
    """Download any public sticker pack (read-only)."""
    target = pathlib.Path(os.getcwd())
    await ops.op_download(link=link, target_dir=target, log=_log_cb, progress=_prog_cb)


@asyncclick.command()
@asyncclick.option("-l", "--link", required=True, help="Sticker pack link")
async def trace(link: str) -> None:
    """Import a pack created by your bot as an editable local copy."""
    target = pathlib.Path(os.getcwd())
    await ops.op_trace(link=link, target_dir=target, log=_log_cb, progress=_prog_cb)


@asyncclick.command()
async def show() -> None:
    """Show pack info (local + cloud)."""
    target = pathlib.Path(os.getcwd())
    data = await ops.op_show(target_dir=target, log=_log_cb)
    if not data:
        return
    local = data.get("local")
    cloud = data.get("cloud")
    if local:
        console.print(Panel(
            f"  [cyan]Pack Title:[/] {local['title']}\n"
            f"  [cyan]Link Name:[/] {local['name']}\n"
            f"  [cyan]Sticker Type:[/] {local['sticker_type']}\n"
            f"  [cyan]Bot Owner:[/] {local['operator_id']}\n"
            f"  [cyan]Local emotes:[/] {local['emotes_count']}",
            style="grey42", title="Local", title_align="left", expand=False,
        ))
    if cloud:
        console.print(Panel(
            f"  [cyan]Cloud Title:[/] {cloud['title']}\n"
            f"  [cyan]Count:[/] {cloud['count']}\n"
            f"  [cyan]Type:[/] {cloud['sticker_type']}\n"
            f"  [cyan]Link:[/] {cloud['link']}",
            style="grey42", title="Cloud", title_align="left", expand=False,
        ))


cli.add_command(init)
cli.add_command(login)
cli.add_command(push)
cli.add_command(sync)
cli.add_command(trace)
cli.add_command(download)
cli.add_command(show)


if __name__ == "__main__":  # pragma: no cover
    cli(_anyio_backend="asyncio")
