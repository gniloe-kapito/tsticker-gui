"""Dialog for picking emojis for a sticker — with categories, search & recents.

Opened from the Push/Sync tab when the user double-clicks a sticker thumbnail
(or clicks "Set emoji…" on a selected one). Lets the user assign one or more
emojis that will be sent to Telegram instead of any emoji derived from the
file name.

Features:
* **Categories** — tabbed grid (Smileys, Gestures, Hearts, Animals, Food,
  Activities, Travel, Objects, Flags, Recent).
* **Search** — type a word (e.g. "cat", "heart", "fire") and matching emoji
  from the full catalog are shown in a dedicated "Search" tab.
* **Recents** — the last ~30 emoji you picked are remembered (QSettings) and
  shown in their own tab for quick reuse.
* **Manual entry** — type or paste any emoji directly.
* **Big, readable buttons** — 42×42 px, font size 18, explicit emoji font
  ("Segoe UI Emoji" on Windows, "Apple Color Emoji" on macOS, "Noto Color Emoji"
  on Linux) so emoji render in colour instead of monochrome boxes.
* **Scrollable** — works at any window size.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Emoji font — pick the best colour-emoji font for the platform so emoji
# render nicely instead of as monochrome outlines / tofu boxes.
# ---------------------------------------------------------------------------

def _emoji_font() -> QFont:
    """Return a QFont tuned for colour emoji rendering."""
    candidates: list[str] = []
    if sys.platform == "win32":
        candidates = ["Segoe UI Emoji", "Segoe UI Symbol"]
    elif sys.platform == "darwin":
        candidates = ["Apple Color Emoji", "Segoe UI Emoji"]
    else:  # Linux / other
        candidates = ["Noto Color Emoji", "Segoe UI Emoji", "DejaVu Sans"]
    f = QFont()
    for name in candidates:
        f.setFamily(name)
        # We can't easily probe whether the family exists without QGuiDatabase,
        # but Qt falls back gracefully, so just set the first candidate.
        break
    f.setPointSize(18)
    return f


# ---------------------------------------------------------------------------
# Curated catalog by category.  Each category is a flat tuple of emoji glyphs.
# Kept deliberately broad so the search box finds something useful.
# ---------------------------------------------------------------------------

_SMILEYS: tuple[str, ...] = (
    "😀", "😃", "😄", "😁", "😅", "😂", "🤣", "🥲", "☺️", "😊",
    "😇", "🙂", "🙃", "😉", "😌", "😍", "🥰", "😘", "😗", "😙",
    "😚", "😋", "😛", "😝", "😜", "🤪", "🤨", "🧐", "🤓", "😎",
    "🥸", "🤩", "🥳", "😏", "😒", "😞", "😔", "😟", "😕", "🙁",
    "☹️", "😣", "😖", "😫", "😩", "🥺", "😢", "😭", "😤", "😠",
    "😡", "🤬", "🤯", "😳", "🥵", "🥶", "😱", "😨", "😰", "😥",
    "😓", "🤗", "🤔", "🤭", "🤫", "🤥", "😶", "😐", "😑", "😬",
    "🙄", "😯", "😦", "😧", "😮", "😲", "🥱", "😴", "🤤", "😪",
    "😵", "🤐", "🥴", "🤢", "🤮", "🤧", "😷", "🤒", "🤕", "🤑",
    "🤠", "💩", "👻", "💀", "👽", "🤖", "😈", "👿", "👹", "👺",
)

_GESTURES: tuple[str, ...] = (
    "👍", "👎", "👊", "✊", "🤛", "🤜", "👏", "🙌", "👐", "🤲",
    "🤝", "🙏", "✌️", "🤞", "🤟", "🤘", "👌", "🤌", "🤏", "👈",
    "👉", "👆", "🖕", "👇", "☝️", "👋", "🤚", "🖐️", "✋", "🖖",
    "💪", "🦾", "🦿", "🦵", "🦶", "👂", "🦻", "👃", "🧠", "🫀",
    "🦷", "bone", "👀", "👁️", "👅", "👄", "💋", "🧒", "👦", "👧",
    "🧑", "👨", "👩", "🧓", "👴", "👵", "👶", "👼", "🤰", "🤱",
)

_HEARTS: tuple[str, ...] = (
    "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔",
    "❣️", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟", "❤️‍🔥",
    "💯", "💢", "💥", "💫", "💦", "💨", "🕳️", "💣", "💬", "👁️‍🗨️",
    "🗨️", "🗯️", "💭", "💤", "✨", "⭐", "🌟", "🌠", "⚡", "🔥",
    "🌈", "☀️", "⛅", "☁️", "🌧️", "⛈️", "🌩️", "❄️", "☃️", "⛄",
    "🎉", "🎊", "🎈", "🎁", "🎀", "🏆", "🥇", "🥈", "🥉", "🏅",
    "👑", "💎", "🔮", "🆗", "🆒", "🆕", "🆓", "✅", "❌", "❓",
)

_ANIMALS: tuple[str, ...] = (
    "🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯",
    "🦁", "🐮", "🐷", "🐽", "🐸", "🐵", "🙈", "🙉", "🙊", "🐒",
    "🦍", "🐔", "🐧", "🐦", "🐤", "🐣", "🐥", "🦆", "🦅", "🦉",
    "🦇", "🐺", "🐗", "🐴", "🦄", "🐝", "🐛", "🦋", "🐌", "🐞",
    "🐜", "🪰", "🪲", "🪳", "🦟", "🦗", "🕷️", "🕸️", "🦂", "🐢",
    "🐍", "🦎", "🦖", "🦕", "🐙", "🦑", "🦐", "🦞", "🦀", "🐡",
    "🐠", "🐟", "🐬", "🐳", "🐋", "🦈", "🐊", "🐅", "🐆", "🦓",
    "🦍", "🐘", "🦛", "🦏", "🐪", "🐫", "🦒", "🦘", "🐃", "🐂",
)

_FOOD: tuple[str, ...] = (
    "🍏", "🍎", "🍐", "🍊", "🍋", "🍌", "🍉", "🍇", "🍓", "🫐",
    "🍈", "🍒", "🍑", "🥭", "🍍", "🥥", "🥝", "🍅", "🍆", "🥑",
    "🥦", "🥬", "🥒", "🌶️", "🫑", "🌽", "🥕", "🫒", "🧄", "🧅",
    "🥔", "🍠", "🥐", "🥯", "🍞", "🥖", "🥨", "🧀", "🥚", "🍳",
    "🧈", "🥞", "🧇", "🥓", "🥩", "🍗", "🍖", "🌭", "🍔", "🍟",
    "🍕", "🥪", "🌮", "🌯", "🥙", "🧆", "🥗", "🥘", "🍜", "🍲",
    "🍛", "🍣", "🍱", "🥟", "🦪", "🍤", "🍙", "🍚", "🍘", "🍥",
    "🥠", "🥮", "🍦", "🍧", "🍨", "🍩", "🍪", "🎂", "🍰", "🧁",
    "🍫", "🍬", "🍭", "🍮", "🍯", "☕", "🍵", "🧃", "🥤", "🍶",
    "🍺", "🍻", "🥂", "🍷", "🥃", "🍸", "🍹", "🍾", "🧊", "🥄",
)

_ACTIVITIES: tuple[str, ...] = (
    "⚽", "🏀", "🏈", "⚾", "🥎", "🎾", "🏐", "🏉", "🥏", "🎱",
    "🪀", "🏓", "🏸", "🏒", "🏑", "🥍", "🏏", "🥅", "⛳", "🏹",
    "🎣", "🤿", "🥊", "🥋", "🎽", "🛹", "🛼", "🛷", "⛸️", "🥌",
    "🎿", "⛷️", "🏂", "🪂", "🏋️", "🤼", "🤸", "⛹️", "🤺", "🤾",
    "🏌️", "🏇", "🧘", "🏄", "🏊", "🤽", "🚣", "🧗", "🚵", "🚴",
    "🏆", "🥇", "🥈", "🥉", "🏅", "🎖️", "🏵️", "🎗️", "🎫", "🎟️",
    "🎪", "🤹", "🎭", "🩰", "🎨", "🎬", "🎤", "🎧", "🎼", "🎹",
    "🥁", "🎷", "🎺", "🎸", "🪕", "🎻", "🎲", "♟️", "🎯", "🎳",
    "🎮", "🕹️", "🎰", "🧩", "🎨", "🎭", "🎪", "🎬", "🎤", "🎧",
)

_TRAVEL: tuple[str, ...] = (
    "🚗", "🚕", "🚙", "🚌", "🚎", "🏎️", "🚓", "🚑", "🚒", "🚐",
    "🛻", "🚚", "🚛", "🚜", "🦯", "🦽", "🦼", "🛴", "🚲", "🛵",
    "🏍️", "🛺", "🚨", "🚔", "🚍", "🚘", "🚖", "🚡", "🚠", "🚟",
    "🚃", "🚋", "🚞", "🚝", "🚄", "🚅", "🚈", "🚂", "🚆", "🚇",
    "🚊", "🚉", "✈️", "🛫", "🛬", "🛩️", "💺", "🛰️", "🚀", "🛸",
    "🚁", "🛶", "⛵", "🚤", "🛥️", "🛳️", "⛴️", "🚢", "⚓", "🗺️",
    "🗿", "🗽", "🗼", "🏰", "🏯", "🏟️", "🎡", "🎢", "🎠", "⛲",
    "⛱️", "🏖️", "🏝️", "🏜️", "🌋", "⛰️", "🏔️", "🗻", "🏕️", "⛺",
    "🏠", "🏡", "🏘️", "🏚️", "🏗️", "🏭", "🏢", "🏬", "🏣", "🏤",
)

_OBJECTS: tuple[str, ...] = (
    "⌚", "📱", "📲", "💻", "⌨️", "🖥️", "🖨️", "🖱️", "🖲️", "🕹️",
    "🗜️", "💽", "💾", "💿", "📀", "📼", "📷", "📸", "📹", "🎥",
    "📽️", "🎞️", "📞", "☎️", "📟", "📠", "📺", "📻", "🎙️", "🎚️",
    "🎛️", "🧭", "⏱️", "⏲️", "⏰", "🕰️", "💡", "🔦", "🏮", "🪔",
    "📔", "📕", "📖", "📗", "📘", "📙", "📚", "📓", "📒", "📃",
    "📜", "📄", "📰", "🗞️", "📑", "🔖", "🏷️", "💰", "💴", "💵",
    "💶", "💷", "💸", "💳", "🧾", "✏️", "✒️", "🖋️", "🖊️", "🖌️",
    "🖍️", "📝", "🔍", "🔎", "🔏", "🔐", "🔑", "🗝️", "🔨", "🪓",
    "⛏️", "⚒️", "🛠️", "🗡️", "⚔️", "💣", "🪃", "🏹", "🛡️", "🔧",
)

_FLAGS: tuple[str, ...] = (
    "🏁", "🚩", "🎌", "🏴", "🏳️", "🏳️‍🌈", "🏴‍☠️", "🇷🇺", "🇺🇸", "🇬🇧",
    "🇪🇺", "🇨🇳", "🇯🇵", "🇰🇷", "🇩🇪", "🇫🇷", "🇮🇹", "🇪🇸", "🇨🇦", "🇦🇺",
    "🇧🇷", "🇮🇳", "🇲🇽", "🇿🇦", "🇪🇬", "🇹🇷", "🇮🇱", "🇸🇦", "🇦🇪", "🇺🇦",
    "🇵🇱", "🇳🇱", "🇧🇪", "🇸🇪", "🇳🇴", "🇫🇮", "🇩🇰", "🇨🇿", "🇭🇺", "🇷🇸",
    "🇭🇷", "🇸🇰", "🇸🇮", "🇧🇬", "🇬🇷", "🇵🇹", "🇨🇭", "🇦🇹", "🇮🇪", "🇮🇸",
)

# (category_name, category_emoji, category_contents)
_CATEGORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Smileys", "😀", _SMILEYS),
    ("Gestures", "👍", _GESTURES),
    ("Hearts", "❤️", _HEARTS),
    ("Animals", "🐱", _ANIMALS),
    ("Food", "🍕", _FOOD),
    ("Activities", "⚽", _ACTIVITIES),
    ("Travel", "🚗", _TRAVEL),
    ("Objects", "💡", _OBJECTS),
    ("Flags", "🏁", _FLAGS),
)

# Flatten the whole catalog for search.
_ALL_EMOJIS: list[str] = []
for _name, _icon, _items in _CATEGORIES:
    for _e in _items:
        if _e not in _ALL_EMOJIS:
            _ALL_EMOJIS.append(_e)

# Build a name index for search using the `emoji` library (demojize gives
# :name: for each glyph).  We do this lazily so the import doesn't slow down
# module load.
_NAME_INDEX: dict[str, list[str]] | None = None


def _build_name_index() -> dict[str, list[str]]:
    """Map a lowercased search keyword -> list of matching emoji glyphs."""
    global _NAME_INDEX
    if _NAME_INDEX is not None:
        return _NAME_INDEX
    import emoji as _emoji

    index: dict[str, list[str]] = {}
    for glyph in _ALL_EMOJIS:
        # demojize returns something like ":cat_face:" — strip the colons,
        # split on underscores, each part becomes a searchable keyword.
        name = _emoji.demojize(glyph, language="en").strip(":").lower()
        keywords = name.replace("_", " ").split()
        # Also index the full name as a single keyword.
        keywords.append(name.replace("_", ""))
        for kw in keywords:
            index.setdefault(kw, [])
            if glyph not in index[kw]:
                index[kw].append(glyph)
    _NAME_INDEX = index
    return index


def _search_emojis(query: str, limit: int = 120) -> list[str]:
    """Return emoji matching ``query`` (substring match on keywords)."""
    if not query.strip():
        return []
    q = query.strip().lower()
    index = _build_name_index()
    seen: list[str] = []
    seen_set: set[str] = set()
    # Exact keyword match first.
    if q in index:
        for g in index[q]:
            if g not in seen_set:
                seen.append(g)
                seen_set.add(g)
    # Then substring matches.
    for kw, glyphs in index.items():
        if q in kw:
            for g in glyphs:
                if g not in seen_set:
                    seen.append(g)
                    seen_set.add(g)
        if len(seen) >= limit:
            break
    return seen[:limit]


# ---------------------------------------------------------------------------
# Recently-used emoji (persisted via QSettings).
# ---------------------------------------------------------------------------

_RECENTS_KEY = "recentEmoji"
_RECENTS_MAX = 30


def _load_recents() -> list[str]:
    try:
        from PySide6.QtCore import QSettings

        s = QSettings("tsticker-gui", "emoji-picker")
        raw = s.value(_RECENTS_KEY, [], type=list)
        return [str(e) for e in raw if isinstance(e, str)][:_RECENTS_MAX]
    except Exception:  # noqa: BLE001
        return []


def _save_recents(emojis: list[str]) -> None:
    try:
        from PySide6.QtCore import QSettings

        s = QSettings("tsticker-gui", "emoji-picker")
        s.setValue(_RECENTS_KEY, emojis[:_RECENTS_MAX])
    except Exception:  # noqa: BLE001
        pass


def _push_recent(emoji: str) -> None:
    recents = _load_recents()
    if emoji in recents:
        recents.remove(emoji)
    recents.insert(0, emoji)
    _save_recents(recents[:_RECENTS_MAX])


# ---------------------------------------------------------------------------
# A scrollable grid of emoji buttons.
# ---------------------------------------------------------------------------

class _EmojiGrid(QWidget):
    """A scrollable grid of emoji buttons that emits ``picked(str)``."""

    picked = None  # set as a Signal on the instance below

    def __init__(self, emojis: Iterable[str], *, columns: int = 10) -> None:
        from PySide6.QtCore import Signal

        # Signals must be class attributes, so we attach one dynamically.
        # (Using a plain QWidget subclass with a class-level Signal is cleaner,
        # but we keep this simple with a callback.)
        super().__init__()
        self._on_pick = None  # callable(str) | None
        self._columns = columns

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        if not list(emojis):
            placeholder = QLabel("No emoji here yet.")
            placeholder.setObjectName("hint")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            outer.addWidget(placeholder)
            outer.addStretch(1)
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(3)
        grid.setContentsMargins(2, 2, 2, 2)
        efont = _emoji_font()
        emojis_list = list(emojis)
        for i, em in enumerate(emojis_list):
            btn = QPushButton(em)
            btn.setFixedSize(42, 42)
            btn.setFont(efont)
            btn.setToolTip(f"{em}  (click to add)")
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            # Flat style so the emoji is the focus, not the button chrome.
            btn.setStyleSheet(
                "QPushButton { background: #161a1f; border: 1px solid #1c2127; "
                "border-radius: 6px; }"
                "QPushButton:hover { background: #134e4a; border-color: #14b8a6; }"
                "QPushButton:pressed { background: #0d9488; }"
            )
            btn.clicked.connect(lambda _checked=False, e=em: self._emit_pick(e))
            grid.addWidget(btn, i // columns, i % columns)
        scroll.setWidget(host)
        outer.addWidget(scroll)

    def set_on_pick(self, cb) -> None:  # type: ignore[no-untyped-def]
        self._on_pick = cb

    def _emit_pick(self, em: str) -> None:
        _push_recent(em)
        if self._on_pick is not None:
            self._on_pick(em)


# ---------------------------------------------------------------------------
# The dialog itself.
# ---------------------------------------------------------------------------

class EmojiPickerDialog(QDialog):
    """Modal dialog that returns a list of emoji strings."""

    def __init__(
        self,
        *,
        sticker_name: str,
        current_emojis: list[str] | None = None,
        source_label: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set emoji for sticker")
        self.setMinimumSize(520, 560)
        self._emojis: list[str] = list(current_emojis) if current_emojis else []
        self._efont = _emoji_font()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # --- Header -------------------------------------------------------
        header = QLabel(f"<b>Sticker:</b> {sticker_name}")
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setWordWrap(True)
        root.addWidget(header)

        if source_label:
            src = QLabel(source_label)
            src.setObjectName("hint")
            src.setWordWrap(True)
            root.addWidget(src)

        # --- Manual entry -------------------------------------------------
        root.addWidget(QLabel("Type or paste emoji (you can add several):"))
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("paste emoji here, e.g.  🐱😺")
        self._entry.setText("".join(self._emojis))
        self._entry.textChanged.connect(self._on_entry_changed)
        ef = QFont(self._entry.font())
        ef.setPointSize(14)
        self._entry.setFont(ef)
        root.addWidget(self._entry)

        entry_row = QHBoxLayout()
        entry_row.setSpacing(6)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self._entry.clear())
        entry_row.addStretch(1)
        entry_row.addWidget(clear_btn)
        root.addLayout(entry_row)

        # --- Search box ---------------------------------------------------
        root.addWidget(QLabel("Search emoji by name (e.g. cat, heart, fire):"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("type a word to find emoji…")
        self._search.textChanged.connect(self._on_search_changed)
        root.addWidget(self._search)

        # --- Category tabs ------------------------------------------------
        self._tabs = QTabWidget()
        # Recent tab (index 0) — populated in _refresh_recent_tab().
        self._recent_grid: _EmojiGrid | None = None
        self._recent_tab_idx = self._tabs.addTab(self._make_recent_tab(), "Recent")
        # Category tabs.
        self._category_grids: dict[str, _EmojiGrid] = {}
        for name, icon, items in _CATEGORIES:
            grid = _EmojiGrid(items, columns=10)
            grid.set_on_pick(self._append_emoji)
            self._category_grids[name] = grid
            self._tabs.addTab(grid, f"{icon} {name}")
        # Search results tab (hidden until the user types).
        self._search_grid: _EmojiGrid | None = None
        self._search_tab_idx = self._tabs.addTab(QWidget(), "🔍 Search")
        self._tabs.setTabVisible(self._search_tab_idx, False)
        root.addWidget(self._tabs, 1)

        # --- Preview ------------------------------------------------------
        self._preview = QLabel("")
        self._preview.setObjectName("hint")
        self._preview.setWordWrap(True)
        pf = QFont(self._preview.font())
        pf.setPointSize(14)
        self._preview.setFont(pf)
        root.addWidget(self._preview)
        self._update_preview()

        # --- Buttons ------------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save emoji")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # Show recent emoji on open.
        self._refresh_recent_tab()

    # --- recent tab ------------------------------------------------------
    def _make_recent_tab(self) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        self._recent_grid = _EmojiGrid([], columns=10)
        self._recent_grid.set_on_pick(self._append_emoji)
        lay.addWidget(self._recent_grid)
        hint = QLabel("Emoji you pick appear here for quick reuse.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return host

    def _refresh_recent_tab(self) -> None:
        if self._recent_grid is None:
            return
        recents = _load_recents()
        # Rebuild the grid contents by replacing the layout.
        # Simplest: create a fresh grid and swap it in.
        new_grid = _EmojiGrid(recents, columns=10)
        new_grid.set_on_pick(self._append_emoji)
        old = self._recent_grid
        parent_layout = old.parent().layout()
        idx = parent_layout.indexOf(old)
        parent_layout.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        parent_layout.insertWidget(idx, new_grid)
        self._recent_grid = new_grid

    # --- search ----------------------------------------------------------
    def _on_search_changed(self, text: str) -> None:
        results = _search_emojis(text)
        if not text.strip() or not results:
            self._tabs.setTabVisible(self._search_tab_idx, False)
            # If we were on the search tab, jump back to recent.
            if self._tabs.currentIndex() == self._search_tab_idx:
                self._tabs.setCurrentIndex(0)
            return
        # Rebuild the search tab content.
        # Remove the old widget and set a new one.
        old = self._tabs.widget(self._search_tab_idx)
        new_host = QWidget()
        nlay = QVBoxLayout(new_host)
        nlay.setContentsMargins(0, 0, 0, 0)
        sg = _EmojiGrid(results, columns=10)
        sg.set_on_pick(self._append_emoji)
        nlay.addWidget(sg)
        cnt = QLabel(f"{len(results)} match(es)")
        cnt.setObjectName("hint")
        nlay.addWidget(cnt)
        self._tabs.removeTab(self._search_tab_idx)
        self._tabs.insertTab(self._search_tab_idx, new_host, f"🔍 Search ({len(results)})")
        self._tabs.setTabVisible(self._search_tab_idx, True)
        self._tabs.setCurrentIndex(self._search_tab_idx)
        self._search_grid = sg

    # --- entry / preview -------------------------------------------------
    def _on_entry_changed(self, text: str) -> None:
        self._emojis = self._parse_emojis(text)
        self._update_preview()

    def _append_emoji(self, em: str) -> None:
        cur = self._entry.text()
        self._entry.setText(cur + em)
        self._entry.setFocus()
        # Refresh recent tab so the new emoji appears at the top.
        self._refresh_recent_tab()

    def _parse_emojis(self, text: str) -> list[str]:
        import emoji as _emoji

        return [ch for ch in text if _emoji.is_emoji(ch)]

    def _update_preview(self) -> None:
        if self._emojis:
            self._preview.setText(
                f"<b>Preview ({len(self._emojis)} emoji):</b>  "
                + "  ".join(self._emojis)
            )
        else:
            self._preview.setText(
                "<i>No emoji selected. The default 😀 will be used at push time.</i>"
            )

    # --- public API ------------------------------------------------------
    def selected_emojis(self) -> list[str]:
        """Return the chosen emoji list (may be empty)."""
        return list(self._emojis)


__all__ = ["EmojiPickerDialog"]
