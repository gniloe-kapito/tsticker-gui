"""Tiny launcher used by ``Запустить.bat`` / ``Debug.bat``.

Adds the ``app/`` directory to ``sys.path`` so that the ``tsticker_gui``
package can be imported, then starts the Qt event loop via qasync.

If the app crashes, the full traceback is written to ``crash.log`` next to
this file — open it in Notepad to see what went wrong.

Run with:
    deps\\Scripts\\pythonw.exe launch.py   (no console, writes crash.log on error)
    deps\\Scripts\\python.exe launch.py    (debug mode, errors shown in console)
"""

from __future__ import annotations

import datetime
import io
import os
import pathlib
import sys
import traceback

# Path to crash.log — resolved BEFORE anything else so we can always write it.
_HERE = pathlib.Path(__file__).resolve().parent
_CRASH_LOG = _HERE / "crash.log"


def _write_crash_log(exc: BaseException, context: str = "") -> None:
    """Append the full traceback to crash.log next to this file.

    This function is deliberately defensive: it must NEVER raise, even if
    the filesystem is read-only or the encoding is weird. It's the last line
    of defence for pythonw.exe (no console) crashes.
    """
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 70}\n")
            f.write(f"Crash at {datetime.datetime.now().isoformat()}\n")
            f.write(f"Context: {context or '(no context)'}\n")
            f.write(f"Python: {sys.version}\n")
            f.write(f"Platform: {sys.platform}\n")
            f.write(f"Executable: {sys.executable}\n")
            f.write(f"argv: {sys.argv}\n")
            f.write(f"{'=' * 70}\n\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
            f.write("\n")
    except Exception:  # noqa: BLE001 - crash logging must never raise
        pass


def _force_utf8_stdio() -> None:
    """Force stdout/stderr to UTF-8 so emoji / Cyrillic don't crash on Windows.

    Windows defaults to cp1251 for console output, which can't encode emoji
    or many Unicode chars. This breaks push() when sticker filenames contain
    emoji (like 😄cat.png). Reconfiguring to UTF-8 with errors='replace'
    means we never crash on a print() — worst case we see '?' instead.

    IMPORTANT: When launched via ``pythonw.exe`` (no console), ``sys.stdout``
    and ``sys.stderr`` are ``None``. We must guard against that — calling
    ``.reconfigure()`` on ``None`` raises ``AttributeError`` and crashes the
    app BEFORE the GUI even appears (which is the "Запустить.bat doesn't work"
    bug). This guard fixes it.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        # pythonw.exe with no console → stream is None. Skip silently.
        if stream is None:
            continue
        # Some environments wrap stdout in objects without .reconfigure.
        if not hasattr(stream, "reconfigure"):
            # Fallback: try to wrap the underlying buffer in a UTF-8 TextIOWrapper.
            try:
                buffer = getattr(stream, "buffer", None)
                if buffer is not None:
                    setattr(sys, stream_name, io.TextIOWrapper(
                        buffer, encoding="utf-8", errors="replace", line_buffering=True,
                    ))
            except Exception:  # noqa: BLE001 - best effort only
                pass
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            # Reconfigure can fail on closed streams or weird wrappers — ignore.
            pass

    # Also set PYTHONIOENCODING for child processes (e.g. ffmpeg subprocess).
    os.environ["PYTHONIOENCODING"] = "utf-8"
    # Windows console code page — best effort, ignore failures (no console = no-op).
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # type: ignore[attr-defined]
            ctypes.windll.kernel32.SetConsoleCP(65001)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - optional, never fatal
            pass


def _bootstrap() -> None:
    """Set up sys.path and PATH so the app + Qt plugins can be found."""
    here = pathlib.Path(__file__).resolve().parent
    app_dir = here / "app"
    if app_dir.is_dir():
        sys.path.insert(0, str(app_dir))
    elif (here / "src").is_dir():
        # Development / editable-install layout.
        sys.path.insert(0, str(here / "src"))

    # Make sure deps\Scripts is on PATH so Qt plugins are discovered.
    scripts = here / "deps" / "Scripts"
    if scripts.is_dir():
        os.environ["PATH"] = str(scripts) + os.pathsep + os.environ.get("PATH", "")

    # Tell Qt where to find its plugins (Windows fallback).
    plugin_path = here / "deps" / "Lib" / "site-packages" / "PySide6" / "plugins"
    if plugin_path.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugin_path))
    else:
        # Editable install: plugins live next to the PySide6 package.
        try:
            import PySide6  # noqa: WPS433
            pyside_dir = pathlib.Path(PySide6.__file__).resolve().parent
            plugins = pyside_dir / "plugins"
            if plugins.is_dir():
                os.environ.setdefault("QT_PLUGIN_PATH", str(plugins))
        except Exception:  # noqa: BLE001 - best effort
            pass


def _check_deps() -> list[str]:
    """Return a list of missing critical modules (empty list = all OK).

    We probe these BEFORE importing the GUI so that a missing dependency
    is reported in crash.log with a clear message, instead of an opaque
    ImportError deep in the Qt stack.
    """
    missing: list[str] = []
    for mod in ("PySide6", "qasync", "telebot", "pydantic", "PIL", "emoji", "keyring"):
        try:
            __import__(mod)
        except Exception as e:  # noqa: BLE001
            missing.append(f"{mod} ({type(e).__name__}: {e})")
    return missing


def main() -> int:
    # Step 1: fix stdio encoding FIRST (so any later print() is safe).
    try:
        _force_utf8_stdio()
    except Exception as exc:  # noqa: BLE001 - never crash on stdio setup
        _write_crash_log(exc, context="_force_utf8_stdio failed")

    # Step 2: set up sys.path / PATH / QT_PLUGIN_PATH.
    try:
        _bootstrap()
    except Exception as exc:  # noqa: BLE001
        _write_crash_log(exc, context="_bootstrap failed")
        return 1

    # Step 3: probe critical deps before importing the GUI.
    missing = _check_deps()
    if missing:
        msg = "Missing or broken dependencies:\n  - " + "\n  - ".join(missing)
        _write_crash_log(RuntimeError(msg), context="dependency check")
        # On Windows with a console (Debug.bat) this is visible; with pythonw
        # it goes to crash.log. Either way the user has something to report.
        print(msg, file=sys.stderr)  # noqa: T201 - best effort
        return 2

    # Step 4: import + run the GUI. Any failure here is logged to crash.log.
    try:
        from tsticker_gui.gui.app import main as gui_main  # noqa: WPS433

        return gui_main()
    except BaseException as exc:  # noqa: BLE001 - catch everything for crash.log
        _write_crash_log(exc, context="gui_main() crashed")
        # Re-raise so Debug.bat (console mode) shows the traceback too.
        raise


if __name__ == "__main__":
    raise SystemExit(main())
