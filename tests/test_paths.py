"""Root resolution and relative/absolute path conversion (design section 6)."""

import os
from pathlib import Path

import pytest

from audio_picker.model import ReviewError
from audio_picker.paths import resolve_root, to_absolute, to_relative


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    lib = tmp_path / "vendor" / "audio"
    (lib / "packA").mkdir(parents=True)
    (lib / "packA" / "click.wav").write_bytes(b"")
    (tmp_path / "docs").mkdir()
    review = tmp_path / "docs" / "review.json"
    review.write_text("{}", encoding="utf-8")
    other = tmp_path / "elsewhere"
    other.mkdir()
    return {"lib": lib, "review": review, "other": other, "tmp": tmp_path}


# -- resolve_root ------------------------------------------------------------


def test_cli_root_wins(tree):
    assert resolve_root(tree["review"], "../vendor/audio", tree["other"]) == tree["other"]


def test_relative_review_root_resolves_against_review_file_directory(tree):
    assert resolve_root(tree["review"], "../vendor/audio", None) == tree["lib"]


def test_absolute_review_root(tree):
    assert resolve_root(tree["review"], str(tree["lib"]), None) == tree["lib"]


def test_missing_root_is_an_error(tree):
    with pytest.raises(ReviewError) as info:
        resolve_root(tree["review"], "../nope", None)
    assert "nope" in str(info.value)


def test_root_that_is_a_file_is_an_error(tree):
    with pytest.raises(ReviewError):
        resolve_root(tree["review"], None, tree["lib"] / "packA" / "click.wav")


# -- to_relative / to_absolute ----------------------------------------------


def test_to_relative_uses_forward_slashes(tree):
    assert to_relative(tree["lib"], tree["lib"] / "packA" / "click.wav") == "packA/click.wav"


def test_to_relative_accepts_backslash_string_input(tree):
    raw = str(tree["lib"]) + "\\packA\\click.wav"
    assert to_relative(tree["lib"], raw) == "packA/click.wav"


def test_to_relative_outside_root_is_none(tree):
    assert to_relative(tree["lib"], tree["other"] / "x.wav") is None


def test_to_relative_rejects_escape_via_dotdot(tree):
    escaped = tree["lib"] / "packA" / ".." / ".." / "x.wav"
    assert to_relative(tree["lib"], escaped) is None


def test_to_relative_normalises_dotdot_inside_root(tree):
    inside = tree["lib"] / "packA" / ".." / "packA" / "click.wav"
    assert to_relative(tree["lib"], inside) == "packA/click.wav"


def test_to_relative_does_not_match_sibling_with_same_prefix(tree):
    sibling = tree["tmp"] / "vendor" / "audio2" / "x.wav"
    assert to_relative(tree["lib"], sibling) is None


def test_to_relative_of_root_itself_is_empty(tree):
    assert to_relative(tree["lib"], tree["lib"]) == ""


@pytest.mark.skipif(os.path.normcase("A") == "A", reason="case-sensitive filesystem")
def test_to_relative_ignores_case_differences_on_windows(tree):
    swapped = str(tree["lib"]).swapcase() + "/packA/click.wav"
    assert to_relative(tree["lib"], swapped) == "packA/click.wav"


def test_to_absolute_joins_forward_slash_path(tree):
    assert to_absolute(tree["lib"], "packA/click.wav") == tree["lib"] / "packA" / "click.wav"


def test_to_absolute_then_to_relative_round_trip(tree):
    rel = "packA/click.wav"
    assert to_relative(tree["lib"], to_absolute(tree["lib"], rel)) == rel
