"""Allow `python -m tsticker_gui` to launch the GUI."""

from __future__ import annotations

from .gui.app import main

raise SystemExit(main())
