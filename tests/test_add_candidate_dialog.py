"""Add Candidate dialog hosts the annotation editor (spec section 5.2)."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from audio_picker.annotations import LibraryAnnotations
from audio_picker.library import AudioLibrary
from audio_picker.model import load
from audio_picker.ui.annotation_hub import AUTOSAVE_MS, AnnotationHub
from audio_picker.ui.dialogs import AddCandidateDialog, Dialogs
from tests.test_ui_smoke import FakePlayer

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "review.json"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    dst = tmp_path / "audio"
    shutil.copytree(FIXTURE_ROOT, dst)
    return dst


@pytest.fixture
def dialog(qtbot, root):
    store = LibraryAnnotations(root)
    store.add_tag("packB/hit.mp3", "hit")
    d = AddCandidateDialog(load(EXAMPLE), AudioLibrary(root), root, FakePlayer(), AnnotationHub(store))
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    return d


def test_editor_follows_the_highlighted_result(dialog):
    assert dialog.editor.path is None
    dialog.results.setCurrentRow(3)  # packB/hit.mp3
    assert dialog.editor.path == "packB/hit.mp3"
    assert dialog.editor.chip_tags() == ["hit"]
    assert dialog.width() >= 900
    assert "even if you cancel" in dialog.notes_hint.text()


def test_hash_search_uses_the_store(dialog):
    dialog.search.setText("#hit")
    assert [dialog.results.item(i).text() for i in range(dialog.results.count())] == ["packB/hit.mp3"]


def test_edit_notifies_the_hub_and_autosaves_while_open(qtbot, dialog, root):
    dialog.results.setCurrentRow(1)  # packA/click.wav
    with qtbot.waitSignal(dialog.hub.changed) as blocker:
        dialog.editor.stars[1].click()
    assert blocker.args == ["packA/click.wav"]
    qtbot.waitUntil(lambda: LibraryAnnotations(root).get("packA/click.wav").rating == 2, timeout=3000)
    assert dialog.isVisible()


def test_enter_in_the_tag_field_adds_a_tag_and_does_not_accept_the_dialog(qtbot, dialog):
    dialog.results.setCurrentRow(1)
    dialog.editor.tag_input.setFocus()
    qtbot.keyClicks(dialog.editor.tag_input, "dry")
    qtbot.keyClick(dialog.editor.tag_input, Qt.Key.Key_Return)
    assert dialog.hub.store.has_tag("packA/click.wav", "dry")
    assert dialog.isVisible()
    assert dialog.result() != dialog.DialogCode.Accepted


def test_escape_in_the_tag_field_does_not_close_the_dialog(qtbot, dialog):
    dialog.results.setCurrentRow(1)
    dialog.editor.tag_input.setFocus()
    qtbot.keyClicks(dialog.editor.tag_input, "x")
    qtbot.keyClick(dialog.editor.tag_input, Qt.Key.Key_Escape)
    assert dialog.isVisible()
    assert dialog.editor.tag_input.text() == ""
    assert dialog.search.hasFocus()


def test_browse_clears_the_stale_result_highlight(monkeypatch, dialog, root):
    dialog.results.setCurrentRow(1)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(root / "packB" / "hit.mp3"), ""))
    )
    dialog._browse()
    assert dialog.editor.path == "packB/hit.mp3"
    assert dialog.results.currentItem() is None
    assert dialog.results.selectedItems() == []


def test_autosave_fires_inside_the_modal_loop(qtbot, root):
    hub = AnnotationHub(LibraryAnnotations(root))
    seen = {}

    def drive():
        d = next(w for w in QApplication.topLevelWidgets() if isinstance(w, AddCandidateDialog))
        d.results.setCurrentRow(1)
        d.editor.stars[2].click()
        QTimer.singleShot(
            AUTOSAVE_MS * 3,
            lambda: (seen.update(on_disk=LibraryAnnotations(root).get("packA/click.wav").rating), d.reject()),
        )

    QTimer.singleShot(50, drive)
    # Hang guard: if the drive above never runs, this reject keeps the modal loop from stalling the suite.
    QTimer.singleShot(
        5000, lambda: [w.reject() for w in QApplication.topLevelWidgets() if isinstance(w, AddCandidateDialog)]
    )
    assert Dialogs().add_candidate(None, load(EXAMPLE), AudioLibrary(root), root, FakePlayer(), hub) is None
    assert seen["on_disk"] == 3
