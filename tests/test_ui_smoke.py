"""GUI smoke tests (design section 15) with the Player and all dialogs faked."""

import json
import shutil
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QApplication

from audio_picker.annotations import SIDECAR_NAME, LibraryAnnotations
from audio_picker.model import load
from audio_picker.player import PlayerState
from audio_picker.ui.annotation_hub import AnnotationHub
from audio_picker.ui.main_window import MainWindow
from audio_picker.ui.path_delegate import SUMMARY_ROLE

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "review.json"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"


class FakePlayer(QObject):
    state_changed = Signal(object)
    position_changed = Signal(int, int)
    source_changed = Signal(object)
    seekable_changed = Signal(bool)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []
        self.state = PlayerState.STOPPED
        self.source: Path | None = None
        self.seekable = False
        self.position_ms = 0
        self.duration_ms = 0
        self.loop = False
        self.volume = 1.0

    def _set(self, state: PlayerState) -> None:
        if state is not self.state:
            self.state = state
            self.state_changed.emit(state)

    def play(self, path: Path) -> None:
        self.calls.append(("play", Path(path)))
        # QMediaPlayer.setSource stops first: a transient STOPPED reaches every slot before PLAYING.
        if self.state is not PlayerState.STOPPED:
            self._set(PlayerState.STOPPED)
        self.source = Path(path)
        self.source_changed.emit(self.source)
        self._set(PlayerState.PLAYING)

    def stop(self) -> None:
        self.calls.append(("stop",))
        self._set(PlayerState.STOPPED)

    def pause(self) -> None:
        self.calls.append(("pause",))
        if self.state is PlayerState.PLAYING:
            self._set(PlayerState.PAUSED)

    def resume(self) -> None:
        self.calls.append(("resume",))
        if self.source is not None:
            self._set(PlayerState.PLAYING)

    def toggle_pause(self) -> None:
        if self.state is PlayerState.PLAYING:
            self.pause()
        else:
            self.resume()

    def seek(self, ms: int) -> None:
        self.calls.append(("seek", ms))

    def set_loop(self, on: bool) -> None:
        self.calls.append(("set_loop", on))
        self.loop = on

    def set_volume(self, v: float) -> None:
        self.volume = v


class FakeDialogs:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.confirm_answer = True
        self.conflict_answer = "cancel"
        self.unsaved_answer = "discard"
        self.export_target: Path | None = None
        self.open_target: Path | None = None

    def confirm(self, parent, title: str, text: str) -> bool:
        self.calls.append(("confirm", text))
        return self.confirm_answer

    def error(self, parent, title: str, text: str) -> None:
        self.calls.append(("error", text))

    def conflict(self, parent, path: Path) -> str:
        self.calls.append(("conflict", Path(path)))
        return self.conflict_answer

    def unsaved(self, parent, action: str, files: list[str]) -> str:
        self.calls.append(("unsaved", action, tuple(files)))
        return self.unsaved_answer

    def export_path(self, parent, start: Path) -> Path | None:
        self.calls.append(("export_path",))
        return self.export_target

    def open_review_path(self, parent, start: Path) -> Path | None:
        self.calls.append(("open_review_path",))
        return self.open_target

    def add_candidate(self, parent, review, library, root, player, hub):
        self.calls.append(("add_candidate",))
        return None

    def edit_slot(self, parent, review, slot):
        self.calls.append(("edit_slot", slot.id if slot else None))
        return None

    def shortcuts(self, parent) -> None:
        self.calls.append(("shortcuts",))


@pytest.fixture
def review_file(tmp_path: Path) -> Path:
    dst = tmp_path / "review.json"
    shutil.copy(EXAMPLE, dst)
    return dst


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    """A writable copy of the audio fixture so annotation saves never touch the repo."""
    dst = tmp_path / "audio"
    shutil.copytree(FIXTURE_ROOT, dst)
    return dst


@pytest.fixture
def make_win(qtbot, tmp_path, review_file):
    def _make(root: Path = FIXTURE_ROOT) -> MainWindow:
        settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
        w = MainWindow(review_file, root, player=FakePlayer(), dialogs=FakeDialogs(), settings=settings)
        qtbot.addWidget(w)
        with qtbot.waitExposed(w):
            w.show()
        with qtbot.waitActive(w):  # a window made inside a test body is not active until the loop spins
            w.activateWindow()
        return w

    return _make


@pytest.fixture
def win(make_win) -> MainWindow:
    return make_win()


def press(qtbot, w, key, modifier=Qt.KeyboardModifier.NoModifier) -> None:
    qtbot.keyClick(QApplication.focusWidget() or w, key, modifier)


def disk(review_file: Path):
    return load(review_file)


# -- opening and navigation ------------------------------------------------------


def test_window_opens_on_example(win, review_file):
    assert "example" in win.windowTitle() and "review.json" in win.windowTitle()
    assert win.windowTitle().endswith("Audio Picker")
    assert not win.windowTitle().startswith("•")
    assert win.tree.slot_ids() == ["ui_click", "ui_confirm", "battle_hit", "battle_miss", "horn_distant"]
    assert win.tree.current_slot_id() == "ui_click"
    assert len(win.panel.rows) == 2
    assert "first-pass" in win.statusBar().currentMessage()


def test_selecting_slot_renders_right_number_of_rows(win):
    win.tree.select_slot("battle_hit")
    assert len(win.panel.rows) == 2
    win.tree.select_slot("battle_miss")
    assert len(win.panel.rows) == 1
    win.tree.select_slot("horn_distant")
    assert win.panel.rows == []
    assert "No horn sample" in win.panel.gap_notes.toPlainText()
    assert win.panel.gap_notes.isVisible()


def test_number_key_plays_candidate_absolute_path(qtbot, win):
    press(qtbot, win, Qt.Key.Key_2)
    assert win.player.calls[-1] == ("play", FIXTURE_ROOT / "packA" / "confirm.ogg")
    assert win.panel.rows[1].is_playing


def test_number_key_of_playing_candidate_stops_it(qtbot, win):
    press(qtbot, win, Qt.Key.Key_1)
    press(qtbot, win, Qt.Key.Key_1)
    assert win.player.calls[-1] == ("stop",)


def test_y_and_n_toggle_the_active_candidate(qtbot, win):
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_1)
    press(qtbot, win, Qt.Key.Key_Y)
    assert win.review.slot("ui_confirm").candidate("A003").decision == "yay"
    press(qtbot, win, Qt.Key.Key_Y)
    assert win.review.slot("ui_confirm").candidate("A003").decision == "unreviewed"
    press(qtbot, win, Qt.Key.Key_N)
    assert win.review.slot("ui_confirm").candidate("A003").decision == "nay"


def test_enter_selects_the_active_candidate(qtbot, win):
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Return)  # active defaults to candidate 1
    slot = win.review.slot("ui_confirm")
    assert slot.selected == "A003"
    assert slot.candidate("A003").decision == "yay"
    assert win.panel.rows[0].radio.isChecked()


def test_enter_on_nay_candidate_changes_nothing_and_explains(qtbot, win):
    win.tree.select_slot("battle_hit")
    press(qtbot, win, Qt.Key.Key_Return)
    assert win.review.slot("battle_hit").selected is None
    assert "nay" in win.statusBar().currentMessage().lower()


def test_autosave_timer_writes_the_file(qtbot, win, review_file):
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Y)
    assert win.windowTitle().startswith("•")
    qtbot.waitUntil(lambda: disk(review_file).slot("ui_confirm").candidate("A003").decision == "yay", timeout=3000)
    qtbot.waitUntil(lambda: not win.windowTitle().startswith("•"), timeout=3000)


def test_ctrl_down_and_up_move_between_slots_wrapping_and_stop_playback(qtbot, win):
    press(qtbot, win, Qt.Key.Key_1)
    press(qtbot, win, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert win.tree.current_slot_id() == "ui_confirm"
    assert ("stop",) in win.player.calls[win.player.calls.index(("play", FIXTURE_ROOT / "packA" / "click.wav")) :]
    press(qtbot, win, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert win.tree.current_slot_id() == "ui_click"
    press(qtbot, win, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert win.tree.current_slot_id() == "horn_distant"
    press(qtbot, win, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert win.tree.current_slot_id() == "ui_click"


def test_mouse_click_on_another_slot_stops_playback(qtbot, win):
    press(qtbot, win, Qt.Key.Key_1)
    n = len(win.player.calls)
    view = win.tree.view
    index = win.tree.index_for_slot("battle_hit")
    view.scrollTo(index)
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(index).center())
    assert win.tree.current_slot_id() == "battle_hit"
    assert ("stop",) in win.player.calls[n:]


def test_filter_that_hides_current_slot_moves_to_first_visible(win):
    win.tree.status_filter.setCurrentText("Gaps")
    assert win.tree.slot_ids() == ["horn_distant"]
    assert win.tree.current_slot_id() == "horn_distant"
    win.tree.status_filter.setCurrentText("All")
    win.tree.search.setText("battle")
    assert win.tree.slot_ids() == ["battle_hit", "battle_miss"]


# -- text fields and shortcuts ---------------------------------------------------


def test_typing_y_into_notes_does_not_change_any_decision(qtbot, win):
    notes = win.panel.rows[0].notes
    notes.setFocus()
    qtbot.keyClicks(notes, "yn1")
    slot = win.review.slot("ui_click")
    assert slot.candidate("A001").decision == "yay"  # unchanged from the file
    assert slot.candidate("A002").decision == "unreviewed"
    assert "yn1" in slot.candidate("A001").notes
    assert not any(c[0] == "play" for c in win.player.calls)


def test_escape_in_a_text_field_returns_focus_to_the_tree(qtbot, win):
    notes = win.panel.rows[0].notes
    notes.setFocus()
    assert notes.hasFocus()
    qtbot.keyClick(notes, Qt.Key.Key_Escape)
    assert win.tree.view.hasFocus()


def test_ctrl_f_focuses_search(qtbot, win):
    press(qtbot, win, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert win.tree.search.hasFocus()


# -- pending-edit safety ---------------------------------------------------------


def _type_notes(qtbot, win, text="hello"):
    notes = win.panel.rows[0].notes
    notes.setFocus()
    qtbot.keyClicks(notes, text)
    return notes


def test_ctrl_s_flushes_typed_notes(qtbot, win, review_file):
    _type_notes(qtbot, win)
    qtbot.keyClick(win.panel.rows[0].notes, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert "hello" in disk(review_file).slot("ui_click").candidate("A001").notes


def test_export_flushes_typed_notes(qtbot, win, review_file, tmp_path):
    _type_notes(qtbot, win)
    win.dialogs.export_target = tmp_path / "manifest.json"
    win.actions["export"].trigger()
    assert "hello" in disk(review_file).slot("ui_click").candidate("A001").notes
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["selections"][0]["candidate"] == "A001"


def test_slot_change_flushes_typed_notes(qtbot, win, review_file):
    _type_notes(qtbot, win)
    win.tree.select_slot("battle_hit")
    assert "hello" in disk(review_file).slot("ui_click").candidate("A001").notes


def test_close_flushes_typed_notes(qtbot, win, review_file):
    _type_notes(qtbot, win)
    assert win.close()
    assert "hello" in disk(review_file).slot("ui_click").candidate("A001").notes


def test_typing_keeps_cursor_and_scroll_position(qtbot, win):
    notes = win.panel.rows[0].notes
    notes.setFocus()
    notes.moveCursor(notes.textCursor().MoveOperation.End)
    scroll = win.panel.scroll.verticalScrollBar()
    before = scroll.value()
    qtbot.keyClicks(notes, "abc")
    assert notes.toPlainText() == "Good.abc"
    assert notes.textCursor().position() == len("Good.abc")
    assert scroll.value() == before
    assert win.panel.rows[0].notes is notes, "row was not rebuilt"


# -- yay / nay buttons -----------------------------------------------------------


def test_click_yay_twice_returns_to_unreviewed(win):
    row = win.panel.rows[1]  # A002, unreviewed
    row.yay.click()
    assert win.review.slot("ui_click").candidate("A002").decision == "yay"
    assert row.yay.isChecked() and not row.nay.isChecked()
    row.yay.click()
    assert win.review.slot("ui_click").candidate("A002").decision == "unreviewed"
    assert not row.yay.isChecked() and not row.nay.isChecked()


def test_click_yay_then_nay(win):
    row = win.panel.rows[1]
    row.yay.click()
    row.nay.click()
    assert win.review.slot("ui_click").candidate("A002").decision == "nay"
    assert row.nay.isChecked() and not row.yay.isChecked()


def test_nay_on_selected_candidate_clears_selection_and_disables_radio(win):
    row = win.panel.rows[0]  # A001, selected
    assert row.radio.isChecked()
    row.nay.click()
    assert win.review.slot("ui_click").selected is None
    assert not row.radio.isChecked()
    assert not row.radio.isEnabled()
    assert "Nay" in row.radio.toolTip()
    assert win.tree.glyph_for("ui_click") == "○"


def test_radio_selects_and_promotes(win):
    row = win.panel.rows[1]
    row.radio.click()
    slot = win.review.slot("ui_click")
    assert slot.selected == "A002"
    assert slot.candidate("A002").decision == "yay"
    assert not win.panel.rows[0].radio.isChecked()
    assert win.tree.glyph_for("ui_click") == "●"


def test_clear_selection(win):
    win.panel.clear_selection.click()
    assert win.review.slot("ui_click").selected is None
    assert not any(r.radio.isChecked() for r in win.panel.rows)


# -- remove and missing files ----------------------------------------------------


def test_remove_candidate_confirms_and_clears_selection(win):
    win.panel.rows[0].remove.click()
    assert ("confirm", "Remove A001 from ui_click?") in win.dialogs.calls
    slot = win.review.slot("ui_click")
    assert [c.id for c in slot.candidates] == ["A002"]
    assert slot.selected is None
    assert len(win.panel.rows) == 1


def test_remove_candidate_declined_changes_nothing(win):
    win.dialogs.confirm_answer = False
    win.panel.rows[0].remove.click()
    assert [c.id for c in win.review.slot("ui_click").candidates] == ["A001", "A002"]


def test_missing_files_mark_rows_and_tree(make_win, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    w = make_win(empty)
    assert w.tree.glyph_for("ui_click") == "✕"
    row = w.panel.rows[0]
    assert row.missing
    assert not row.play.isEnabled()
    assert "missing" in row.name.toolTip().lower()
    assert "missing" in w.statusBar().currentMessage()


def test_player_error_goes_to_status_bar_and_row_tooltip(qtbot, win):
    press(qtbot, win, Qt.Key.Key_1)
    win.player.error.emit("click.wav: boom")
    assert "boom" in win.statusBar().currentMessage()
    assert "boom" in win.panel.rows[0].play.toolTip()


# -- external change detection ---------------------------------------------------


def _rewrite_on_disk(review_file: Path, project: str) -> None:
    data = json.loads(review_file.read_text(encoding="utf-8"))
    data["project"] = project
    review_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_external_change_cancel_leaves_file_untouched(qtbot, win, review_file):
    _rewrite_on_disk(review_file, "edited-elsewhere")
    before = review_file.read_bytes()
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Y)
    qtbot.waitUntil(lambda: ("conflict", review_file) in win.dialogs.calls, timeout=3000)
    qtbot.wait(700)
    assert review_file.read_bytes() == before
    assert win.windowTitle().startswith("•")
    assert win.dialogs.calls.count(("conflict", review_file)) == 1


def test_external_change_reload_takes_disk_version(qtbot, win, review_file):
    _rewrite_on_disk(review_file, "edited-elsewhere")
    win.dialogs.conflict_answer = "reload"
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Y)
    qtbot.waitUntil(lambda: win.review.project == "edited-elsewhere", timeout=3000)
    assert win.review.slot("ui_confirm").candidate("A003").decision == "unreviewed"
    assert not win.windowTitle().startswith("•")
    assert "edited-elsewhere" in win.windowTitle()


def test_external_change_overwrite_takes_model_version(qtbot, win, review_file):
    _rewrite_on_disk(review_file, "edited-elsewhere")
    win.dialogs.conflict_answer = "overwrite"
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Y)
    qtbot.waitUntil(lambda: disk(review_file).slot("ui_confirm").candidate("A003").decision == "yay", timeout=3000)
    assert disk(review_file).project == "example"


def test_quit_after_cancelled_save_asks_and_can_be_cancelled(qtbot, win, review_file):
    _rewrite_on_disk(review_file, "edited-elsewhere")
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Y)
    win.dialogs.unsaved_answer = "cancel"
    assert not win.close()
    assert ("unsaved", "quit", ("review.json",)) in win.dialogs.calls
    win.dialogs.unsaved_answer = "discard"
    assert win.close()


def _review_errors(w) -> int:
    return sum(1 for c in w.dialogs.calls if c[0] == "error" and "review.json" in c[1])


def test_review_save_failure_during_quit_shows_only_the_unsaved_dialog(monkeypatch, qtbot, win, review_file):
    def _fail(review, path):
        raise OSError("disk full")

    monkeypatch.setattr("audio_picker.ui.main_window.save", _fail)
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Y)
    win.dialogs.unsaved_answer = "cancel"
    before = _review_errors(win)
    assert not win.close()
    assert win.dialogs.calls.count(("unsaved", "quit", ("review.json",))) == 1
    assert _review_errors(win) == before, "settling shows the unsaved dialog only, not a second error box"
    win.dialogs.unsaved_answer = "discard"
    assert win.close()


def test_quit_retry_after_conflict_can_overwrite(qtbot, win, review_file):
    _rewrite_on_disk(review_file, "edited-elsewhere")
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Y)

    def unsaved(parent, action, files):
        first = not any(c[0] == "unsaved" for c in win.dialogs.calls)
        win.dialogs.calls.append(("unsaved", action, tuple(files)))
        if not first:
            return "cancel"
        win.dialogs.conflict_answer = "overwrite"
        return "retry"

    win.dialogs.unsaved = unsaved
    assert win.close()
    assert disk(review_file).slot("ui_confirm").candidate("A003").decision == "yay"
    assert [c for c in win.dialogs.calls if c[0] == "unsaved"] == [("unsaved", "quit", ("review.json",))]


# -- transport -------------------------------------------------------------------


def test_loop_and_volume_reach_the_player_and_persist(win):
    win.transport.loop.setChecked(True)
    assert win.player.loop is True
    win.transport.volume.setValue(35)
    assert abs(win.player.volume - 0.35) < 1e-6
    assert win.settings.value("transport/loop", type=bool) is True
    assert win.settings.value("transport/volume", type=int) == 35


# -- active candidate signal -----------------------------------------------------------


def test_panel_emits_active_changed_on_slot_change_play_and_empty_slot(qtbot, win):
    seen: list = []
    win.panel.active_changed.connect(seen.append)
    win.tree.select_slot("ui_confirm")  # one candidate: A003 becomes active by default
    assert seen[-1] == "A003"
    win.tree.select_slot("ui_click")
    assert seen[-1] == "A001"
    press(qtbot, win, Qt.Key.Key_2)
    assert seen[-1] == "A002"
    n = len(seen)
    press(qtbot, win, Qt.Key.Key_2)  # stopping keeps A002 active: no new emission
    assert len(seen) == n
    win.tree.select_slot("horn_distant")
    assert seen[-1] is None
    assert seen == ["A003", "A001", "A002", None]


def test_space_plays_first_candidate_when_nothing_loaded(qtbot, win):
    press(qtbot, win, Qt.Key.Key_Space)
    assert win.player.calls[-1] == ("play", FIXTURE_ROOT / "packA" / "click.wav")
    press(qtbot, win, Qt.Key.Key_Space)
    assert win.player.calls[-1] == ("pause",)
    press(qtbot, win, Qt.Key.Key_S)
    assert win.player.calls[-1] == ("stop",)
    press(qtbot, win, Qt.Key.Key_L)
    assert win.transport.loop.isChecked()


# -- library annotations hub -------------------------------------------------------------


def test_window_builds_the_hub_for_its_root(make_win, tmp_root):
    w = make_win(tmp_root)
    assert isinstance(w.hub, AnnotationHub)
    assert w.hub.store.path == tmp_root / SIDECAR_NAME


def test_hub_change_autosaves_the_sidecar(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    w.hub.store.set_rating("packA/click.wav", 4)
    w.hub.notify_changed("packA/click.wav")
    qtbot.waitUntil(lambda: (tmp_root / SIDECAR_NAME).exists(), timeout=3000)
    assert LibraryAnnotations(tmp_root).get("packA/click.wav").rating == 4


def test_ctrl_s_flushes_the_sidecar(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    w.hub.store.add_tag("packA/click.wav", "ui")
    w.hub.notify_changed("packA/click.wav")
    press(qtbot, w, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert LibraryAnnotations(tmp_root).has_tag("packA/click.wav", "ui")


def test_close_flushes_the_sidecar(make_win, tmp_root):
    w = make_win(tmp_root)
    w.hub.store.set_note("packA/click.wav", "bye")
    w.hub.notify_changed("packA/click.wav")
    assert w.close()
    assert LibraryAnnotations(tmp_root).get("packA/click.wav").note == "bye"


def _break_sidecar_saves(w, tmp_root) -> None:
    """A directory where the sidecar should be makes every save raise OSError."""
    (tmp_root / SIDECAR_NAME).mkdir()
    w.hub.store.set_rating("packA/click.wav", 2)
    w.hub.notify_changed("packA/click.wav")


def _note_errors(w) -> int:
    return sum(1 for c in w.dialogs.calls if c[0] == "error" and "library notes" in c[1].lower())


def test_sidecar_save_failure_shows_an_error(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    qtbot.waitUntil(
        lambda: any(c[0] == "error" and "library notes" in c[1].lower() for c in w.dialogs.calls), timeout=3000
    )
    assert w.hub.store.dirty


def test_quit_with_unsaved_sidecar_asks_and_cancel_keeps_the_window(make_win, tmp_root):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    w.dialogs.unsaved_answer = "cancel"
    before = _note_errors(w)
    assert not w.close()
    assert ("unsaved", "quit", (SIDECAR_NAME,)) in w.dialogs.calls
    assert _note_errors(w) == before, "settling shows the unsaved dialog only, not a second error box"
    w.dialogs.unsaved_answer = "discard"
    assert w.close()


def test_quit_retry_succeeds_once_the_obstacle_is_gone(make_win, tmp_root):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    answers = iter(["retry", "cancel"])

    def unsaved(parent, action, files):
        w.dialogs.calls.append(("unsaved", action, tuple(files)))
        (tmp_root / SIDECAR_NAME).rmdir()
        return next(answers)

    w.dialogs.unsaved = unsaved
    assert w.close()
    assert LibraryAnnotations(tmp_root).get("packA/click.wav").rating == 2
    assert [c for c in w.dialogs.calls if c[0] == "unsaved"] == [("unsaved", "quit", (SIDECAR_NAME,))]


def test_unsaved_dialog_names_both_files(qtbot, make_win, tmp_root, review_file):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    _rewrite_on_disk(review_file, "edited-elsewhere")  # the review save will hit the conflict dialog (cancel)
    w.tree.select_slot("ui_confirm")
    press(qtbot, w, Qt.Key.Key_Y)
    w.dialogs.unsaved_answer = "cancel"
    assert not w.close()
    assert ("unsaved", "quit", ("review.json", SIDECAR_NAME)) in w.dialogs.calls


def test_open_other_with_unsaved_sidecar_cancel_keeps_everything(make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    w.dialogs.unsaved_answer = "cancel"
    w.dialogs.open_target = tmp_path / "never.json"
    w.actions["open"].trigger()
    assert ("unsaved", "open another review", (SIDECAR_NAME,)) in w.dialogs.calls
    assert ("open_review_path",) not in w.dialogs.calls
    assert w.hub.store.dirty


def _other_review(tmp_path: Path) -> tuple[Path, Path]:
    other_root = tmp_path / "other_audio"
    shutil.copytree(FIXTURE_ROOT, other_root)
    other_review = tmp_path / "other" / "review.json"
    other_review.parent.mkdir()
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["root"] = "../other_audio"
    other_review.write_text(json.dumps(data), encoding="utf-8")
    return other_review, other_root


def test_open_other_review_flushes_and_switches_the_store(make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    w.hub.store.add_tag("packA/click.wav", "first")
    w.hub.notify_changed("packA/click.wav")
    other_review, other_root = _other_review(tmp_path)
    w.dialogs.open_target = other_review
    w.actions["open"].trigger()
    assert LibraryAnnotations(tmp_root).has_tag("packA/click.wav", "first")
    assert w.hub.store.path == other_root / SIDECAR_NAME
    assert not w.hub.store.has_tag("packA/click.wav", "first")


def test_open_other_discard_with_unsaved_sidecar_switches_store(make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    w.dialogs.unsaved_answer = "discard"
    other_review, other_root = _other_review(tmp_path)
    w.dialogs.open_target = other_review
    w.actions["open"].trigger()
    assert w.hub.store.path == other_root / SIDECAR_NAME
    assert not w.hub.store.dirty


def test_malformed_sidecar_is_reported_once_and_the_store_is_read_only(make_win, tmp_root):
    (tmp_root / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    w = make_win(tmp_root)
    assert sum(1 for c in w.dialogs.calls if c[0] == "error" and "version" in c[1]) == 1
    assert w.hub.store.read_only
    assert w.annotations_warning.isVisible()
    assert "rescan" in w.annotations_warning.text()


def test_rescan_reloads_a_fixed_sidecar_and_clears_the_warning(make_win, tmp_root):
    (tmp_root / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    w = make_win(tmp_root)
    good = {"version": 1, "tags": [], "files": {"packA/click.wav": {"tags": ["fixed"]}}}
    (tmp_root / SIDECAR_NAME).write_text(json.dumps(good), encoding="utf-8")
    w.actions["rescan"].trigger()
    assert not w.hub.store.read_only
    assert not w.annotations_warning.isVisible()
    assert w.hub.store.has_tag("packA/click.wav", "fixed")
    assert "reloaded" in w.statusBar().currentMessage()


def test_rescan_keeps_a_dirty_store_and_says_so(make_win, tmp_root):
    w = make_win(tmp_root)
    w.hub.store.add_tag("packA/click.wav", "mine")
    w.hub.notify_changed("packA/click.wav")
    w.actions["rescan"].trigger()  # fires before the 500 ms autosave, so the store is still dirty
    assert w.hub.store.has_tag("packA/click.wav", "mine")
    assert "not reloaded" in w.statusBar().currentMessage()


# -- library notes dock ------------------------------------------------------------------


def test_dock_is_hidden_by_default_and_toggles_from_the_view_menu(win):
    assert not win.notes_dock.isVisible()
    win.notes_dock.toggleViewAction().trigger()
    assert win.notes_dock.isVisible()
    assert win.notes_dock.objectName() == "libraryNotesDock"
    assert [a.text() for a in win.menuBar().actions()] == ["&File", "&Slot", "&Candidate", "&View", "&Help"]


def test_dock_follows_the_active_candidate(qtbot, win):
    win.notes_dock.show()
    assert win.notes_editor.path == "packA/click.wav"
    press(qtbot, win, Qt.Key.Key_2)
    assert win.notes_editor.path == "packA/confirm.ogg"
    win.tree.select_slot("battle_hit")
    assert win.notes_editor.path == "packB/hit.mp3"
    win.tree.select_slot("horn_distant")
    assert win.notes_editor.path is None


def test_dock_edit_goes_through_the_hub_and_autosaves(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    w.notes_dock.show()
    with qtbot.waitSignal(w.hub.changed):
        w.notes_editor.stars[4].click()
    assert w.hub.store.get("packA/click.wav").rating == 5
    qtbot.waitUntil(lambda: (tmp_root / SIDECAR_NAME).exists(), timeout=3000)


def test_dock_edit_of_a_backslash_path_writes_a_canonical_key(make_win, tmp_root, review_file):
    """A hand-edited review can carry `packA\\click.wav`; the sidecar must stay loadable."""
    data = json.loads(review_file.read_text(encoding="utf-8"))
    data["slots"][0]["candidates"][0]["path"] = "packA\\click.wav"
    review_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    w = make_win(tmp_root)
    w.notes_dock.show()
    w.notes_editor.stars[2].click()
    assert w.hub.flush()
    assert LibraryAnnotations(tmp_root).get("packA/click.wav").rating == 3
    assert not LibraryAnnotations(tmp_root).read_only
    # Both windows key on the emitted path, so the viewer must see the edit without a reselect.
    w.actions["library"].trigger()
    lw = w.library_window
    w.notes_editor.stars[4].click()
    assert lw._row_for("packA/click.wav").data(SUMMARY_ROLE).startswith("★5")
    lw.list.setCurrentItem(lw._row_for("packA/click.wav"))
    lw.editor.stars[1].click()
    assert [s.text() for s in w.notes_editor.stars] == ["★", "★", "☆", "☆", "☆"]


def test_dock_reflects_a_change_made_elsewhere(make_win, tmp_root):
    w = make_win(tmp_root)
    w.notes_dock.show()
    w.hub.store.set_rating("packA/click.wav", 3)
    w.hub.notify_changed("packA/click.wav")
    assert [s.text() for s in w.notes_editor.stars] == ["★", "★", "★", "☆", "☆"]


def test_typing_y_in_the_dock_note_does_not_mark_a_decision(qtbot, make_win, tmp_root):
    # tmp_root, not the shared fixture: the note dirties the store and closing the window writes it out.
    w = make_win(tmp_root)
    w.notes_dock.show()
    w.notes_editor.note.setFocus()
    qtbot.keyClicks(w.notes_editor.note, "yn1")
    assert w.review.slot("ui_click").candidate("A002").decision == "unreviewed"
    assert not any(c[0] == "play" for c in w.player.calls)
    assert w.hub.store.get("packA/click.wav").note == "yn1"


def test_enter_in_the_dock_tag_field_adds_a_tag_and_tree_enter_still_selects(qtbot, make_win, tmp_root):
    # tmp_root, not the shared fixture: the committed tag dirties the store and closing writes it out.
    w = make_win(tmp_root)
    w.notes_dock.show()
    w.notes_editor.tag_input.setFocus()
    qtbot.keyClicks(w.notes_editor.tag_input, "half")
    qtbot.keyClick(w.notes_editor.tag_input, Qt.Key.Key_Return)
    assert w.hub.store.has_tag("packA/click.wav", "half")
    assert w.notes_editor.tag_input.text() == ""
    assert w.review.slot("ui_click").selected == "A001"  # unchanged
    assert not w.windowTitle().startswith("•")  # the review is untouched: no re-select, no edit
    # The has_tag / empty-field pair above is what proves the key reached the field.
    w.tree.select_slot("ui_confirm")
    w.tree.view.setFocus()  # selecting a slot leaves focus in the dock; the user comes back to the tree
    press(qtbot, w, Qt.Key.Key_Return)
    assert w.review.slot("ui_confirm").selected == "A003"


def test_escape_in_the_dock_clears_the_tag_field_and_returns_to_the_tree(qtbot, win):
    win.notes_dock.show()
    win.notes_editor.tag_input.setFocus()
    qtbot.keyClicks(win.notes_editor.tag_input, "half")
    qtbot.keyClick(win.notes_editor.tag_input, Qt.Key.Key_Escape)
    assert win.notes_editor.tag_input.text() == ""
    assert win.tree.view.hasFocus()


def test_dock_state_is_saved_and_restored(make_win):
    w = make_win()  # both windows share the one settings.ini of the make_win fixture
    w.notes_dock.show()
    assert w.close()
    w2 = make_win()
    assert w2.notes_dock.isVisible()


def test_dock_is_disabled_while_the_sidecar_is_malformed_and_recovers_on_rescan(make_win, tmp_root):
    (tmp_root / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    w = make_win(tmp_root)
    w.notes_dock.show()
    assert w.notes_editor.path == "packA/click.wav"
    assert not w.notes_editor.note.isEnabled()
    (tmp_root / SIDECAR_NAME).write_text('{"version": 1, "tags": [], "files": {}}', encoding="utf-8")
    w.actions["rescan"].trigger()
    assert w.notes_editor.path == "packA/click.wav"
    assert w.notes_editor.note.isEnabled()
    assert not w.annotations_warning.isVisible()


def test_open_other_review_repoints_the_dock(make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    w.notes_dock.show()
    other_review, other_root = _other_review(tmp_path)
    w.dialogs.open_target = other_review
    w.actions["open"].trigger()
    assert w.notes_editor.path == "packA/click.wav"
    w.notes_editor.stars[0].click()
    assert w.hub.store.path == other_root / SIDECAR_NAME
    assert w.hub.store.get("packA/click.wav").rating == 1


def _rewrite_candidate_path_on_disk(review_file: Path, path: str) -> None:
    data = json.loads(review_file.read_text(encoding="utf-8"))
    data["slots"][0]["candidates"][0]["path"] = path
    review_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_dock_follows_a_reload_that_changes_the_path_of_the_same_id(qtbot, win, review_file):
    win.notes_dock.show()
    _rewrite_candidate_path_on_disk(review_file, "packB/hit.mp3")
    win.dialogs.conflict_answer = "reload"
    press(qtbot, win, Qt.Key.Key_Y)
    qtbot.waitUntil(lambda: win.notes_editor.path == "packB/hit.mp3", timeout=3000)


def test_add_candidate_edits_autosave_while_open_even_when_cancelled(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)

    def fake_add(parent, review, library, root, player, hub):
        hub.store.add_tag("packA/confirm.ogg", "warm")
        hub.notify_changed("packA/confirm.ogg")
        qtbot.waitUntil(lambda: LibraryAnnotations(tmp_root).has_tag("packA/confirm.ogg", "warm"), timeout=3000)
        return None  # cancelled

    w.dialogs.add_candidate = fake_add
    w.actions["add_candidate"].trigger()
    assert [c.id for c in w.review.slot("ui_click").candidates] == ["A001", "A002"]
    assert w.hub.store.has_tag("packA/confirm.ogg", "warm")


# -- library viewer from the review window --------------------------------------------


def test_library_viewer_opens_once_shares_hub_and_player_and_stops_review_playback(qtbot, win):
    press(qtbot, win, Qt.Key.Key_1)
    n = len(win.player.calls)
    win.actions["library"].trigger()
    lw = win.library_window
    assert lw.isVisible()
    assert lw.player is win.player
    assert lw.hub is win.hub
    assert ("stop",) in win.player.calls[n:]  # the viewer's transport bar also logs set_loop after it
    assert not lw.owns_hub and not lw.owns_player
    win.actions["library"].trigger()
    assert win.library_window is lw
    assert [a.text() for a in win.menuBar().actions()[0].menu().actions() if a.text()][:5] == [
        "&Open…",
        "&Save now",
        "&Export manifest…",
        "&Rescan library",
        "&Library viewer…",
    ]


def test_viewer_playback_clears_the_review_highlight(qtbot, win):
    press(qtbot, win, Qt.Key.Key_1)
    win.actions["library"].trigger()
    lw = win.library_window
    qtbot.keyClick(win.tree.view, Qt.Key.Key_1)  # the review plays again while the viewer is open
    assert win.panel.rows[0].is_playing
    lw.list.setCurrentRow(3)
    lw.list.itemDoubleClicked.emit(lw.list.item(3))
    assert not win.panel.rows[0].is_playing
    assert win.transport.now_playing.text() == "Nothing playing"
    # The shared player going on playing the viewer's file must not light the row again.
    win.player.state_changed.emit(PlayerState.STOPPED)
    win.player.state_changed.emit(PlayerState.PLAYING)
    assert not win.panel.rows[0].is_playing


def test_reshowing_the_viewer_stops_review_playback(qtbot, win):
    win.actions["library"].trigger()
    lw = win.library_window
    lw.close()
    qtbot.keyClick(win.tree.view, Qt.Key.Key_1)
    n = len(win.player.calls)
    win.actions["library"].trigger()
    assert win.library_window is lw and lw.isVisible()
    assert ("stop",) in win.player.calls[n:]


def test_open_other_frees_the_retired_viewer(qtbot, make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    w.actions["library"].trigger()
    old = w.library_window
    other_review, _other_root = _other_review(tmp_path)
    w.dialogs.open_target = other_review
    w.actions["open"].trigger()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(old)
    # Nothing the review window still emits may reach the freed viewer.
    w.transport.loop.setChecked(True)
    w.hub.store.set_rating("packA/click.wav", 2)
    w.hub.notify_changed("packA/click.wav")


def test_open_other_detaches_the_retired_viewer_from_the_hub(make_win, tmp_root, tmp_path):
    """deleteLater waits for the event loop; the new store must not reach the old viewer first."""
    w = make_win(tmp_root)
    w.actions["library"].trigger()
    old = w.library_window
    calls = []
    old.refresh_list = lambda: calls.append(1)
    other_review, _other_root = _other_review(tmp_path)
    w.dialogs.open_target = other_review
    w.actions["open"].trigger()
    assert calls == []


def test_cancelling_the_open_dialog_keeps_the_viewer(make_win, tmp_root):
    w = make_win(tmp_root)
    w.actions["library"].trigger()
    w.dialogs.open_target = None  # the user cancelled the file dialog
    w.actions["open"].trigger()
    assert w.library_window is not None and w.library_window.isVisible()


def test_viewer_and_review_transport_bars_stay_in_sync(qtbot, win):
    win.actions["library"].trigger()
    lw = win.library_window
    lw.transport.loop.setChecked(True)
    assert win.transport.loop.isChecked()
    assert win.player.loop is True
    assert win.settings.value("transport/loop", type=bool) is True
    win.transport.volume.setValue(35)
    assert lw.transport.volume.value() == 35
    assert abs(win.player.volume - 0.35) < 1e-6


def test_viewer_and_dock_stay_in_sync_through_the_hub(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    w.notes_dock.show()
    w.actions["library"].trigger()
    lw = w.library_window
    lw.list.setCurrentRow(1)  # packA/click.wav, also the dock's file
    lw.editor.stars[3].click()
    assert [s.text() for s in w.notes_editor.stars] == ["★", "★", "★", "★", "☆"]
    qtbot.waitUntil(lambda: LibraryAnnotations(tmp_root).get("packA/click.wav").rating == 4, timeout=3000)
    w.notes_editor.stars[0].click()
    assert lw.list.item(1).data(SUMMARY_ROLE) == "★1"


def test_rescan_in_the_review_window_refreshes_an_open_viewer(make_win, tmp_root):
    w = make_win(tmp_root)
    w.actions["library"].trigger()
    lw = w.library_window
    (tmp_root / "packA" / "new.wav").write_bytes(b"")
    w.actions["rescan"].trigger()
    assert "packA/new.wav" in [lw.list.item(i).text() for i in range(lw.list.count())]


def test_open_other_review_closes_the_viewer(make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    w.actions["library"].trigger()
    other_review, _other_root = _other_review(tmp_path)
    w.dialogs.open_target = other_review
    w.actions["open"].trigger()
    assert w.library_window is None


def test_quit_closes_the_viewer(make_win, tmp_root):
    w = make_win(tmp_root)
    w.actions["library"].trigger()
    lw = w.library_window
    assert w.close()
    assert not lw.isVisible()
