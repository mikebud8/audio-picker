"""AnnotationHub: change fan-out and the debounced sidecar save (spec section 3.5)."""

import json
from pathlib import Path

import pytest

from audio_picker.annotations import SIDECAR_NAME, LibraryAnnotations
from audio_picker.ui.annotation_hub import AnnotationHub


@pytest.fixture
def hub(qtbot, tmp_path: Path) -> AnnotationHub:
    return AnnotationHub(LibraryAnnotations(tmp_path))


def test_notify_changed_emits_and_autosaves(qtbot, hub, tmp_path):
    hub.store.set_rating("a.wav", 3)
    with qtbot.waitSignal(hub.changed) as blocker:
        hub.notify_changed("a.wav")
    assert blocker.args == ["a.wav"]
    qtbot.waitUntil(lambda: (tmp_path / SIDECAR_NAME).exists(), timeout=3000)
    assert not hub.store.dirty


def test_flush_saves_now_and_reports_true(hub, tmp_path):
    hub.store.set_note("a.wav", "x")
    hub.notify_changed("a.wav")
    assert hub.flush()
    assert LibraryAnnotations(tmp_path).get("a.wav").note == "x"
    assert hub.flush(), "nothing pending counts as success"


def test_failed_save_emits_save_failed_and_keeps_dirty(qtbot, hub, tmp_path):
    (tmp_path / SIDECAR_NAME).mkdir()
    hub.store.set_rating("a.wav", 1)
    with qtbot.waitSignal(hub.save_failed) as blocker:
        assert not hub.flush()
    assert "library notes" in blocker.args[0].lower()
    assert hub.store.dirty


def test_reload_refuses_a_dirty_store_but_still_emits(qtbot, hub):
    hub.store.set_rating("a.wav", 1)
    with qtbot.waitSignal(hub.reloaded):
        text = hub.reload()
    assert "not reloaded" in text
    assert hub.store.get("a.wav").rating == 1


def test_reload_reads_the_disk_when_clean(qtbot, hub, tmp_path):
    good = {"version": 1, "tags": [], "files": {"b.wav": {"rating": 2}}}
    (tmp_path / SIDECAR_NAME).write_text(json.dumps(good), encoding="utf-8")
    with qtbot.waitSignal(hub.reloaded):
        text = hub.reload()
    assert text == "library notes reloaded"
    assert hub.store.get("b.wav").rating == 2


def test_reload_reports_a_still_broken_file(hub, tmp_path):
    (tmp_path / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    assert hub.reload() == "library notes not loaded"
    assert hub.store.read_only


def test_set_store_stops_the_timer_and_emits(qtbot, hub, tmp_path):
    hub.store.set_rating("a.wav", 1)
    hub.notify_changed("a.wav")
    other = LibraryAnnotations(tmp_path / "other")
    with qtbot.waitSignal(hub.reloaded):
        hub.set_store(other)
    assert not hub._timer.isActive()
    assert hub.store is other
    assert not (tmp_path / SIDECAR_NAME).exists(), "the old store was dropped, not saved"


def test_flush_on_a_read_only_store_returns_true(hub, tmp_path):
    (tmp_path / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    hub.reload()
    assert hub.store.read_only
    assert hub.flush() is True
