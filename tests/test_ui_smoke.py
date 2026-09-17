"""GUI smoke tests (design section 15) with the Player and all dialogs faked."""

import json
import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QApplication

from audio_picker.model import load
from audio_picker.player import PlayerState
from audio_picker.ui.main_window import MainWindow

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
        self.quit_answer = True
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

    def quit_without_saving(self, parent) -> bool:
        self.calls.append(("quit_without_saving",))
        return self.quit_answer

    def export_path(self, parent, start: Path) -> Path | None:
        self.calls.append(("export_path",))
        return self.export_target

    def open_review_path(self, parent, start: Path) -> Path | None:
        self.calls.append(("open_review_path",))
        return self.open_target

    def add_candidate(self, parent, review, library, root, player):
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
def make_win(qtbot, tmp_path, review_file):
    def _make(root: Path = FIXTURE_ROOT) -> MainWindow:
        settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
        w = MainWindow(review_file, root, player=FakePlayer(), dialogs=FakeDialogs(), settings=settings)
        qtbot.addWidget(w)
        w.show()
        qtbot.waitExposed(w)
        w.activateWindow()
        qtbot.waitActive(w)
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


def test_quit_after_cancelled_save_asks_for_confirmation(qtbot, win, review_file):
    _rewrite_on_disk(review_file, "edited-elsewhere")
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Y)
    win.dialogs.quit_answer = False
    assert not win.close()
    assert ("quit_without_saving",) in win.dialogs.calls
    win.dialogs.quit_answer = True
    assert win.close()


# -- transport -------------------------------------------------------------------


def test_loop_and_volume_reach_the_player_and_persist(win):
    win.transport.loop.setChecked(True)
    assert win.player.loop is True
    win.transport.volume.setValue(35)
    assert abs(win.player.volume - 0.35) < 1e-6
    assert win.settings.value("transport/loop", type=bool) is True
    assert win.settings.value("transport/volume", type=int) == 35


def test_space_plays_first_candidate_when_nothing_loaded(qtbot, win):
    press(qtbot, win, Qt.Key.Key_Space)
    assert win.player.calls[-1] == ("play", FIXTURE_ROOT / "packA" / "click.wav")
    press(qtbot, win, Qt.Key.Key_Space)
    assert win.player.calls[-1] == ("pause",)
    press(qtbot, win, Qt.Key.Key_S)
    assert win.player.calls[-1] == ("stop",)
    press(qtbot, win, Qt.Key.Key_L)
    assert win.transport.loop.isChecked()
