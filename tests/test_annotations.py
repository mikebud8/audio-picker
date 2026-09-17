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
        ({"version": 1, "tags": [], "files": {" a.wav": {}}}, "canonical"),
        ({"version": 1, "tags": [], "files": {"packA/": {}}}, "canonical"),
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
    assert "UTF-8" in LibraryAnnotations(tmp_path).load_error


def test_reload_recovers_after_the_file_is_fixed(tmp_path):
    write_sidecar(tmp_path, {"version": 9})
    store = LibraryAnnotations(tmp_path)
    assert store.read_only
    shutil.copy(FIXTURE, tmp_path / SIDECAR_NAME)
    store.reload()
    assert not store.read_only
    assert store.load_error is None
    assert store.annotated() == ["packA/click.wav", "packZ/gone.wav"]
