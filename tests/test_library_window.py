"""Standalone library viewer (spec section 5.3)."""

import json
import shutil
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QSettings, Qt

from audio_picker.annotations import SIDECAR_NAME, LibraryAnnotations
from audio_picker.library import AudioLibrary
from audio_picker.player import PlayerState
from audio_picker.ui.annotation_hub import AnnotationHub
from audio_picker.ui.library_window import LibraryWindow
from audio_picker.ui.path_delegate import SUMMARY_ROLE
from tests.test_ui_smoke import FakeDialogs, FakePlayer, press

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"
ALL_FILES = ["loose/miss.wav", "packA/click.wav", "packA/confirm.ogg", "packB/hit.mp3"]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    dst = tmp_path / "audio"
    shutil.copytree(FIXTURE_ROOT, dst)
    store = LibraryAnnotations(dst)
    store.add_tag("packA/click.wav", "ui")
    store.set_rating("packA/click.wav", 4)
    store.add_tag("packB/hit.mp3", "hit")
    store.set_rating("packB/hit.mp3", 2)
    store.add_tag("packZ/gone.wav", "orphan")
    store.save()
    return dst


@pytest.fixture
def make_lw(qtbot, tmp_path, root):
    def _make(*, owns_hub: bool = True, player=None, hub=None) -> LibraryWindow:
        settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
        w = LibraryWindow(
            root,
            AudioLibrary(root),
            hub or AnnotationHub(LibraryAnnotations(root)),
            player or FakePlayer(),
            settings,
            owns_hub=owns_hub,
            owns_player=owns_hub,
            dialogs=FakeDialogs(),
        )
        qtbot.addWidget(w)
        with qtbot.waitExposed(w):
            w.show()
        with qtbot.waitActive(w):  # a window made inside a test body is not active until the loop spins
            w.activateWindow()
        return w

    return _make


@pytest.fixture
def lw(make_lw) -> LibraryWindow:
    return make_lw()


def rows(w: LibraryWindow) -> list[str]:
    return [w.list.item(i).text() for i in range(w.list.count())]


def tag_choices(w: LibraryWindow) -> list[str]:
    return [w.tag_filter.itemText(i) for i in range(w.tag_filter.count())]


# -- listing and filters ---------------------------------------------------------------


def test_lists_every_file_then_orphans_greyed(lw):
    assert rows(lw) == ALL_FILES + ["packZ/gone.wav"]
    orphan = lw.list.item(4)
    assert "Missing on disk" in orphan.toolTip()
    assert lw.is_orphan(orphan)
    assert lw.list.item(1).data(SUMMARY_ROLE) == "★4 ui"
    assert lw.list.item(2).data(SUMMARY_ROLE) == ""
    assert lw.count_label.text() == "4 files, 1 annotated file missing on disk"
    assert lw.windowTitle().endswith("Audio Picker")


def test_empty_library_lists_only_orphans(qtbot, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    store = LibraryAnnotations(empty)
    store.add_tag("packZ/gone.wav", "orphan")
    store.save()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = LibraryWindow(
        empty,
        AudioLibrary(empty),
        AnnotationHub(LibraryAnnotations(empty)),
        FakePlayer(),
        settings,
        owns_hub=True,
        owns_player=True,
        dialogs=FakeDialogs(),
    )
    qtbot.addWidget(w)
    with qtbot.waitExposed(w):
        w.show()
    assert rows(w) == ["packZ/gone.wav"]
    assert w.count_label.text().startswith("0 files")
    assert w.editor.path == "packZ/gone.wav"


def test_search_hides_orphans_and_hash_terms_work(lw):
    lw.search.setText("pack")
    assert rows(lw) == ["packA/click.wav", "packA/confirm.ogg", "packB/hit.mp3"]
    lw.search.setText("#ui")
    assert rows(lw) == ["packA/click.wav"]
    lw.search.setText("")
    assert len(rows(lw)) == 5


def test_tag_and_rating_filters_combine(lw):
    assert tag_choices(lw) == ["Any tag", "hit", "orphan", "ui"]
    lw.tag_filter.setCurrentText("hit")
    assert rows(lw) == ["packB/hit.mp3"]
    lw.tag_filter.setCurrentText("Any tag")
    lw.rating_filter.setCurrentText("3+")
    assert rows(lw) == ["packA/click.wav"]
    lw.rating_filter.setCurrentText("1+")
    lw.tag_filter.setCurrentText("ui")
    assert rows(lw) == ["packA/click.wav"]


# -- editing and synchronisation ----------------------------------------------------------


def test_current_row_drives_the_editor_and_edits_update_the_row(qtbot, lw):
    lw.list.setCurrentRow(2)  # packA/confirm.ogg
    assert lw.editor.path == "packA/confirm.ogg"
    lw.editor.stars[2].click()
    assert lw.list.item(2).data(SUMMARY_ROLE) == "★3"
    qtbot.keyClicks(lw.editor.tag_input, "warm")
    qtbot.keyClick(lw.editor.tag_input, Qt.Key.Key_Return)
    assert lw.list.item(2).data(SUMMARY_ROLE) == "★3 warm"
    assert tag_choices(lw) == ["Any tag", "hit", "orphan", "ui", "warm"]
    assert lw.editor.path == "packA/confirm.ogg", "repainting a row keeps the current one"


def test_removing_the_filtered_tag_drops_the_row(lw):
    lw.tag_filter.setCurrentText("ui")
    assert rows(lw) == ["packA/click.wav"]
    assert lw.editor.path == "packA/click.wav"
    lw.editor.chips[0].remove.click()
    assert rows(lw) == []
    assert lw.editor.path is None


def test_lowering_the_rating_below_the_threshold_drops_the_row(lw):
    lw.rating_filter.setCurrentText("3+")
    assert rows(lw) == ["packA/click.wav"]
    lw.editor.stars[1].click()  # rating 2
    assert rows(lw) == []


def test_clearing_an_orphan_removes_it(lw):
    lw.list.setCurrentRow(4)
    lw.editor.chips[0].remove.click()
    assert rows(lw) == ALL_FILES


def test_change_from_another_host_updates_row_and_editor(lw):
    lw.list.setCurrentRow(2)
    lw.hub.store.set_rating("packA/confirm.ogg", 5)
    lw.hub.notify_changed("packA/confirm.ogg")
    assert lw.list.item(2).data(SUMMARY_ROLE) == "★5"
    assert [s.text() for s in lw.editor.stars] == ["★"] * 5


def test_reloaded_rebuilds_from_the_store_and_library(lw, root):
    (root / "packA" / "new.wav").write_bytes(b"")
    good = {"version": 1, "tags": [], "files": {"packA/new.wav": {"rating": 1}}}
    (root / SIDECAR_NAME).write_text(json.dumps(good), encoding="utf-8")
    lw.library.refresh()
    lw.hub.reload()
    assert "packA/new.wav" in rows(lw)
    assert lw.list.item(rows(lw).index("packA/new.wav")).data(SUMMARY_ROLE) == "★1"
    assert tag_choices(lw) == ["Any tag"]


def test_rescan_action_refreshes_library_and_notes(lw, root):
    (root / "packA" / "new.wav").write_bytes(b"")
    lw.actions["rescan"].trigger()
    assert "packA/new.wav" in rows(lw)
    assert "reloaded" in lw.statusBar().currentMessage()


# -- playback -------------------------------------------------------------------------------


def test_double_click_and_space_play_pause_and_stop(qtbot, lw):
    lw.list.setCurrentRow(1)
    lw.list.itemDoubleClicked.emit(lw.list.item(1))
    assert lw.player.calls[-1] == ("play", lw.root / "packA" / "click.wav")
    assert "click.wav" in lw.transport.now_playing.text()
    lw.list.setFocus()
    press(qtbot, lw, Qt.Key.Key_Space)
    assert lw.player.calls[-1] == ("pause",)
    press(qtbot, lw, Qt.Key.Key_Space)
    assert lw.player.calls[-1] == ("resume",)
    press(qtbot, lw, Qt.Key.Key_S)
    assert lw.player.calls[-1] == ("stop",)
    assert lw.transport.now_playing.text() == "Nothing playing"


def test_space_on_an_orphan_does_not_play(qtbot, lw):
    lw.list.setCurrentRow(4)
    lw.list.setFocus()
    press(qtbot, lw, Qt.Key.Key_Space)
    assert not any(c[0] == "play" for c in lw.player.calls)


def test_space_in_a_text_field_types_instead_of_playing(qtbot, lw):
    lw.list.setCurrentRow(1)
    lw.editor.note.setFocus()
    qtbot.keyClicks(lw.editor.note, "a b")
    assert not any(c[0] == "play" for c in lw.player.calls)
    assert lw.hub.store.get("packA/click.wav").note == "a b"


def test_escape_returns_focus_to_the_list(qtbot, lw):
    lw.list.setCurrentRow(1)
    lw.editor.tag_input.setFocus()
    qtbot.keyClicks(lw.editor.tag_input, "zz")
    qtbot.keyClick(lw.editor.tag_input, Qt.Key.Key_Escape)
    assert lw.editor.tag_input.text() == ""
    assert lw.list.hasFocus()


def test_play_requested_is_emitted_before_playing(qtbot, lw):
    lw.list.setCurrentRow(1)
    with qtbot.waitSignal(lw.play_requested):
        lw.list.itemDoubleClicked.emit(lw.list.item(1))


def test_someone_else_playing_clears_now_playing(lw):
    lw.list.setCurrentRow(1)
    lw.list.itemDoubleClicked.emit(lw.list.item(1))
    lw.player.play(lw.root / "packB" / "hit.mp3")  # as if the review window played
    assert lw.transport.now_playing.text() == "Nothing playing"


def test_stopped_state_from_the_player_clears_now_playing(lw):
    lw.list.setCurrentRow(1)
    lw.list.itemDoubleClicked.emit(lw.list.item(1))
    lw.player._set(PlayerState.STOPPED)
    assert lw.transport.now_playing.text() == "Nothing playing"


def test_transient_stop_during_source_change_keeps_now_playing(lw):
    """setSource emits STOPPED before PLAYING; that pair must not wipe our now-playing."""
    lw.list.setCurrentRow(1)
    lw.list.itemDoubleClicked.emit(lw.list.item(1))
    lw.player.state_changed.emit(PlayerState.STOPPED)
    lw.player.state_changed.emit(PlayerState.PLAYING)
    assert "click.wav" in lw.transport.now_playing.text()


def test_switching_files_keeps_playback_ownership(make_lw, root):
    """The transient stop inside the second play must not hand the borrowed player back."""
    w = make_lw(owns_hub=False, hub=AnnotationHub(LibraryAnnotations(root)))
    w.list.setCurrentRow(1)
    w.list.itemDoubleClicked.emit(w.list.item(1))
    w.list.setCurrentRow(3)
    w.list.itemDoubleClicked.emit(w.list.item(3))
    assert "hit.mp3" in w.transport.now_playing.text()
    assert w.close()
    assert w.player.calls[-1] == ("stop",)  # our audio must not outlive the window


# -- persistence and ownership ----------------------------------------------------------------


def test_owned_hub_autosaves_and_flushes_on_close(qtbot, lw, root):
    lw.list.setCurrentRow(2)
    lw.editor.stars[0].click()
    qtbot.waitUntil(lambda: LibraryAnnotations(root).get("packA/confirm.ogg").rating == 1, timeout=3000)
    lw.editor.note.setFocus()
    qtbot.keyClicks(lw.editor.note, "bye")
    assert lw.close()
    assert LibraryAnnotations(root).get("packA/confirm.ogg").note == "bye"
    assert lw.player.calls[-1] == ("stop",)
    assert lw.settings.value("library_window/geometry") is not None


def test_owned_hub_save_failure_reports_then_close_asks(qtbot, lw, root):
    lw.list.setCurrentRow(2)
    (root / SIDECAR_NAME).unlink()
    (root / SIDECAR_NAME).mkdir()
    lw.editor.stars[0].click()
    qtbot.waitUntil(lambda: any(c[0] == "error" for c in lw.dialogs.calls), timeout=3000)
    assert lw.hub.store.dirty
    lw.dialogs.unsaved_answer = "cancel"
    errors = sum(1 for c in lw.dialogs.calls if c[0] == "error")
    assert not lw.close()
    assert ("unsaved", "close", (SIDECAR_NAME,)) in lw.dialogs.calls
    # The unsaved-changes dialog names the file and offers a retry: closing must not stack a second modal.
    assert sum(1 for c in lw.dialogs.calls if c[0] == "error") == errors
    lw.dialogs.unsaved_answer = "discard"
    assert lw.close()


def test_unowned_hub_neither_reports_nor_stops_the_player(qtbot, make_lw, root):
    hub = AnnotationHub(LibraryAnnotations(root))
    w = make_lw(owns_hub=False, hub=hub)
    (root / SIDECAR_NAME).unlink()
    (root / SIDECAR_NAME).mkdir()
    w.list.setCurrentRow(2)
    with qtbot.waitSignal(hub.save_failed):
        w.editor.stars[0].click()
    assert not any(c[0] in ("error", "unsaved") for c in w.dialogs.calls)
    assert w.close()
    assert not any(c == ("stop",) for c in w.player.calls)


def test_unowned_hub_still_saves_on_ctrl_s(make_lw, root):
    """Saving is idempotent, so Ctrl+S must write whoever owns the hub (it was a silent no-op)."""
    w = make_lw(owns_hub=False, hub=AnnotationHub(LibraryAnnotations(root)))
    w.list.setCurrentRow(2)
    w.editor.stars[2].click()
    assert w.hub.store.dirty
    assert w.flush()
    assert not w.hub.store.dirty
    assert LibraryAnnotations(root).get("packA/confirm.ogg").rating == 3


def test_closing_while_playing_stops_a_borrowed_player(make_lw, root):
    w = make_lw(owns_hub=False, hub=AnnotationHub(LibraryAnnotations(root)))
    w.list.setCurrentRow(1)
    w.list.itemDoubleClicked.emit(w.list.item(1))
    assert w.close()
    assert ("stop",) in w.player.calls  # our audio must not outlive the window


def test_player_signals_after_the_viewer_is_deleted_do_not_raise(make_lw):
    """A shared player outlives this window, so every slot on it must be a bound method."""
    player = FakePlayer()
    w = make_lw(player=player)
    assert w.close()
    shiboken6.delete(w)
    del w  # the widget is gone; pytest-qt must not try to close it again at teardown
    # Lambda slots survive their receiver: these would reach a deleted C++ object and raise.
    player.source_changed.emit(Path("x.wav"))
    player.error.emit("boom")
    player.seekable_changed.emit(True)


def test_owned_hub_with_malformed_sidecar_reports_and_disables_editing(make_lw, root):
    (root / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    w = make_lw()
    assert sum(1 for c in w.dialogs.calls if c[0] == "error" and "version" in c[1]) == 1
    assert w.warning.isVisible() and "rescan" in w.warning.text().lower()
    w.list.setCurrentRow(1)
    assert not w.editor.note.isEnabled()
    (root / SIDECAR_NAME).write_text('{"version": 1, "tags": [], "files": {}}', encoding="utf-8")
    w.actions["rescan"].trigger()
    assert w.editor.note.isEnabled()
    assert not w.warning.isVisible()
