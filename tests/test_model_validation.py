"""One failing fixture per load-time rule in design section 5.6."""

import copy
import json
from pathlib import Path

import pytest

from audio_picker.model import ReviewError, from_dict

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "review.json"


@pytest.fixture
def data() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _rejects(data: dict, needle: str) -> None:
    with pytest.raises(ReviewError) as info:
        from_dict(copy.deepcopy(data))
    assert needle in str(info.value), str(info.value)


def test_example_is_valid(data):
    from_dict(data)


def test_wrong_version(data):
    data["version"] = 2
    _rejects(data, "version")


def test_missing_required_key_names_it(data):
    del data["slots"][0]["candidates"][0]["why"]
    _rejects(data, "why")


def test_missing_top_level_key(data):
    del data["packs"]
    _rejects(data, "packs")


def test_unknown_extra_key_is_an_error(data):
    data["slots"][1]["colour"] = "blue"
    _rejects(data, "colour")


def test_wrong_type(data):
    data["slots"][0]["notes"] = 5
    _rejects(data, "notes")


def test_bool_is_not_an_int(data):
    data["version"] = True
    _rejects(data, "version")


def test_categories_must_be_strings(data):
    data["categories"] = ["UI", 3]
    _rejects(data, "categories")


def test_priority_outside_enum(data):
    data["slots"][0]["priority"] = "urgent"
    _rejects(data, "urgent")


def test_role_outside_enum(data):
    data["slots"][0]["candidates"][0]["role"] = "primary"
    _rejects(data, "primary")


def test_decision_outside_enum(data):
    data["slots"][0]["candidates"][0]["decision"] = "maybe"
    _rejects(data, "maybe")


def test_duplicate_slot_id(data):
    data["slots"][1]["id"] = "ui_click"
    _rejects(data, "duplicate slot id")


def test_duplicate_candidate_id_across_slots(data):
    data["slots"][1]["candidates"][0]["id"] = "A001"
    _rejects(data, "duplicate candidate id")


def test_selected_not_in_own_candidates(data):
    data["slots"][0]["selected"] = "A003"  # exists, but in another slot
    _rejects(data, "A003")


def test_selected_candidate_marked_nay(data):
    data["slots"][0]["candidates"][0]["decision"] = "nay"
    _rejects(data, "nay")


def test_candidate_pack_not_in_packs(data):
    data["slots"][0]["candidates"][0]["pack"] = "pack_z"
    _rejects(data, "pack_z")


def test_duplicate_pack_folder(data):
    data["packs"]["pack_b"]["folder"] = "packA"
    _rejects(data, "folder")


def test_slot_id_pattern(data):
    data["slots"][0]["id"] = "UI-Click"
    _rejects(data, "UI-Click")


def test_pack_id_pattern(data):
    data["packs"]["Pack A"] = data["packs"].pop("pack_a")
    for s in data["slots"]:
        for c in s["candidates"]:
            if c["pack"] == "pack_a":
                c["pack"] = "Pack A"
    _rejects(data, "Pack A")


def test_candidate_id_pattern(data):
    data["slots"][0]["candidates"][0]["id"] = "a001"
    data["slots"][0]["selected"] = "a001"
    _rejects(data, "a001")


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/packA/click.wav",
        "\\packA\\click.wav",
        "C:/lib/click.wav",
        "packA/../click.wav",
        "./packA/click.wav",
        "packA/./click.wav",
    ],
)
def test_candidate_path_rules(data, path):
    data["slots"][0]["candidates"][0]["path"] = path
    _rejects(data, "path")


def test_error_names_slot_and_candidate(data):
    data["slots"][2]["candidates"][1]["role"] = "bogus"
    with pytest.raises(ReviewError) as info:
        from_dict(data)
    assert "battle_hit" in str(info.value)
    assert "A005" in str(info.value)


def test_top_level_not_an_object():
    with pytest.raises(ReviewError):
        from_dict([])
