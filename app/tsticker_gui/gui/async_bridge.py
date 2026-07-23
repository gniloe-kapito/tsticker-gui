"""Bridges between asyncio (Telegram SDK) and the Qt event loop (qasync).

The GUI runs on the Qt event loop. The Telegram SDK is async. ``qasync`` lets
us run an ``asyncio`` loop *inside* Qt, so we can ``await`` Telegram calls
directly from Qt slots.

This module exposes:

* :class:`AsyncJobRunner` — wraps a coroutine into a Qt-friendly future with
  ``on_success`` / ``on_error`` / ``on_finished`` callbacks.
* :func:`run_async` — convenience free function.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

try:
    from qasync import asyncSlot  # type: ignore
except Exception:  # pragma: no cover - qasync is a hard dependency at runtime
    asyncSlot = None  # type: ignore

T = TypeVar("T")


class AsyncJobRunner(Generic[T]):
    """Run an awaitable on the qasync loop and dispatch Qt-signal-like callbacks.

    The callbacks are plain Python callables (typically ``self._signal.emit``)
    so this stays testable without Qt.
    """

    def __init__(
        self,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        on_success: Callable[[T], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        self._coro_factory = coro_factory
        self._on_success = on_success
        self._on_error = on_error
        self._on_finished = on_finished
        self._task: asyncio.Task[T] | None = None

    def start(self) -> asyncio.Task[T]:
        if self._task is not None and not self._task.done():
            return self._task
        self._task = asyncio.ensure_future(self._run())
        return self._task

    async def _run(self) -> T:
        try:
            result = await self._coro_factory()
        except BaseException as e:  # noqa: BLE001
            if self._on_error is not None:
                self._on_error(e)
            raise
        else:
            if self._on_success is not None:
                self._on_success(result)
            return result
        finally:
            if self._on_finished is not None:
                self._on_finished()


def run_async(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    on_success: Callable[[T], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
    on_finished: Callable[[], None] | None = None,
) -> AsyncJobRunner[T]:
    """Convenience factory around :class:`AsyncJobRunner`."""
    runner = AsyncJobRunner(
        coro_factory,
        on_success=on_success,
        on_error=on_error,
        on_finished=on_finished,
    )
    runner.start()
    return runner


def async_slot(*args: Any, **kwargs: Any):  # pragma: no cover - thin wrapper
    """Re-export ``qasync.asyncSlot`` so widgets don't import qasync directly."""
    if asyncSlot is None:  # pragma: no cover
        raise RuntimeError("qasync is not installed. Run `uv sync` again.")
    return asyncSlot(*args, **kwargs)


def debounce(ms: int) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """Simple debounce decorator for line-edit signals."""

    def deco(fn: Callable[..., None]) -> Callable[..., None]:
        timer: dict[str, Any] = {}

        @functools.wraps(fn)
        def wrapper(*a: Any, **kw: Any) -> None:
            try:
                from PySide6.QtCore import QTimer  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("PySide6 is required for debounce") from e

            key = fn.__qualname__
            if key in timer:
                timer[key].stop()
            t = QTimer()
            t.setSingleShot(True)
            t.timeout.connect(lambda: fn(*a, **kw))
            t.start(ms)
            timer[key] = t

        return wrapper

    return deco


__all__ = ["AsyncJobRunner", "run_async", "async_slot", "debounce"]
