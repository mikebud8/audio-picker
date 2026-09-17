"""Rating, tags and note for one library file (library annotations spec, section 4).

Knows the `LibraryAnnotations` store and a current relative path, nothing
about reviews, slots or the player. Every control change writes straight
through to the store and emits `changed(rel)`.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QStringListModel, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..annotations import RATINGS, LibraryAnnotations, normalise_tag
from .path_delegate import path_html
from .theme import dim_color, dim_css

FILLED, EMPTY = "★", "☆"
MIN_TAIL_PX = 60  # below this the pack folder gets elided too, rather than eating the file name


class FlowLayout(QLayout):
    """Wraps its items into rows, like text. Port of Qt's flowlayout example."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), dry_run=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, dry_run=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, *, dry_run: bool) -> int:
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and row_height > 0:
                x = rect.x()
                y += row_height + self._spacing
                row_height = 0
            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y()


class TagChip(QFrame):
    removed = Signal(str)

    def __init__(self, tag: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tag = tag
        self.setObjectName("tagChip")
        self.setStyleSheet(
            "#tagChip { border: 1px solid palette(mid); border-radius: 9px; background: palette(alternate-base); }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 2, 1)
        layout.setSpacing(2)
        self.label = QLabel(tag)
        self.remove = QToolButton()
        self.remove.setText("×")
        self.remove.setAutoRaise(True)
        self.remove.setToolTip(f"Remove tag {tag}")
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.clicked.connect(lambda: self.removed.emit(self.tag))
        layout.addWidget(self.label)
        layout.addWidget(self.remove)


class AnnotationEditor(QWidget):
    """Stars, tag chips and a note for one path.

    Hosts with very little vertical space should wrap this in a `QScrollArea`.
    After the store is reloaded from disk, a host must call `refresh()` or
    `set_store()` so the read-only state is re-evaluated.
    """

    changed = Signal(str)  # relative path whose annotation was edited
    escape_pressed = Signal()  # Escape in a text field, after the tag field was cleared

    def __init__(self, store: LibraryAnnotations, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._rel: str | None = None
        self._loading = False
        self._emitting = False
        self.chips: list[TagChip] = []
        self.setMinimumWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.path_label = QLabel()
        self.path_label.setTextFormat(Qt.TextFormat.RichText)
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.path_label)

        rating_row = QWidget()
        rating_row.setToolTip("Recording quality, not preference")
        rating_layout = QHBoxLayout(rating_row)
        rating_layout.setContentsMargins(0, 0, 0, 0)
        rating_layout.setSpacing(0)
        self.stars: list[QToolButton] = []
        for n in RATINGS:
            star = QToolButton()
            star.setText(EMPTY)
            star.setAutoRaise(True)
            star.setCursor(Qt.CursorShape.PointingHandCursor)
            star.setStyleSheet("font-size: 16pt;")
            # The star tooltips shadow the row's, so each one repeats what the rating means.
            star.setToolTip(f"Rate {n} of 5" + (" (junk)" if n == 1 else "") + ". Recording quality, not preference")
            star.clicked.connect(lambda _checked=False, n=n: self._on_star(n))
            rating_layout.addWidget(star)
            self.stars.append(star)
        self.unrated = QLabel("unrated")
        self.unrated.setStyleSheet(dim_css())
        rating_layout.addSpacing(6)
        rating_layout.addWidget(self.unrated)
        rating_layout.addStretch(1)
        layout.addWidget(rating_row)

        self.chips_container = QWidget()
        self.chips_layout = FlowLayout(self.chips_container)
        layout.addWidget(self.chips_container)

        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Add tag (Enter or comma)")
        self.tag_input.setClearButtonEnabled(True)
        self._completer_model = QStringListModel(self)
        self.completer = QCompleter(self._completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.tag_input.setCompleter(self.completer)
        # With the popup closed, eventFilter consumes Enter so a dialog's default button never sees it.
        # With the popup open, QCompleter forwards the key with `widget->event()`, which bypasses event
        # filters, so `returnPressed` is the one that fires; and picking a completion (Down-Enter, or a
        # click) fires `activated` instead. Both commit here; whichever runs second is a duplicate no-op.
        # `activated` must be queued: QLineEdit's own handler sets the field text after a direct slot and
        # would leave the completed word sitting in the field.
        self.tag_input.returnPressed.connect(self._commit_tag_field)
        self.completer.activated[str].connect(self._on_completion_activated, Qt.ConnectionType.QueuedConnection)
        self.tag_input.textEdited.connect(self._on_tag_text_edited)
        self.tag_input.installEventFilter(self)
        layout.addWidget(self.tag_input)

        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("Note: what you learned listening to this file")
        self.note.setTabChangesFocus(True)
        self.note.setMinimumHeight(self.note.fontMetrics().lineSpacing() * 4 + 12)
        self.note.textChanged.connect(self._on_note_changed)
        self.note.installEventFilter(self)
        layout.addWidget(self.note, 1)

        self.set_path(None)

    # -- public ---------------------------------------------------------------

    @property
    def path(self) -> str | None:
        return self._rel

    def set_store(self, store: LibraryAnnotations) -> None:
        self._store = store
        self.set_path(None)

    def set_path(self, rel: str | None) -> None:
        self._rel = rel
        self._load()

    def refresh(self) -> None:
        """Re-read the current path from the store; leaves the note cursor alone when the text is unchanged."""
        if self._emitting:
            return  # our own edit, already on screen: reloading would rebuild every chip per keystroke
        self._load()

    def escape(self) -> None:
        """Clear a half-typed tag. Hosts with a window-level Escape shortcut call this."""
        self.tag_input.clear()

    def chip_tags(self) -> list[str]:
        return [c.tag for c in self.chips]

    def completer_words(self) -> list[str]:
        return list(self._completer_model.stringList())

    # -- loading --------------------------------------------------------------

    def _load(self) -> None:
        self._loading = True
        try:
            rel = self._rel
            read_only = self._store.read_only
            enabled = rel is not None and not read_only
            for star in self.stars:
                star.setEnabled(enabled)
            self.tag_input.setEnabled(enabled)
            self.note.setEnabled(enabled)
            self.tag_input.setPlaceholderText(
                "Library notes are read-only until the sidecar is fixed" if read_only else "Add tag (Enter or comma)"
            )
            self._completer_model.setStringList(self._store.vocabulary())
            if rel is None:
                self.path_label.setText('<span style="color: %s">No file</span>' % dim_color().name())
                self.path_label.setToolTip("")
                self._show_rating(None)
                self._show_tags([])
                if self.note.toPlainText():
                    self.note.clear()
                return
            annotation = self._store.get(rel)
            self._render_path()
            self._show_rating(annotation.rating)
            self._show_tags(annotation.tags)
            if self.note.toPlainText() != annotation.note:
                self.note.setPlainText(annotation.note)
        finally:
            self._loading = False

    def _render_path(self) -> None:
        rel = self._rel or ""
        self.path_label.setToolTip(rel)
        folder, sep, rest = rel.partition("/")
        fm = self.path_label.fontMetrics()
        available = max(40, self.path_label.width() - 8)
        bold_font = QFont(self.path_label.font())
        bold_font.setBold(True)
        # The folder renders bold, so measure it bold; a folder that leaves no room for the
        # file name is elided along with the rest instead of swallowing it.
        folder_width = QFontMetrics(bold_font).horizontalAdvance(folder + "/") if sep else 0
        if sep and available - folder_width >= MIN_TAIL_PX:
            rest = fm.elidedText(rest, Qt.TextElideMode.ElideMiddle, available - folder_width)
            shown = f"{folder}/{rest}"
        else:
            shown = fm.elidedText(rel, Qt.TextElideMode.ElideMiddle, available)
        self.path_label.setText(path_html(shown, self.palette().text().color().name()))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self._rel is not None:
            self._render_path()
        self._fit_chips()

    def _fit_chips(self) -> None:
        """Hold the chip area open at its wrapped height; otherwise a short host clips rows silently."""
        height = self.chips_layout.heightForWidth(self.chips_container.width()) if self.chips else 0
        self.chips_container.setMinimumHeight(max(0, height))

    def _show_rating(self, rating: int | None) -> None:
        for n, star in zip(RATINGS, self.stars):
            star.setText(FILLED if rating is not None and n <= rating else EMPTY)
        self.unrated.setVisible(rating is None and self._rel is not None)

    def _show_tags(self, tags: list[str]) -> None:
        for chip in self.chips:
            self.chips_layout.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self.chips = []
        for tag in tags:
            chip = TagChip(tag)
            chip.removed.connect(self._remove_tag)
            self.chips_layout.addWidget(chip)
            chip.show()  # addWidget defers the child's show to the event loop; a hidden widget measures 0x0
            self.chips.append(chip)
        self.chips_container.setVisible(bool(tags))
        self._fit_chips()
        self.chips_container.updateGeometry()

    # -- editing --------------------------------------------------------------

    def _emit(self) -> None:
        if self._rel is None:
            return
        self._emitting = True  # a host that fans `changed` back into `refresh()` must not reload under us
        try:
            self.changed.emit(self._rel)
        finally:
            self._emitting = False

    def _on_star(self, n: int) -> None:
        if self._rel is None:
            return
        current = self._store.get(self._rel).rating
        self._store.set_rating(self._rel, None if current == n else n)
        self._show_rating(self._store.get(self._rel).rating)
        self._emit()

    def _commit_tag(self, text: str) -> bool:
        """Add `text` as a tag if it normalises to something new. Returns True if the store changed."""
        if self._rel is None:
            return False
        try:
            tag = normalise_tag(text)
        except ValueError:
            return False
        if self._store.has_tag(self._rel, tag):
            return False
        self._store.add_tag(self._rel, tag)
        self._show_tags(self._store.get(self._rel).tags)
        self._completer_model.setStringList(self._store.vocabulary())
        self._emit()
        return True

    def _commit_tag_field(self) -> None:
        self._commit_tag(self.tag_input.text())
        self.tag_input.clear()

    def _on_completion_activated(self, text: str) -> None:
        """A completion was chosen in the popup (Enter or a click)."""
        self._commit_tag(text)
        self.tag_input.clear()

    def _on_tag_text_edited(self, text: str) -> None:
        if "," not in text:
            return
        *done, remainder = text.split(",")
        for part in done:
            self._commit_tag(part)
        self.tag_input.setText(remainder.lstrip())

    def _remove_tag(self, tag: str) -> None:
        if self._rel is None:
            return
        self._store.remove_tag(self._rel, tag)
        self._show_tags(self._store.get(self._rel).tags)
        self._emit()

    def _on_note_changed(self) -> None:
        if self._loading or self._rel is None:
            return
        text = self.note.toPlainText()
        if self._store.get(self._rel).note == text:
            return
        self._store.set_note(self._rel, text)
        self._emit()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and obj is self.tag_input
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            event.accept()  # keep a host window's Return shortcut from stealing the commit
            return True
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if obj is self.tag_input and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._commit_tag_field()
                return True  # consumed: a dialog's default button must not fire
            if key == Qt.Key.Key_Escape:
                if obj is self.tag_input and self.completer.popup().isVisible():
                    return False  # belt and braces: the popup has already eaten Escape to close itself
                self.escape()
                self.escape_pressed.emit()
                return True
        return super().eventFilter(obj, event)
