"""
AlphaIndexWidget
~~~~~~~~~~~~~~~~
A compact letter-index bar that appears above artist / album / album-artist
tables.  It shows A–Z buttons plus a '#' bucket (digits and non-Latin chars)
and optional sub-page navigation when a single letter contains more entries
than a configured page-size threshold.

Usage pattern
-------------
1. Instantiate and add above your QTableView.
2. Connect ``letterChanged`` to your reload slot.
3. Call ``refresh(counts)`` with a ``{letter: int}`` mapping after every DB
   query (use the get_*_letter_counts helpers).
4. Call ``set_page_size`` to control how many rows trigger sub-pages.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

_LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["#"]

# Articles stripped when ``ignore_articles`` is True.
_SORT_ARTICLES = ("the ", "a ", "an ")


def sort_key(name: str, ignore_articles: bool = False) -> str:
    """Return the effective sort letter for *name*.

    When *ignore_articles* is True the leading articles "The ", "A " and
    "An " are stripped before taking the first character.
    """
    s = (name or "").strip().upper()
    if ignore_articles:
        for art in _SORT_ARTICLES:
            if s.startswith(art.upper()):
                s = s[len(art):].lstrip()
                break
    if not s:
        return "#"
    ch = s[0]
    return ch if ch.isalpha() and ch.isascii() else "#"


class AlphaIndexWidget(QWidget):
    """Horizontal letter-index bar with optional sub-page controls.

    Signals
    -------
    letterChanged(letter: str, page: int)
        Emitted when the user picks a different letter or page.
        ``letter`` is one of A–Z or '#' or '' (meaning "show all").
        ``page`` is 0-based.
    """

    letterChanged = Signal(str, int)   # (letter, page)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._counts: dict[str, int] = {}
        self._current_letter: str = ""   # '' = all
        self._current_page: int = 0
        self._page_size: int = 200        # rows per sub-page
        self._ignore_articles: bool = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(0)

        # "All" button
        self._btn_all = self._make_letter_btn("All", special=True)
        self._btn_all.setCheckable(True)
        self._btn_all.setChecked(True)
        self._btn_all.clicked.connect(lambda: self._select_letter(""))
        outer.addWidget(self._btn_all)

        # Letter buttons
        self._letter_buttons: dict[str, QPushButton] = {}
        for ch in _LETTERS:
            btn = self._make_letter_btn(ch)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, c=ch: self._select_letter(c))
            self._letter_buttons[ch] = btn
            outer.addWidget(btn)

        outer.addStretch(1)

        # Sub-page controls (shown when a selected letter has > page_size items)
        self._prev_btn = QPushButton("‹")
        self._prev_btn.setFixedWidth(32)
        self._prev_btn.setFixedHeight(28)
        self._prev_btn.clicked.connect(self._prev_page)
        outer.addWidget(self._prev_btn)

        self._page_label = QLabel("1/1")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setFixedWidth(52)
        f_lbl = QFont()
        f_lbl.setPointSize(10)
        f_lbl.setBold(True)
        self._page_label.setFont(f_lbl)
        outer.addWidget(self._page_label)

        self._next_btn = QPushButton("›")
        self._next_btn.setFixedWidth(32)
        self._next_btn.setFixedHeight(28)
        self._next_btn.clicked.connect(self._next_page)
        outer.addWidget(self._next_btn)

        self._set_pager_visible(False)
        self._apply_styles()

    # ------------------------------------------------------------------ public

    def set_page_size(self, size: int) -> None:
        self._page_size = max(10, int(size))

    def set_ignore_articles(self, ignore: bool) -> None:
        self._ignore_articles = bool(ignore)

    def refresh(self, counts: dict[str, int]) -> None:
        """Update enabled/disabled state of letter buttons.

        *counts* maps letter → number of items (from a DB query).
        Letters with 0 items are greyed out but still visible.
        """
        self._counts = dict(counts)
        for ch, btn in self._letter_buttons.items():
            has = bool(self._counts.get(ch, 0))
            btn.setEnabled(has)
            btn.setToolTip(f"{self._counts.get(ch, 0)} item(s)" if has else "")

        # If currently-selected letter no longer has items, reset to "all".
        if self._current_letter and not self._counts.get(self._current_letter, 0):
            self._select_letter("", emit=False)

        self._update_pager()

    def current_letter(self) -> str:
        return self._current_letter

    def current_page(self) -> int:
        return self._current_page

    def total_pages(self) -> int:
        if not self._current_letter:
            return 1
        count = self._counts.get(self._current_letter, 0)
        return max(1, -(-count // self._page_size))   # ceiling division

    def db_offset(self) -> int:
        """Convenience: offset to pass to the DB query for current page."""
        return self._current_page * self._page_size

    def db_limit(self) -> int:
        """Convenience: limit to pass to the DB query for current page."""
        return self._page_size

    def reset(self) -> None:
        """Reset to 'All' without emitting a signal."""
        self._select_letter("", emit=False)

    # ------------------------------------------------------------ private logic

    def _select_letter(self, letter: str, *, emit: bool = True) -> None:
        if letter == self._current_letter:
            # Same letter clicked again → do nothing (keeps page intact)
            return
        self._current_letter = letter
        self._current_page = 0
        self._update_checked_state()
        self._update_pager()
        if emit:
            self.letterChanged.emit(self._current_letter, self._current_page)

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._update_pager()
            self.letterChanged.emit(self._current_letter, self._current_page)

    def _next_page(self) -> None:
        if self._current_page < self.total_pages() - 1:
            self._current_page += 1
            self._update_pager()
            self.letterChanged.emit(self._current_letter, self._current_page)

    def _update_checked_state(self) -> None:
        self._btn_all.setChecked(self._current_letter == "")
        for ch, btn in self._letter_buttons.items():
            btn.setChecked(ch == self._current_letter)

    def _update_pager(self) -> None:
        pages = self.total_pages()
        visible = bool(self._current_letter) and pages > 1
        self._set_pager_visible(visible)
        if visible:
            self._page_label.setText(f"{self._current_page + 1}/{pages}")
            self._prev_btn.setEnabled(self._current_page > 0)
            self._next_btn.setEnabled(self._current_page < pages - 1)

    def _set_pager_visible(self, visible: bool) -> None:
        self._prev_btn.setVisible(visible)
        self._page_label.setVisible(visible)
        self._next_btn.setVisible(visible)

    # --------------------------------------------------------------- styling

    def _make_letter_btn(self, text: str, *, special: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(28)
        if special:
            btn.setFixedWidth(44)
        else:
            btn.setFixedWidth(28)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        btn.setFont(f)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return btn

    def _apply_styles(self) -> None:
        self.setObjectName("AlphaIndexWidget")
        self.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 4px;
                padding: 2px 2px;
                color: palette(text);
                background: transparent;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:checked {
                background: palette(highlight);
                color: palette(highlighted-text);
            }
            QPushButton:hover:!checked {
                background: palette(midlight);
            }
            QPushButton:disabled {
                color: palette(mid);
                opacity: 0.4;
            }
            #AlphaIndexWidget {
                border-bottom: 1px solid palette(mid);
                padding-bottom: 4px;
                padding-top: 2px;
            }
        """)

