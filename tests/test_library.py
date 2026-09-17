"""Audio library index (design section 11)."""

from pathlib import Path

import pytest

from audio_picker.annotations import LibraryAnnotations
from audio_picker.library import AudioLibrary

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for rel in [
        "packA/click.wav",
        "packA/sub/deep.OGG",
        "packB/hit.mp3",
        "packB/notes.txt",
        "packB/cover.png",
        "loose.flac",
        ".hidden/secret.wav",
        "packA/.DS_Store",
        "packA/._click.wav",
        "__MACOSX/packA/._click.wav",
    ]:
        _touch(tmp_path, rel)
    return tmp_path


def test_index_is_sorted_relative_forward_slash_audio_only(root):
    lib = AudioLibrary(root)
    assert lib.paths == [
        "loose.flac",
        "packA/click.wav",
        "packA/sub/deep.OGG",
        "packB/hit.mp3",
    ]
    assert len(lib) == 4


def test_hidden_directories_and_dot_files_are_skipped(root):
    paths = AudioLibrary(root).paths
    assert not any(".hidden" in p or "._" in p or "__MACOSX" in p for p in paths)


def test_search_every_term_must_match_case_insensitively(root):
    lib = AudioLibrary(root)
    assert lib.search("PACKA") == ["packA/click.wav", "packA/sub/deep.OGG"]
    assert lib.search("packa deep") == ["packA/sub/deep.OGG"]
    assert lib.search("packa hit") == []


def test_search_empty_query_returns_everything(root):
    lib = AudioLibrary(root)
    assert lib.search("") == lib.paths
    assert lib.search("   ") == lib.paths


def test_search_is_capped(root):
    lib = AudioLibrary(root)
    assert lib.search("", limit=2) == ["loose.flac", "packA/click.wav"]
    assert lib.search("", limit=0) == []
    store = LibraryAnnotations(root)
    store.add_tag("packA/click.wav", "ui")
    store.add_tag("packB/hit.mp3", "ui")
    assert lib.search("#ui", limit=1, annotations=store) == ["packA/click.wav"]


def test_pack_folder_is_first_component():
    assert AudioLibrary.pack_folder("packA/sub/deep.ogg") == "packA"
    assert AudioLibrary.pack_folder("loose.flac") == ""


def test_refresh_picks_up_new_files(root):
    lib = AudioLibrary(root)
    _touch(root, "packC/new.wav")
    assert "packC/new.wav" not in lib.paths
    lib.refresh()
    assert "packC/new.wav" in lib.paths


def test_missing_root_is_an_empty_library(tmp_path):
    lib = AudioLibrary(tmp_path / "nope")
    assert lib.paths == []


def test_fixture_library_matches_example_review():
    lib = AudioLibrary(FIXTURE_ROOT)
    assert lib.paths == [
        "loose/miss.wav",
        "packA/click.wav",
        "packA/confirm.ogg",
        "packB/hit.mp3",
    ]


# -- tag terms -----------------------------------------------------------------------


def test_hash_terms_match_tags_from_the_store(root):
    lib = AudioLibrary(root)
    store = LibraryAnnotations(root)
    store.add_tag("packA/click.wav", "ui")
    store.add_tag("packB/hit.mp3", "ui")
    store.add_tag("packB/hit.mp3", "hit")
    assert lib.search("#ui", annotations=store) == ["packA/click.wav", "packB/hit.mp3"]
    assert lib.search("#UI packb", annotations=store) == ["packB/hit.mp3"]
    assert lib.search("#ui #hit", annotations=store) == ["packB/hit.mp3"]
    assert lib.search("#nope", annotations=store) == []
    assert lib.search("#", annotations=store) == lib.paths, "a bare # is ignored"


def test_hash_terms_match_nothing_without_a_store(root):
    lib = AudioLibrary(root)
    assert lib.search("#ui") == []
    assert lib.search("packa") == ["packA/click.wav", "packA/sub/deep.OGG"]
