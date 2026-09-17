"""Model layer: dataclasses, load/save, validation, status and selection rules."""

import json
from pathlib import Path

import pytest

from audio_picker.model import (
    Candidate,
    Review,
    ReviewError,
    Slot,
    from_dict,
    load,
    next_candidate_id_for,
    save,
    to_dict,
)

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "review.json"


@pytest.fixture
def review() -> Review:
    return load(EXAMPLE)


# -- load / save -------------------------------------------------------------


def test_load_example_populates_dataclasses(review):
    assert review.version == 1
    assert review.project == "example"
    assert review.categories == ["UI", "Battle", "Unfilled"]
    assert set(review.packs) == {"pack_a", "pack_b"}
    assert review.packs["pack_a"].folder == "packA"
    assert [s.id for s in review.slots] == [
        "ui_click",
        "ui_confirm",
        "battle_hit",
        "battle_miss",
        "horn_distant",
    ]
    first = review.slots[0]
    assert first.selected == "A001"
    assert first.candidates[1].decision == "unreviewed"
    assert review.slots[3].candidates[0].pack is None


def test_save_round_trip_is_byte_identical(review, tmp_path):
    out = tmp_path / "review.json"
    save(review, out)
    assert out.read_bytes() == EXAMPLE.read_bytes()


def test_save_is_canonical_regardless_of_input_key_order(tmp_path):
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    shuffled = dict(reversed(list(data.items())))
    out = tmp_path / "review.json"
    save(from_dict(shuffled), out)
    assert out.read_bytes() == EXAMPLE.read_bytes()


def test_save_is_atomic_leaves_no_tmp_file(review, tmp_path):
    out = tmp_path / "review.json"
    save(review, out)
    assert list(tmp_path.iterdir()) == [out]


def test_to_dict_from_dict_round_trip(review):
    assert from_dict(to_dict(review)) == review


def test_load_missing_file_raises_review_error(tmp_path):
    with pytest.raises(ReviewError):
        load(tmp_path / "nope.json")


def test_load_invalid_json_raises_review_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ReviewError):
        load(p)


# -- derived status ----------------------------------------------------------


def test_status_covers_all_four_values(review):
    by_id = {s.id: s.status() for s in review.slots}
    assert by_id == {
        "ui_click": "selected",
        "ui_confirm": "unselected",
        "battle_hit": "rejected",
        "battle_miss": "unselected",
        "horn_distant": "gap",
    }


def test_status_gap_beats_selected_and_rejected():
    slot = Slot("s", "c", "f", "later", "", None, [])
    assert slot.status() == "gap"


# -- 5.8 selection and rejection rules --------------------------------------


def test_nay_on_selected_candidate_clears_selection(review):
    slot = review.slot("ui_click")
    slot.set_decision("A001", "nay")
    assert slot.selected is None
    assert slot.candidate("A001").decision == "nay"


def test_nay_on_other_candidate_keeps_selection(review):
    slot = review.slot("ui_click")
    slot.set_decision("A002", "nay")
    assert slot.selected == "A001"


def test_select_refuses_nay_candidate(review):
    slot = review.slot("battle_hit")
    with pytest.raises(ValueError):
        slot.select("A004")
    assert slot.selected is None


def test_select_promotes_unreviewed_to_yay(review):
    slot = review.slot("ui_click")
    slot.select("A002")
    assert slot.selected == "A002"
    assert slot.candidate("A002").decision == "yay"
    assert slot.candidate("A001").decision == "yay", "other decisions untouched"


def test_select_leaves_yay_alone(review):
    slot = review.slot("ui_click")
    slot.select("A001")
    assert slot.candidate("A001").decision == "yay"
    assert slot.selected == "A001"


def test_set_decision_rejects_unknown_values(review):
    with pytest.raises(ValueError):
        review.slot("ui_click").set_decision("A001", "maybe")


def test_unknown_candidate_raises_key_error(review):
    slot = review.slot("ui_click")
    with pytest.raises(KeyError):
        slot.set_decision("Z999", "yay")
    with pytest.raises(KeyError):
        slot.select("Z999")
    assert slot.candidate("Z999") is None


# -- lookups and id allocation ----------------------------------------------


def test_slot_lookup(review):
    assert review.slot("battle_hit").function == "Melee strike connects"
    assert review.slot("nope") is None


def test_all_candidate_ids(review):
    assert review.all_candidate_ids() == {"A001", "A002", "A003", "A004", "A005", "A006"}


def test_next_candidate_id_is_max_plus_one_zero_padded(review):
    assert review.next_candidate_id() == "A007"


def test_next_candidate_id_skips_gaps_in_numbering():
    assert next_candidate_id_for({"A001", "A005", "A009"}) == "A010"


def test_next_candidate_id_handles_mixed_widths():
    assert next_candidate_id_for({"A5", "A0100", "A12"}) == "A101"
    assert next_candidate_id_for({"A999"}) == "A1000"


def test_next_candidate_id_respects_prefix():
    assert next_candidate_id_for({"A007", "B002"}, prefix="B") == "B003"
    assert next_candidate_id_for({"A007"}, prefix="B") == "B001"
    assert next_candidate_id_for(set()) == "A001"


def test_candidate_dataclass_equality():
    a = Candidate("A1", "p/x.wav", None, "first", "", "", "", "unreviewed", "")
    b = Candidate("A1", "p/x.wav", None, "first", "", "", "", "unreviewed", "")
    assert a == b
