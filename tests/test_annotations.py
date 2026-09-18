"""Library annotations store (library annotations spec, section 3). No Qt."""

import json
import shutil
from pathlib import Path

import pytest

from audio_picker.annotations import (
    SIDECAR_NAME,
    Annotation,
    AnnotationsError,
    LibraryAnnotations,
    normalise_tag,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "library-annotations.json"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A root with the fixture sidecar in place."""
    shutil.copy(FIXTURE, tmp_path / SIDECAR_NAME)
    return tmp_path


def write_sidecar(root: Path, data) -> Path:
    p = root / SIDECAR_NAME
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# -- normalise_tag ---------------------------------------------------------------


def test_normalise_tag_lowercases_strips_and_joins_whitespace():
    assert normalise_tag("  UI Click ") == "ui-click"
    assert normalise_tag("Loop\tSeam\nOK") == "loop-seam-ok"
    assert normalise_tag("metallic") == "metallic"


def test_normalise_tag_rejects_empty():
    with pytest.raises(ValueError):
        normalise_tag("   ")


# -- loading ---------------------------------------------------------------------


def test_missing_file_is_an_empty_store(tmp_path):
    store = LibraryAnnotations(tmp_path)
    assert store.path == tmp_path / SIDECAR_NAME
    assert store.annotated() == []
    assert store.vocabulary() == []
    assert store.get("anything.wav") == Annotation()
    assert not store.dirty
    assert not store.read_only
    assert store.load_error is None


def test_fixture_loads(root):
    store = LibraryAnnotations(root)
    assert store.annotated() == ["packA/click.wav", "packZ/gone.wav"]
    assert store.get("packA/click.wav") == Annotation(rating=4, tags=["click", "ui"], note="Clean and short.")
    assert store.get("packZ/gone.wav") == Annotation(rating=None, tags=["orphan"], note="")
    assert store.vocabulary() == ["click", "orphan", "ui"]
    assert store.has("packA/click.wav")
    assert not store.has("nope.wav")
    assert store.has_tag("packA/click.wav", "ui")
    assert not store.has_tag("packA/click.wav", "hit")


def test_get_returns_a_copy(root):
    store = LibraryAnnotations(root)
    store.get("packA/click.wav").tags.append("mutated")
    assert store.get("packA/click.wav").tags == ["click", "ui"]


def test_vocabulary_is_union_of_listed_and_used_tags(tmp_path):
    write_sidecar(tmp_path, {"version": 1, "tags": ["spare"], "files": {"a.wav": {"tags": ["used"]}}})
    assert LibraryAnnotations(tmp_path).vocabulary() == ["spare", "used"]


@pytest.mark.parametrize(
    "data, fragment",
    [
        ("not json", "invalid JSON"),
        ([], "expected an object"),
        ({"version": 2, "tags": [], "files": {}}, "version"),
        ({"tags": [], "files": {}}, "version"),
        ({"version": 1, "tags": [], "files": {}, "extra": 1}, "unknown key"),
        ({"version": 1, "tags": "x", "files": {}}, "tags must be a list"),
        ({"version": 1, "tags": ["Bad Tag"], "files": {}}, "not normalised"),
        ({"version": 1, "tags": [], "files": []}, "files must be an object"),
        ({"version": 1, "tags": [], "files": {"/abs.wav": {}}}, "absolute"),
        ({"version": 1, "tags": [], "files": {"a/../b.wav": {}}}, "'..'"),
        ({"version": 1, "tags": [], "files": {"a.wav": []}}, "expected an object"),
        ({"version": 1, "tags": [], "files": {"a.wav": {"bogus": 1}}}, "unknown key"),
        ({"version": 1, "tags": [], "files": {"a.wav": {"rating": 0}}}, "rating"),
        ({"version": 1, "tags": [], "files": {"a.wav": {"rating": 6}}}, "rating"),
        ({"version": 1, "tags": [], "files": {"a.wav": {"rating": True}}}, "rating"),
        ({"version": 1, "tags": [], "files": {"a.wav": {"rating": "4"}}}, "rating"),
        ({"version": 1, "tags": [], "files": {"a.wav": {"tags": "ui"}}}, "tags must be a list"),
        ({"version": 1, "tags": [], "files": {"a.wav": {"tags": ["UI"]}}}, "not normalised"),
        ({"version": 1, "tags": [], "files": {"a.wav": {"note": 3}}}, "note must be a string"),
        ({"version": 1, "tags": [], "files": {"a\\b.wav": {}}}, "canonical"),
        ({"version": 1, "tags": [], "files": {"packA//x.wav": {}}}, "canonical"),
        ({"version": 1, "tags": [], "files": {"packA/": {}}}, "canonical"),
        ({"version": 1, "tags": [""], "files": {}}, "empty"),
        ({"version": 1, "tags": [], "files": {"a.wav": {"tags": ["  "]}}}, "empty"),
    ],
)
def test_malformed_sidecar_is_reported_and_store_is_read_only(tmp_path, data, fragment):
    p = tmp_path / SIDECAR_NAME
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    store = LibraryAnnotations(tmp_path)
    assert store.load_error is not None and fragment in store.load_error
    assert store.read_only
    assert store.annotated() == []
    with pytest.raises(AnnotationsError):
        store.reload()


def test_not_utf8_is_reported(tmp_path):
    (tmp_path / SIDECAR_NAME).write_bytes(b"\xff\xfe{}")
    error = LibraryAnnotations(tmp_path).load_error
    assert error is not None and "UTF-8" in error


def test_load_tolerates_null_rating_duplicate_tags_and_empty_entries(tmp_path):
    write_sidecar(
        tmp_path,
        {"version": 1, "tags": [], "files": {"a.wav": {"rating": None, "tags": ["ui", "ui"]}, "b.wav": {}}},
    )
    store = LibraryAnnotations(tmp_path)
    assert store.get("a.wav") == Annotation(rating=None, tags=["ui"], note="")
    assert store.annotated() == ["a.wav"]
    assert store.vocabulary() == ["ui"]


def test_reload_recovers_after_the_file_is_fixed(tmp_path):
    write_sidecar(tmp_path, {"version": 9})
    store = LibraryAnnotations(tmp_path)
    assert store.read_only
    shutil.copy(FIXTURE, tmp_path / SIDECAR_NAME)
    store.reload()
    assert not store.read_only
    assert store.load_error is None
    assert store.annotated() == ["packA/click.wav", "packZ/gone.wav"]


# -- mutators ------------------------------------------------------------------------


def test_set_rating_marks_dirty_and_validates(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.set_rating("a.wav", 3)
    assert store.dirty
    assert store.get("a.wav").rating == 3
    store.set_rating("a.wav", None)
    assert store.get("a.wav").rating is None
    for bad in (0, 6, True, "4", 4.0):
        with pytest.raises(ValueError):
            store.set_rating("a.wav", bad)


def test_add_tag_normalises_sorts_and_grows_vocabulary(tmp_path):
    store = LibraryAnnotations(tmp_path)
    assert store.add_tag("a.wav", " UI ") == "ui"
    assert store.add_tag("a.wav", "Click") == "click"
    assert store.get("a.wav").tags == ["click", "ui"]
    assert store.vocabulary() == ["click", "ui"]
    assert store.dirty


def test_add_duplicate_tag_is_a_no_op(root):
    store = LibraryAnnotations(root)
    assert store.add_tag("packA/click.wav", "ui") == "ui"
    assert store.get("packA/click.wav").tags == ["click", "ui"]
    assert not store.dirty


def test_add_empty_tag_raises(tmp_path):
    store = LibraryAnnotations(tmp_path)
    with pytest.raises(ValueError):
        store.add_tag("a.wav", "  ")
    assert not store.dirty


def test_remove_tag_keeps_the_vocabulary(root):
    store = LibraryAnnotations(root)
    store.remove_tag("packZ/gone.wav", "orphan")
    assert not store.has("packZ/gone.wav"), "an entry with nothing left is dropped"
    assert "orphan" in store.vocabulary()
    assert store.dirty


def test_remove_unknown_tag_is_a_no_op(root):
    store = LibraryAnnotations(root)
    store.remove_tag("packA/click.wav", "nope")
    store.remove_tag("nope.wav", "ui")
    assert not store.dirty


def test_set_note_and_clearing_everything_drops_the_entry(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.set_note("a.wav", "hello")
    assert store.get("a.wav").note == "hello"
    assert store.annotated() == ["a.wav"]
    store.set_note("a.wav", "")
    assert store.annotated() == []


def test_set_note_to_same_text_is_a_no_op(root):
    store = LibraryAnnotations(root)
    store.set_note("packA/click.wav", "Clean and short.")
    store.set_note("other.wav", "")
    assert not store.dirty


def test_set_note_rejects_non_strings(tmp_path):
    store = LibraryAnnotations(tmp_path)
    with pytest.raises(ValueError):
        store.set_note("a.wav", 3)
    assert not store.dirty


def test_clearing_a_rating_on_an_unknown_path_is_a_no_op(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.set_rating("nope.wav", None)
    assert not store.dirty
    assert store.annotated() == []


# -- filters ---------------------------------------------------------------------------


def test_files_with_and_min_rating(root):
    store = LibraryAnnotations(root)
    store.set_rating("packB/hit.mp3", 2)
    store.add_tag("packB/hit.mp3", "ui")
    assert store.files_with("UI") == ["packA/click.wav", "packB/hit.mp3"]
    assert store.files_with("orphan") == ["packZ/gone.wav"]
    assert store.files_with("nope") == []
    assert store.min_rating(1) == ["packA/click.wav", "packB/hit.mp3"]
    assert store.min_rating(3) == ["packA/click.wav"]
    assert store.min_rating(5) == []


# -- saving --------------------------------------------------------------------------


def test_round_trip_is_byte_identical(root):
    store = LibraryAnnotations(root)
    store.dirty = True  # save is unconditional; this proves it clears the flag
    store.save()
    assert (root / SIDECAR_NAME).read_bytes() == FIXTURE.read_bytes()
    assert not store.dirty
    assert not (root / (SIDECAR_NAME + ".tmp")).exists()


def test_save_writes_sorted_keys_lf_and_omits_empty_fields(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.add_tag("z.wav", "b")
    store.set_rating("a.wav", 5)
    store.set_note("m.wav", "line1\nline2")
    store.save()
    raw = (tmp_path / SIDECAR_NAME).read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"}\n")
    data = json.loads(raw)
    assert list(data) == ["version", "tags", "files"]
    assert list(data["files"]) == ["a.wav", "m.wav", "z.wav"]
    assert data["files"]["a.wav"] == {"rating": 5}
    assert data["files"]["m.wav"] == {"note": "line1\nline2"}
    assert data["files"]["z.wav"] == {"tags": ["b"]}
    assert data["tags"] == ["b"]


def test_save_is_a_no_op_when_read_only(tmp_path):
    p = write_sidecar(tmp_path, {"version": 9})
    store = LibraryAnnotations(tmp_path)
    with pytest.raises(AnnotationsError):
        store.set_rating("a.wav", 1)
    store.save()
    assert json.loads(p.read_text(encoding="utf-8")) == {"version": 9}
    assert not store.dirty


def test_save_failure_raises_oserror_and_keeps_dirty(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.set_rating("a.wav", 1)
    (tmp_path / SIDECAR_NAME).mkdir()  # a directory in the way
    with pytest.raises(OSError):
        store.save()
    assert store.dirty
    assert not (tmp_path / (SIDECAR_NAME + ".tmp")).exists()


def test_reload_picks_up_a_disk_change(tmp_path):
    store = LibraryAnnotations(tmp_path)
    write_sidecar(tmp_path, {"version": 1, "tags": [], "files": {"n.wav": {"rating": 2}}})
    assert not store.has("n.wav")
    store.reload()
    assert store.get("n.wav").rating == 2


def test_empty_store_saves_and_reloads_clean(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.set_rating("a.wav", 1)
    store.set_rating("a.wav", None)
    store.save()
    again = LibraryAnnotations(tmp_path)
    assert again.annotated() == []
    assert again.vocabulary() == []
    assert not again.read_only


def test_backslash_keys_are_normalised_on_write_and_read(tmp_path):
    """A hand-edited review can carry a backslash path; the store must never key on one."""
    store = LibraryAnnotations(tmp_path)
    store.add_tag("packA\\click.wav", "ui")
    store.set_rating("packA\\click.wav", 3)
    assert store.get("packA/click.wav").tags == ["ui"]
    assert store.has_tag("packA\\click.wav", "ui")
    store.save()
    again = LibraryAnnotations(tmp_path)
    assert not again.read_only
    assert again.get("packA/click.wav").rating == 3
    assert again.annotated() == ["packA/click.wav"]
