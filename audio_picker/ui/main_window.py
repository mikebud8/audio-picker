"""Main window: menus, splitter, shortcuts, autosave and file safety (design 13.1, 13.6, 13.8)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QScrollArea, QSplitter, QVBoxLayout, QWidget

from ..annotations import LibraryAnnotations
from ..check import CheckReport, check_review
from ..export import build_manifest
from ..library import AudioLibrary
from ..model import Candidate, Review, ReviewError, Slot, load, save
from ..paths import resolve_root, to_absolute
from ..player import PlayerState
from .annotation_editor import AnnotationEditor
from .annotation_hub import AnnotationHub
from .dialogs import Dialogs
from .keys import text_field_focused
from .library_window import LibraryWindow
from .slot_panel import SlotPanel
from .slot_tree import SlotTree
from .theme import error_css
from .transport_bar import TransportBar

AUTOSAVE_MS = 500


def _fingerprint(path: Path) -> tuple[int, int, str] | None:
    try:
        st = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns, digest)


class MainWindow(QMainWindow):
    def __init__(
        self,
        review_path: Path,
        root: Path,
        *,
        player,
        dialogs=None,
        settings: QSettings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.player = player
        self.dialogs = dialogs or Dialogs()
        self.settings = settings or QSettings("audio-picker", "audio-picker")
        self.review_path = Path(review_path)
        self.root = Path(root)
        self.review: Review = load(self.review_path)
        self.library = AudioLibrary(self.root)
        self.hub = AnnotationHub(LibraryAnnotations(self.root), self)
        self.hub.save_failed.connect(self._on_annotations_save_failed)
        self.hub.reloaded.connect(self._on_annotations_reloaded)
        self._fingerprint = _fingerprint(self.review_path)
        self._dirty = False
        self._saving = False
        self._settling = False
        self._current_slot: str | None = None
        self._playing_cid: str | None = None
        self.library_window: LibraryWindow | None = None
        self._missing_slots: set[str] = set()
        self._missing_cids: set[str] = set()
        self.report: CheckReport = CheckReport()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_MS)
        self._save_timer.timeout.connect(self._autosave)

        self._build_widgets()
        self._build_actions()
        self._build_menus()
        self._connect_player()

        self.setMinimumSize(900, 560)
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1200, 760)
        state = self.settings.value("window/state")
        if state is not None:
            self.restoreState(state)
        self.settings.setValue("last_file", str(self.review_path))

        self._run_check()
        self._report_annotations_load()
        self.tree.set_review(self.review, self._missing_slots)
        self._update_title()
        self.tree.view.setFocus()

    # -- construction --------------------------------------------------------------

    def _build_widgets(self) -> None:
        self.tree = SlotTree()
        self.panel = SlotPanel()
        self.transport = TransportBar(self.player, self.settings)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.panel, 1)
        right_layout.addWidget(self.transport)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 7)
        self.splitter.setSizes([360, 840])
        self.setCentralWidget(self.splitter)
        self.annotations_warning = QLabel()
        self.annotations_warning.setStyleSheet(error_css())
        self.annotations_warning.hide()
        self.statusBar().addPermanentWidget(self.annotations_warning)

        self.notes_editor = AnnotationEditor(self.hub.store)
        self.notes_editor.changed.connect(self.hub.notify_changed)
        # Belt and braces: this window's Escape shortcut already covers the dock, floating or not
        # (a floating dock is a Tool window parented here), but the editor does not rely on that.
        self.notes_editor.escape_pressed.connect(self.tree.view.setFocus)
        # The editor's minimum height grows with its chip rows, so a scroll area absorbs it
        # instead of letting the dock put a floor under the whole window.
        notes_scroll = QScrollArea()
        notes_scroll.setWidgetResizable(True)
        notes_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        notes_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        notes_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Tab reaches the stars, not the viewport
        notes_scroll.setMinimumWidth(240)
        notes_scroll.setWidget(self.notes_editor)
        self.notes_dock = QDockWidget("Library notes", self)
        self.notes_dock.setObjectName("libraryNotesDock")
        self.notes_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)
        self.notes_dock.setWidget(notes_scroll)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.notes_dock)
        self.notes_dock.hide()

        self.tree.current_slot_changed.connect(self._on_current_slot)
        self.panel.play_clicked.connect(self._toggle_candidate)
        self.panel.decision_clicked.connect(self._toggle_decision)
        self.panel.select_clicked.connect(self._select)
        self.panel.notes_edited.connect(self._notes_edited)
        self.panel.remove_clicked.connect(self._remove_candidate)
        self.panel.edit_slot_clicked.connect(self._edit_slot)
        self.panel.clear_selection_clicked.connect(self._clear_selection)
        self.panel.add_candidate_clicked.connect(self._add_candidate)
        self.transport.play_pause_clicked.connect(self._space)
        self.transport.stop_clicked.connect(self.player.stop)
        self.panel.active_changed.connect(self._on_active_changed)
        self.hub.changed.connect(self._on_annotation_changed)

    def _action(
        self,
        key: str,
        text: str,
        shortcut: str | list[str] | None,
        handler: Callable[[], None],
        *,
        single_key: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            keys = [shortcut] if isinstance(shortcut, str) else shortcut
            action.setShortcuts([QKeySequence(k) for k in keys])
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if single_key:
            action.triggered.connect(lambda: None if self._text_focused() else handler())
        else:
            action.triggered.connect(lambda: handler())
        self.addAction(action)
        self.actions[key] = action
        return action

    def _build_actions(self) -> None:
        self.actions: dict[str, QAction] = {}
        self._action("open", "&Open…", "Ctrl+O", self._open_other)
        self._action("save", "&Save now", "Ctrl+S", self.flush)
        self._action("export", "&Export manifest…", None, self._export)
        self._action("rescan", "&Rescan library", None, self._rescan)
        self._action("library", "&Library viewer…", None, self._open_library_window)
        self._action("quit", "&Quit", "Ctrl+Q", self.close)
        self._action("add_slot", "&Add slot…", "Ctrl+N", self._add_slot)
        self._action("edit_slot", "&Edit slot…", "Ctrl+E", self._edit_slot)
        self._action("remove_slot", "&Remove slot", None, self._remove_slot)
        self._action("next_slot", "&Next slot", "Ctrl+Down", self.tree.next_slot)
        self._action("prev_slot", "&Previous slot", "Ctrl+Up", self.tree.previous_slot)
        self._action("add_candidate", "&Add candidate…", "Ctrl+Shift+N", self._add_candidate)
        self._action("remove_candidate", "&Remove candidate", None, self._remove_active_candidate)
        self._action("shortcuts", "&Keyboard shortcuts", None, lambda: self.dialogs.shortcuts(self))
        self._action("search", "Find slot", "Ctrl+F", self._focus_search)

        for n in range(1, 10):
            self._action(f"play_{n}", f"Play candidate {n}", str(n), lambda n=n: self._play_number(n), single_key=True)
        self._action("space", "Pause / resume", "Space", self._space, single_key=True)
        self._action("stop", "Stop", "S", self.player.stop, single_key=True)
        self._action("loop", "Toggle loop", "L", self.transport.loop.toggle, single_key=True)
        self._action("yay", "Mark yay", "Y", lambda: self._toggle_active_decision("yay"), single_key=True)
        self._action("nay", "Mark nay", "N", lambda: self._toggle_active_decision("nay"), single_key=True)
        self._action("select", "Select candidate", ["Return", "Enter"], self._select_active, single_key=True)

        escape = QShortcut(QKeySequence("Escape"), self)
        escape.setContext(Qt.ShortcutContext.WindowShortcut)
        escape.activated.connect(self._escape)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        for key in ("open", "save", "export", "rescan", "library"):
            file_menu.addAction(self.actions[key])
        file_menu.addSeparator()
        file_menu.addAction(self.actions["quit"])
        slot_menu = bar.addMenu("&Slot")
        for key in ("add_slot", "edit_slot", "remove_slot"):
            slot_menu.addAction(self.actions[key])
        slot_menu.addSeparator()
        for key in ("next_slot", "prev_slot"):
            slot_menu.addAction(self.actions[key])
        cand_menu = bar.addMenu("&Candidate")
        for key in ("add_candidate", "remove_candidate"):
            cand_menu.addAction(self.actions[key])
        view_menu = bar.addMenu("&View")
        view_menu.addAction(self.notes_dock.toggleViewAction())
        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.actions["shortcuts"])

    def _connect_player(self) -> None:
        self.player.state_changed.connect(self._on_player_state)
        self.player.error.connect(self._on_player_error)

    # -- helpers -------------------------------------------------------------------

    @staticmethod
    def _text_focused() -> bool:
        return text_field_focused()

    def _slot(self) -> Slot | None:
        return self.review.slot(self._current_slot) if self._current_slot else None

    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def _update_title(self) -> None:
        dot = "• " if self._dirty else ""
        self.setWindowTitle(f"{dot}{self.review.project} — {self.review_path.name} — Audio Picker")

    # -- check --------------------------------------------------------------------

    def _run_check(self) -> None:
        self.report = check_review(self.review, self.root)
        self._missing_slots = {f.slot for f in self.report.findings if f.code == "missing_file"}
        self._missing_cids = {f.candidate for f in self.report.findings if f.code == "missing_file" and f.candidate}
        missing = len(self._missing_cids)
        unselected = sum(1 for f in self.report.findings if f.code == "first_pass_unselected")
        parts = []
        if missing:
            parts.append(f"{missing} missing file{'s' if missing != 1 else ''}")
        parts.append(f"{unselected} first-pass slot{'s' if unselected != 1 else ''} unselected")
        self._status(", ".join(parts))

    # -- slot navigation ----------------------------------------------------------

    def _on_current_slot(self, slot_id: str) -> None:
        if slot_id == self._current_slot:
            return
        self.flush()
        self.player.stop()
        self._playing_cid = None
        self._current_slot = slot_id or None
        slot = self._slot()
        self.panel.show_slot(slot, self.review, self._missing_cids)
        self.transport.set_now_playing(None, None)

    def _on_active_changed(self, cid) -> None:
        slot = self._slot()
        candidate = slot.candidate(cid) if slot is not None and cid else None
        self.notes_editor.set_path(candidate.path if candidate is not None else None)

    def _focus_search(self) -> None:
        self.tree.search.setFocus()
        self.tree.search.selectAll()

    def _escape(self) -> None:
        self.notes_editor.escape()
        self.tree.view.setFocus()

    # -- mutations -----------------------------------------------------------------

    def mutate(self, fn: Callable[[Review], None], *, slot_id: str, rebuild_panel: bool = False) -> None:
        """Apply `fn` to the model now; the disk write is debounced (design 13.8)."""
        fn(self.review)
        self.tree.refresh_slot(slot_id)
        if rebuild_panel and slot_id == self._current_slot:
            self.panel.show_slot(self._slot(), self.review, self._missing_cids)
        else:
            self.panel.refresh()
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._update_title()
        self._save_timer.start()

    def _autosave(self) -> None:
        if self._dirty:
            self._save()

    def flush(self) -> bool:
        """Cancel the timers and save both files now if dirty. False if either is still unsaved."""
        self._save_timer.stop()
        review_ok = self._save() if self._dirty else True
        notes_ok = self.hub.flush()
        return review_ok and notes_ok

    # -- unsaved changes ------------------------------------------------------------------

    def _unsaved_files(self) -> list[str]:
        files = []
        if self._dirty:
            files.append(self.review_path.name)
        if self.hub.store.dirty:
            files.append(self.hub.store.path.name)
        return files

    def settle_unsaved(self, action: str) -> bool:
        """Flush both files; on failure ask try again / discard / cancel. True means go ahead."""
        self._settling = True
        try:
            while not self.flush():
                answer = self.dialogs.unsaved(self, action, self._unsaved_files())
                if answer == "discard":
                    return True
                if answer != "retry":
                    return False
            return True
        finally:
            self._settling = False

    # -- library annotations ----------------------------------------------------------------

    def _report_annotations_load(self) -> None:
        """Show a malformed-sidecar error and keep a permanent warning while the store is read-only."""
        store = self.hub.store
        if store.load_error:
            self.dialogs.error(self, "Library notes not loaded", store.load_error)
        self.annotations_warning.setText(
            f"Library notes not loaded: fix {store.path.name} and rescan" if store.read_only else ""
        )
        self.annotations_warning.setVisible(store.read_only)

    def _on_annotation_changed(self, rel: str) -> None:
        if self.notes_editor.path == rel:
            self.notes_editor.refresh()

    def _on_annotations_reloaded(self) -> None:
        self._report_annotations_load()
        self.notes_editor.set_store(self.hub.store)
        self._on_active_changed(self.panel.active_candidate_id())

    def _open_library_window(self) -> None:
        """Show the library viewer, built once and kept: it shares this window's hub and player."""
        self.player.stop()  # spec 5.3: the review window stops playback before showing the viewer
        self._playing_cid = None
        if self.library_window is not None:
            self.library_window.show()
            self.library_window.raise_()
            self.library_window.activateWindow()
            return
        lw = LibraryWindow(
            self.root,
            self.library,
            self.hub,
            self.player,
            self.settings,
            owns_hub=False,
            owns_player=False,
            dialogs=self.dialogs,
            parent=self,
        )
        # Two transport bars, one player: loop and volume have no player signal to follow, so
        # mirror them both ways. Both signals only fire on a real change, so this cannot loop.
        lw.transport.loop.toggled.connect(self.transport.loop.setChecked)
        self.transport.loop.toggled.connect(lw.transport.loop.setChecked)
        lw.transport.volume.valueChanged.connect(self.transport.volume.setValue)
        self.transport.volume.valueChanged.connect(lw.transport.volume.setValue)
        lw.play_requested.connect(self._on_viewer_play)
        self.library_window = lw
        lw.show()

    def _close_library_window(self) -> None:
        if self.library_window is not None:
            lw = self.library_window
            self.library_window = None
            lw.close()
            # Free it: a retired viewer would go on rebuilding its rows against the old root
            # every time the hub reports an edit. Every slot it holds is a bound method or a
            # QObject slot, so Qt drops them all with the object.
            lw.deleteLater()

    def _on_viewer_play(self) -> None:
        self._playing_cid = None
        self.panel.set_playing(None)
        self.transport.set_now_playing(None, None)

    def _on_annotations_save_failed(self, message: str) -> None:
        if self._settling:
            return  # the unsaved-changes dialog names the file and offers a retry: one modal is enough
        self.dialogs.error(self, "Save failed", message)

    def _changed_on_disk(self) -> bool:
        try:
            st = self.review_path.stat()
        except OSError:
            return False  # gone: writing recreates it
        if self._fingerprint is None:
            return False
        size, mtime, digest = self._fingerprint
        if (st.st_size, st.st_mtime_ns) == (size, mtime):
            return False
        try:
            current = hashlib.sha256(self.review_path.read_bytes()).hexdigest()
        except OSError:
            return False
        if current == digest:
            self._fingerprint = (st.st_size, st.st_mtime_ns, digest)
            return False
        return True

    def _save(self) -> bool:
        if self._saving:
            return False
        self._saving = True
        try:
            if self._changed_on_disk():
                answer = self.dialogs.conflict(self, self.review_path)
                if answer == "reload":
                    return self._reload_from_disk()
                if answer != "overwrite":
                    self._save_timer.stop()
                    self._status("Not saved: the file changed on disk. Save again to decide.")
                    return False
            try:
                save(self.review, self.review_path)
            except OSError as e:
                self._save_timer.stop()
                if not self._settling:  # settling names the file and offers a retry: one modal is enough
                    self.dialogs.error(self, "Save failed", f"Could not write {self.review_path}:\n{e}")
                return False
            self._fingerprint = _fingerprint(self.review_path)
            self._dirty = False
            self._update_title()
            self._status(f"Saved {datetime.now().strftime('%H:%M:%S')}")
            return True
        finally:
            self._saving = False

    def _reload_from_disk(self) -> bool:
        try:
            review = load(self.review_path)
        except ReviewError as e:
            self._save_timer.stop()
            self.dialogs.error(
                self, "Reload failed", f"{self.review_path.name} could not be loaded; keeping the current model.\n\n{e}"
            )
            return False
        self.review = review
        self._fingerprint = _fingerprint(self.review_path)
        self._dirty = False
        self._rebuild_all()
        self._status("Reloaded from disk")
        return True

    def _rebuild_all(self) -> None:
        self.player.stop()
        self._playing_cid = None
        self._run_check()
        keep = self._current_slot
        self._current_slot = None
        self.tree.set_review(self.review, self._missing_slots)
        if keep and self.tree.current_slot_id() == keep:
            self._on_current_slot(keep)
        self._update_title()
        # A reload can keep the candidate id and change its path, which emits nothing.
        self._on_active_changed(self.panel.active_candidate_id())

    # -- playback -------------------------------------------------------------------

    def _play_candidate(self, cid: str) -> None:
        slot = self._slot()
        candidate = slot.candidate(cid) if slot else None
        if candidate is None:
            return
        if cid in self._missing_cids:
            self.panel.set_active(cid)
            self._status(f"{cid}: file is missing ({candidate.path})")
            return
        self.panel.set_active(cid)
        self._playing_cid = cid
        row = self.panel.row_for(cid)
        if row is not None:
            row.set_error_tooltip("Stop")
        self.player.play(to_absolute(self.root, candidate.path))
        self.panel.set_playing(cid)
        self.transport.set_now_playing(cid, candidate.path.rsplit("/", 1)[-1])

    def _toggle_candidate(self, cid: str) -> None:
        if self._playing_cid == cid and self.player.state is not PlayerState.STOPPED:
            self.player.stop()
        else:
            self._play_candidate(cid)

    def _play_number(self, n: int) -> None:
        if n - 1 < len(self.panel.rows):
            self._toggle_candidate(self.panel.rows[n - 1].cid)

    def _space(self) -> None:
        state = self.player.state
        if state is PlayerState.PLAYING:
            self.player.pause()
        elif state is PlayerState.PAUSED:
            self.player.resume()
        elif self._playing_cid is not None and self.panel.row_for(self._playing_cid) is not None:
            self._play_candidate(self._playing_cid)
        else:
            active = self.panel.active_candidate_id()
            if active is not None:
                self._play_candidate(active)

    def _on_player_state(self, state: PlayerState) -> None:
        if state is PlayerState.STOPPED:
            self.panel.set_playing(None)
            self.transport.set_now_playing(None, None)
        elif self._playing_cid is not None:
            self.panel.set_playing(self._playing_cid)

    def _on_player_error(self, text: str) -> None:
        self._status(f"Playback error: {text}")
        if self._playing_cid is not None:
            row = self.panel.row_for(self._playing_cid)
            if row is not None:
                row.set_error_tooltip(f"Playback error: {text}")

    # -- decisions and selection ---------------------------------------------------

    def _toggle_decision(self, cid: str, which: str) -> None:
        slot = self._slot()
        candidate = slot.candidate(cid) if slot else None
        if candidate is None:
            return
        new = which if candidate.decision != which else "unreviewed"
        self.mutate(lambda r: slot.set_decision(cid, new), slot_id=slot.id)

    def _toggle_active_decision(self, which: str) -> None:
        active = self.panel.active_candidate_id()
        if active is not None:
            self._toggle_decision(active, which)

    def _select(self, cid: str) -> None:
        slot = self._slot()
        candidate = slot.candidate(cid) if slot else None
        if candidate is None:
            return
        if candidate.decision == "nay":
            self.panel.refresh()  # put the radio back
            self._status(f"{cid} is marked Nay; change the rating to select it")
            return
        self.mutate(lambda r: slot.select(cid), slot_id=slot.id)

    def _select_active(self) -> None:
        active = self.panel.active_candidate_id()
        if active is not None:
            self._select(active)

    def _clear_selection(self) -> None:
        slot = self._slot()
        if slot is None or slot.selected is None:
            return
        self.mutate(lambda r: setattr(slot, "selected", None), slot_id=slot.id)

    def _notes_edited(self, cid: str, text: str) -> None:
        slot = self._slot()
        candidate = slot.candidate(cid) if slot else None
        if candidate is None or candidate.notes == text:
            return
        self.mutate(lambda r: setattr(candidate, "notes", text), slot_id=slot.id)

    # -- candidates ------------------------------------------------------------------

    def _remove_candidate(self, cid: str) -> None:
        slot = self._slot()
        candidate = slot.candidate(cid) if slot else None
        if candidate is None:
            return
        if not self.dialogs.confirm(self, "Remove candidate", f"Remove {cid} from {slot.id}?"):
            return
        if self._playing_cid == cid:
            self.player.stop()
            self._playing_cid = None

        def remove(_r: Review) -> None:
            slot.candidates.remove(candidate)
            if slot.selected == cid:
                slot.selected = None

        self.mutate(remove, slot_id=slot.id, rebuild_panel=True)

    def _remove_active_candidate(self) -> None:
        active = self.panel.active_candidate_id()
        if active is not None:
            self._remove_candidate(active)

    def _add_candidate(self) -> None:
        slot = self._slot()
        if slot is None:
            return
        self.player.stop()
        result = self.dialogs.add_candidate(self, self.review, self.library, self.root, self.player, self.hub)
        self.player.stop()
        if result is None:
            return
        cid = self.review.next_candidate_id()
        folder = AudioLibrary.pack_folder(result.path)
        pack_id = next((pid for pid, p in self.review.packs.items() if p.folder == folder), None)
        candidate = Candidate(
            id=cid,
            path=result.path,
            pack=pack_id,
            role=result.role,
            why=result.why,
            listen_for="",
            proposed_use="",
            decision="unreviewed",
            notes="",
        )
        self.mutate(lambda r: slot.candidates.append(candidate), slot_id=slot.id, rebuild_panel=True)
        self._run_check()
        self.tree.set_missing(self._missing_slots)
        self.panel.set_missing(self._missing_cids)
        if pack_id is None:
            self._status(f"Added {cid} with no pack: folder {folder!r} matches no pack (edit the JSON to add packs)")
        else:
            self._status(f"Added {cid} ({self.review.packs[pack_id].name})")

    # -- slots ---------------------------------------------------------------------------

    def _add_slot(self) -> None:
        result = self.dialogs.edit_slot(self, self.review, None)
        if result is None:
            return
        slot = Slot(result.id, result.category, result.function, result.priority, result.notes, None, [])

        def add(r: Review) -> None:
            r.slots.append(slot)
            if slot.category not in r.categories:
                r.categories.append(slot.category)

        add(self.review)
        self._mark_dirty()
        self.tree.set_review(self.review, self._missing_slots)
        self.tree.select_slot(slot.id)

    def _edit_slot(self) -> None:
        slot = self._slot()
        if slot is None:
            return
        result = self.dialogs.edit_slot(self, self.review, slot)
        if result is None:
            return

        def apply(r: Review) -> None:
            slot.category = result.category
            slot.function = result.function
            slot.priority = result.priority
            slot.notes = result.notes
            if slot.category not in r.categories:
                r.categories.append(slot.category)

        apply(self.review)
        self._mark_dirty()
        self._run_check()
        self.tree.set_review(self.review, self._missing_slots)
        self.panel.refresh()

    def _remove_slot(self) -> None:
        slot = self._slot()
        if slot is None:
            return
        n = len(slot.candidates)
        text = f"Remove slot {slot.id}" + (f" and its {n} candidate{'s' if n != 1 else ''}?" if n else "?")
        if not self.dialogs.confirm(self, "Remove slot", text):
            return
        self.player.stop()
        ids = self.tree.slot_ids()
        neighbour = None
        if slot.id in ids and len(ids) > 1:
            i = ids.index(slot.id)
            neighbour = ids[i + 1] if i + 1 < len(ids) else ids[i - 1]
        self.review.slots.remove(slot)
        self._mark_dirty()
        self._current_slot = None
        self._run_check()
        self.tree.set_review(self.review, self._missing_slots)
        if neighbour:
            self.tree.select_slot(neighbour)

    # -- file menu ---------------------------------------------------------------------

    def _export(self) -> None:
        self.flush()
        target = self.dialogs.export_path(self, self.review_path.parent / "manifest.json")
        if target is None:
            return
        manifest = build_manifest(self.review, self.root, datetime.now(timezone.utc))
        try:
            Path(target).write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
            )
        except OSError as e:
            self.dialogs.error(self, "Export failed", f"Could not write {target}:\n{e}")
            return
        n = len(manifest["selections"])
        self._status(f"Exported {n} selection{'s' if n != 1 else ''} to {Path(target).name}")

    def _rescan(self) -> None:
        self.library.refresh()
        self._run_check()
        self.tree.set_missing(self._missing_slots)
        self.panel.set_missing(self._missing_cids)
        notes = self.hub.reload()
        self._status(
            f"Library rescanned: {len(self.library)} audio files; {notes}. " + self.statusBar().currentMessage()
        )

    def _open_other(self) -> None:
        if not self.settle_unsaved("open another review"):
            return
        target = self.dialogs.open_review_path(self, self.review_path.parent)
        if target is None:
            return
        target = Path(target)
        try:
            review = load(target)
            root = resolve_root(target, review.root, None)
        except ReviewError as e:
            self.dialogs.error(self, "Cannot open review", str(e))
            return
        self._close_library_window()  # only now: it is bound to the root, library and store we leave
        self.review_path = target
        self.root = root
        self.review = review
        self.library = AudioLibrary(root)
        self.hub.set_store(LibraryAnnotations(root))
        self._fingerprint = _fingerprint(target)
        self._dirty = False
        self.settings.setValue("last_file", str(target))
        self._rebuild_all()

    # -- lifecycle --------------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.settle_unsaved("quit"):
            event.ignore()
            return
        self._close_library_window()
        self.player.stop()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        event.accept()
