"""AnnotationEditor writes straight through to the store (spec section 4)."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from audio_picker.annotations import SIDECAR_NAME, LibraryAnnotations
from audio_picker.ui.annotation_editor import AnnotationEditor


@pytest.fixture
def store(tmp_path: Path) -> LibraryAnnotations:
    s = LibraryAnnotations(tmp_path)
    s.add_tag("packA/click.wav", "ui")
    s.add_tag("packB/hit.mp3", "hit")
    s.set_rating("packA/click.wav", 4)
    s.set_note("packA/click.wav", "Clean.")
    s.dirty = False
    return s


@pytest.fixture
def editor(qtbot, store):
    e = AnnotationEditor(store)
    qtbot.addWidget(e)
    e.resize(280, 400)
    e.show()
    qtbot.waitExposed(e)
    return e


def test_no_path_disables_everything(editor):
    editor.set_path(None)
    assert "No file" in editor.path_label.text()
    assert not editor.tag_input.isEnabled()
    assert not editor.note.isEnabled()
    assert not any(s.isEnabled() for s in editor.stars)


def test_set_path_loads_the_annotation(editor):
    editor.set_path("packA/click.wav")
    assert "packA" in editor.path_label.text() and "click.wav" in editor.path_label.text()
    assert editor.path_label.toolTip() == "packA/click.wav"
    assert [s.text() for s in editor.stars] == ["★", "★", "★", "★", "☆"]
    assert not editor.unrated.isVisible()
    assert editor.chip_tags() == ["ui"]
    assert editor.note.toPlainText() == "Clean."
    assert editor.tag_input.isEnabled()


def test_unannotated_path_shows_unrated_and_empty(editor):
    editor.set_path("packB/hit.mp3")
    assert [s.text() for s in editor.stars] == ["☆"] * 5
    assert editor.unrated.isVisible()
    assert editor.chip_tags() == ["hit"]
    assert editor.note.toPlainText() == ""


def test_star_click_sets_and_reclick_clears(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    with qtbot.waitSignal(editor.changed) as blocker:
        editor.stars[2].click()
    assert blocker.args == ["packB/hit.mp3"]
    assert store.get("packB/hit.mp3").rating == 3
    assert [s.text() for s in editor.stars] == ["★", "★", "★", "☆", "☆"]
    editor.stars[2].click()
    assert store.get("packB/hit.mp3").rating is None
    assert editor.unrated.isVisible()


def test_enter_commits_a_normalised_tag(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    editor.tag_input.setFocus()
    qtbot.keyClicks(editor.tag_input, " Metallic Hit ")
    with qtbot.waitSignal(editor.changed):
        qtbot.keyClick(editor.tag_input, Qt.Key.Key_Return)
    assert store.get("packB/hit.mp3").tags == ["hit", "metallic-hit"]
    assert editor.chip_tags() == ["hit", "metallic-hit"]
    assert editor.tag_input.text() == ""
    assert "metallic-hit" in editor.completer_words()


def test_comma_commits_a_tag_and_keeps_the_rest(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    qtbot.keyClicks(editor.tag_input, "loop,sea")
    assert store.get("packB/hit.mp3").tags == ["hit", "loop"]
    assert editor.tag_input.text() == "sea"


def test_duplicate_or_empty_tag_is_a_no_op(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    qtbot.keyClicks(editor.tag_input, "HIT")
    qtbot.keyClick(editor.tag_input, Qt.Key.Key_Return)
    qtbot.keyClick(editor.tag_input, Qt.Key.Key_Return)
    assert store.get("packB/hit.mp3").tags == ["hit"]
    assert not store.dirty
    assert editor.tag_input.text() == ""


def test_chip_remove_button_removes_the_tag(qtbot, editor, store):
    editor.set_path("packA/click.wav")
    with qtbot.waitSignal(editor.changed):
        editor.chips[0].remove.click()
    assert store.get("packA/click.wav").tags == []
    assert editor.chip_tags() == []


def test_note_writes_through_per_keystroke(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    editor.note.setFocus()
    qtbot.keyClicks(editor.note, "abc")
    assert store.get("packB/hit.mp3").note == "abc"
    assert editor.note.textCursor().position() == 3


def test_set_path_does_not_emit_changed_or_dirty(qtbot, editor, store):
    with qtbot.assertNotEmitted(editor.changed):
        editor.set_path("packA/click.wav")
        editor.set_path("packB/hit.mp3")
        editor.set_path(None)
    assert not store.dirty


def test_refresh_reflects_outside_changes_without_moving_the_cursor(qtbot, editor, store):
    editor.set_path("packA/click.wav")
    store.add_tag("packA/click.wav", "extra")
    store.set_rating("packA/click.wav", 1)
    editor.refresh()
    assert editor.chip_tags() == ["extra", "ui"]
    assert [s.text() for s in editor.stars] == ["★", "☆", "☆", "☆", "☆"]
    assert editor.note.toPlainText() == "Clean."


def test_escape_clears_the_tag_field_and_signals(qtbot, editor):
    editor.set_path("packA/click.wav")
    editor.tag_input.setFocus()
    qtbot.keyClicks(editor.tag_input, "half")
    with qtbot.waitSignal(editor.escape_pressed):
        qtbot.keyClick(editor.tag_input, Qt.Key.Key_Escape)
    assert editor.tag_input.text() == ""


def test_read_only_store_shows_but_disables_editing(qtbot, tmp_path):
    (tmp_path / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    broken = LibraryAnnotations(tmp_path)
    assert broken.read_only
    e = AnnotationEditor(broken)
    qtbot.addWidget(e)
    e.set_path("a.wav")
    assert "a.wav" in e.path_label.text()
    assert not e.tag_input.isEnabled()
    assert not e.note.isEnabled()
    assert not any(s.isEnabled() for s in e.stars)
    assert "read-only" in e.tag_input.placeholderText()


def test_completer_matches_anywhere_case_insensitively(editor):
    editor.set_path("packA/click.wav")
    editor.completer.setCompletionPrefix("I")
    words = [
        editor.completer.completionModel().index(i, 0).data()
        for i in range(editor.completer.completionModel().rowCount())
    ]
    assert words == ["hit", "ui"]
