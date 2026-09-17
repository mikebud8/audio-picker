"""Standalone library viewer: search, filters, annotation editor, transport (spec section 5.3).

Opened from the CLI (`audio-picker library --root DIR`, owning its hub and
player) or from the review window (sharing both). Single keys follow the
review window's rule: quiet while a text field has focus.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..annotations import LibraryAnnotations
from ..library import AudioLibrary
from ..paths import to_absolute
from ..player import PlayerState
from .annotation_editor import AnnotationEditor
from .annotation_hub import AnnotationHub
from .dialogs import Dialogs
from .keys import text_field_focused
from .path_delegate import PATH_ROLE, SUMMARY_ROLE, PathDelegate
from .theme import dim_color, error_css
from .transport_bar import TransportBar

ORPHAN_ROLE = Qt.ItemDataRole.UserRole + 2
ANY_TAG = "Any tag"
RATING_CHOICES = [("Any rating", 0), ("1+", 1), ("2+", 2), ("3+", 3), ("4+", 4), ("5", 5)]


def summary_for(annotations: LibraryAnnotations, rel: str) -> str:
    a = annotations.get(rel)
    parts = [f"★{a.rating}"] if a.rating is not None else []
    return " ".join(parts + a.tags)


class LibraryWindow(QMainWindow):
    play_requested = Signal()  # emitted just before this window starts playback

    def __init__(
        self,
        root: Path,
        library: AudioLibrary,
        hub: AnnotationHub,
        player,
        settings: QSettings,
        *,
        owns_hub: bool,
        owns_player: bool = False,
        dialogs=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.root = Path(root)
        self.library = library
        self.hub = hub
        self.player = player
        self.settings = settings
        self.owns_hub = owns_hub
        self.owns_player = owns_player
        self.dialogs = dialogs or Dialogs()
        self._playing_rel: str | None = None
        self._refreshing = False
        self._settling = False
        self._listed: list[tuple[str, bool]] = []

        self._build_widgets()
        self._build_actions()
        self._connect_player()
        self.hub.changed.connect(self._on_hub_changed)
        self.hub.reloaded.connect(self._on_hub_reloaded)
        if owns_hub:
            self.hub.save_failed.connect(self._on_save_failed)

        self.setWindowTitle(f"Library — {self.root.name} — Audio Picker")
        self.setMinimumSize(760, 480)
        geometry = self.settings.value("library_window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1000, 640)
        self._report_load()
        self.refresh_list()
        self.list.setFocus()

    @property
    def annotations(self) -> LibraryAnnotations:
        return self.hub.store

    # -- construction ----------------------------------------------------------------

    def _build_widgets(self) -> None:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 4, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search paths, #tag for tags")
        self.search.setClearButtonEnabled(True)
        left_layout.addWidget(self.search)

        filters = QHBoxLayout()
        self.tag_filter = QComboBox()
        self.tag_filter.setToolTip("Only files carrying this tag")
        self.rating_filter = QComboBox()
        self.rating_filter.setToolTip("Only files rated at least this")
        for text, value in RATING_CHOICES:
            self.rating_filter.addItem(text, value)
        filters.addWidget(self.tag_filter, 1)
        filters.addWidget(self.rating_filter)
        left_layout.addLayout(filters)

        self.list = QListWidget()
        self.list.setItemDelegate(PathDelegate(self.list))
        self.list.currentItemChanged.connect(self._on_current_item)
        self.list.itemDoubleClicked.connect(lambda _i: self._play_current(restart=True))
        left_layout.addWidget(self.list, 1)
        self.count_label = QLabel()
        left_layout.addWidget(self.count_label)

        self.editor = AnnotationEditor(self.hub.store)
        self.editor.changed.connect(self.hub.notify_changed)
        # The editor's minimum height grows with its chip rows, so a scroll area absorbs it
        # instead of putting a floor under the whole window.
        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Tab reaches the stars, not the viewport
        editor_scroll.setMinimumWidth(260)
        editor_scroll.setWidget(self.editor)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(editor_scroll)
        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([700, 300])

        self.transport = TransportBar(self.player, self.settings)
        self.transport.play_pause_clicked.connect(self._space)
        self.transport.stop_clicked.connect(self.player.stop)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.transport)
        self.setCentralWidget(central)

        self.warning = QLabel()
        self.warning.setStyleSheet(error_css())
        self.warning.hide()
        self.statusBar().addPermanentWidget(self.warning)

        self._refresh_tag_filter()
        self.search.textChanged.connect(lambda _t: self.refresh_list())
        self.tag_filter.currentIndexChanged.connect(lambda _i: self.refresh_list())
        self.rating_filter.currentIndexChanged.connect(lambda _i: self.refresh_list())

    def _action(self, key: str, text: str, shortcut: str, handler: Callable[[], None], *, single_key: bool) -> None:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if single_key:
            action.triggered.connect(lambda: None if text_field_focused() else handler())
        else:
            action.triggered.connect(lambda: handler())
        self.addAction(action)
        self.actions[key] = action

    def _build_actions(self) -> None:
        self.actions: dict[str, QAction] = {}
        self._action("space", "Play / pause", "Space", self._space, single_key=True)
        self._action("stop", "Stop", "S", self.player.stop, single_key=True)
        self._action("loop", "Toggle loop", "L", self.transport.loop.toggle, single_key=True)
        self._action("search", "Find", "Ctrl+F", self._focus_search, single_key=False)
        self._action("save", "Save now", "Ctrl+S", self.flush, single_key=False)
        self._action("rescan", "Rescan library", "F5", self._rescan, single_key=False)
        self._action("close", "Close", "Ctrl+W", self.close, single_key=False)
        escape = QShortcut(QKeySequence("Escape"), self)
        escape.setContext(Qt.ShortcutContext.WindowShortcut)
        escape.activated.connect(self._escape)

    def _connect_player(self) -> None:
        self.player.state_changed.connect(self._on_player_state)
        self.player.source_changed.connect(lambda _source: self._check_source())
        self.player.error.connect(lambda text: self.statusBar().showMessage(f"Playback error: {text}"))

    # -- rows --------------------------------------------------------------------------------

    def _filters_active(self) -> bool:
        return (
            bool(self.search.text().strip())
            or self.tag_filter.currentIndex() > 0
            or int(self.rating_filter.currentData() or 0) > 0
        )

    def _rows(self) -> list[tuple[str, bool]]:
        """(relative path, is_orphan) for everything the current search and filters admit."""
        store = self.hub.store
        hits = self.library.search(self.search.text(), limit=max(1, len(self.library)), annotations=store)
        tag = self.tag_filter.currentText() if self.tag_filter.currentIndex() > 0 else None
        min_rating = int(self.rating_filter.currentData() or 0)
        if tag is not None:
            hits = [p for p in hits if store.has_tag(p, tag)]
        if min_rating:
            hits = [p for p in hits if (store.get(p).rating or 0) >= min_rating]
        rows = [(p, False) for p in hits]
        if not self._filters_active():
            known = set(self.library.paths)
            rows += [(p, True) for p in store.annotated() if p not in known]
        return rows

    def refresh_list(self) -> None:
        """Rebuild the rows, keeping the current path selected where it still exists."""
        self._refreshing = True
        try:
            current = self.current_path()
            self._listed = self._rows()
            self.list.clear()
            for rel, orphan in self._listed:
                self.list.addItem(self._item(rel, orphan))
            files = sum(1 for _rel, orphan in self._listed if not orphan)
            orphans = len(self._listed) - files
            text = f"{files} file{'s' if files != 1 else ''}"
            if orphans:
                text += f", {orphans} annotated file{'s' if orphans != 1 else ''} missing on disk"
            self.count_label.setText(text)
            self._select_path(current)
        finally:
            self._refreshing = False
        self._on_current_item(self.list.currentItem(), None)

    def _item(self, rel: str, orphan: bool) -> QListWidgetItem:
        item = QListWidgetItem(rel)
        item.setData(PATH_ROLE, rel)
        item.setData(SUMMARY_ROLE, summary_for(self.hub.store, rel))
        item.setData(ORPHAN_ROLE, orphan)
        if orphan:
            item.setForeground(dim_color())
            item.setToolTip("Missing on disk: annotated, but no such file under the root")
        return item

    @staticmethod
    def is_orphan(item: QListWidgetItem | None) -> bool:
        return bool(item is not None and item.data(ORPHAN_ROLE))

    def current_path(self) -> str | None:
        item = self.list.currentItem()
        return item.data(PATH_ROLE) if item is not None else None

    def _row_for(self, rel: str) -> QListWidgetItem | None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(PATH_ROLE) == rel:
                return item
        return None

    def _select_path(self, rel: str | None) -> None:
        item = self._row_for(rel) if rel is not None else None
        if item is not None:
            self.list.setCurrentItem(item)
        elif self.list.count():
            self.list.setCurrentRow(0)

    def _refresh_tag_filter(self) -> None:
        wanted = [ANY_TAG] + self.hub.store.vocabulary()
        have = [self.tag_filter.itemText(i) for i in range(self.tag_filter.count())]
        if wanted == have:
            return
        keep = self.tag_filter.currentText()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItems(wanted)
        self.tag_filter.setCurrentText(keep if keep in wanted else ANY_TAG)
        self.tag_filter.blockSignals(False)

    def _on_current_item(self, current: QListWidgetItem | None, _previous) -> None:
        if self._refreshing:
            return
        self.editor.set_path(current.data(PATH_ROLE) if current is not None else None)

    # -- hub -----------------------------------------------------------------------------------

    def _on_hub_changed(self, rel: str) -> None:
        """Any host edited `rel`: re-apply the filters, or just repaint the row when nothing moved."""
        if self._rows() != self._listed:
            self.refresh_list()
        else:
            item = self._row_for(rel)
            if item is not None:
                item.setData(SUMMARY_ROLE, summary_for(self.hub.store, rel))
        self._refresh_tag_filter()
        if self.editor.path == rel:
            self.editor.refresh()

    def _on_hub_reloaded(self) -> None:
        self.editor.set_store(self.hub.store)
        self._report_load()
        self._refresh_tag_filter()
        self.refresh_list()

    def _rescan(self) -> None:
        self.library.refresh()
        notes = self.hub.reload()
        self.statusBar().showMessage(f"Library rescanned: {len(self.library)} audio files; {notes}.")

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _escape(self) -> None:
        self.editor.escape()
        self.list.setFocus()

    # -- playback ---------------------------------------------------------------------------

    def _play_current(self, *, restart: bool = False) -> None:
        item = self.list.currentItem()
        if item is None or self.is_orphan(item):
            return
        rel = item.data(PATH_ROLE)
        if not restart and self._playing_rel == rel and self.player.state is not PlayerState.STOPPED:
            self.player.stop()
            return
        self.play_requested.emit()
        self._playing_rel = rel
        self.player.play(to_absolute(self.root, rel))
        self.transport.set_now_playing(AudioLibrary.pack_folder(rel) or "library", rel.rsplit("/", 1)[-1])

    def _space(self) -> None:
        state = self.player.state
        if state is PlayerState.PLAYING:
            self.player.pause()
        elif state is PlayerState.PAUSED:
            self.player.resume()
        else:
            self._play_current()

    def _on_player_state(self, state: PlayerState) -> None:
        if state is PlayerState.STOPPED:
            self._playing_rel = None
            self.transport.set_now_playing(None, None)
        else:
            self._check_source()

    def _check_source(self) -> None:
        """Forget our now-playing when the shared player is playing someone else's file."""
        if self._playing_rel is not None and self.player.source != to_absolute(self.root, self._playing_rel):
            self._playing_rel = None  # the review window took the player
            self.transport.set_now_playing(None, None)

    # -- persistence -------------------------------------------------------------------------

    def _report_load(self) -> None:
        store = self.hub.store
        if self.owns_hub and store.load_error:
            self.dialogs.error(self, "Library notes not loaded", store.load_error)
        self.warning.setText(
            f"Library notes not loaded: fix {store.path.name} and rescan (F5)" if store.read_only else ""
        )
        self.warning.setVisible(store.read_only)

    def _on_save_failed(self, message: str) -> None:
        if self._settling:
            return  # the unsaved-changes dialog names the file and offers a retry: one modal is enough
        self.dialogs.error(self, "Save failed", message)

    def flush(self) -> bool:
        if not self.owns_hub:
            return True
        ok = self.hub.flush()
        if ok and not self.hub.store.dirty:
            self.statusBar().showMessage(f"Saved {datetime.now().strftime('%H:%M:%S')}")
        return ok

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        if self.owns_hub:
            self._settling = True
            try:
                while not self.hub.flush():
                    answer = self.dialogs.unsaved(self, "close", [self.hub.store.path.name])
                    if answer == "discard":
                        break
                    if answer != "retry":
                        event.ignore()
                        return
            finally:
                self._settling = False
        if self.owns_player:
            self.player.stop()
        self.settings.setValue("library_window/geometry", self.saveGeometry())
        event.accept()
