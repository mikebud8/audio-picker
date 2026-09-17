"""Export manifest (design section 9)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from audio_picker.export import build_manifest, first_pass_unselected
from audio_picker.model import load

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "review.json"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"
NOW = datetime(2026, 9, 17, 18, 4, 11, tzinfo=timezone.utc)


@pytest.fixture
def review():
    return load(EXAMPLE)


def test_header_fields(review):
    m = build_manifest(review, FIXTURE_ROOT, NOW)
    assert m["manifest_version"] == 1
    assert m["project"] == "example"
    assert m["generated"] == "2026-09-17T18:04:11Z"
    assert m["root"] == str(FIXTURE_ROOT).replace("\\", "/")
    assert "\\" not in m["root"]
    assert list(m) == ["manifest_version", "project", "generated", "root", "selections", "unselected", "gaps"]


def test_generated_converts_aware_and_assumes_utc_for_naive(review):
    plus_two = datetime(2026, 9, 17, 20, 4, 11, tzinfo=timezone(timedelta(hours=2)))
    assert build_manifest(review, FIXTURE_ROOT, plus_two)["generated"] == "2026-09-17T18:04:11Z"
    naive = datetime(2026, 9, 17, 18, 4, 11)
    assert build_manifest(review, FIXTURE_ROOT, naive)["generated"] == "2026-09-17T18:04:11Z"


def test_selection_entry(review):
    m = build_manifest(review, FIXTURE_ROOT, NOW)
    assert len(m["selections"]) == 1
    sel = m["selections"][0]
    assert sel == {
        "slot": "ui_click",
        "category": "UI",
        "priority": "first_pass",
        "candidate": "A001",
        "path": "packA/click.wav",
        "absolute_path": str(FIXTURE_ROOT).replace("\\", "/") + "/packA/click.wav",
        "exists": True,
        "pack_id": "pack_a",
        "pack": "Pack A",
        "license": "CC0; see packA/LICENSE.txt",
        "proposed_use": "Every button.",
    }


def test_selection_without_pack_has_null_provenance(review):
    review.slot("battle_miss").select("A006")
    m = build_manifest(review, FIXTURE_ROOT, NOW)
    sel = next(s for s in m["selections"] if s["slot"] == "battle_miss")
    assert (sel["pack_id"], sel["pack"], sel["license"]) == (None, None, None)


def test_selections_follow_slot_file_order(review):
    review.slot("battle_miss").select("A006")
    review.slot("ui_confirm").select("A003")
    m = build_manifest(review, FIXTURE_ROOT, NOW)
    assert [s["slot"] for s in m["selections"]] == ["ui_click", "ui_confirm", "battle_miss"]


def test_exists_false_when_file_missing(review, tmp_path):
    m = build_manifest(review, tmp_path, NOW)
    assert m["selections"][0]["exists"] is False


def test_unselected_includes_unselected_and_rejected_with_status(review):
    m = build_manifest(review, FIXTURE_ROOT, NOW)
    assert m["unselected"] == [
        {"slot": "ui_confirm", "priority": "first_pass", "status": "unselected", "candidates": 1},
        {"slot": "battle_hit", "priority": "later", "status": "rejected", "candidates": 2},
        {"slot": "battle_miss", "priority": "optional", "status": "unselected", "candidates": 1},
    ]


def test_gaps(review):
    m = build_manifest(review, FIXTURE_ROOT, NOW)
    assert m["gaps"] == [
        {
            "slot": "horn_distant",
            "priority": "later",
            "notes": "No horn sample found.\n\nLeave silent until a candidate is approved.",
        }
    ]


def test_first_pass_unselected_lists_unselected_and_rejected_first_pass_slots(review):
    assert first_pass_unselected(review) == ["ui_confirm"]
    review.slot("battle_hit").priority = "first_pass"
    review.slot("horn_distant").priority = "first_pass"  # gap: not counted here
    assert first_pass_unselected(review) == ["ui_confirm", "battle_hit"]
    review.slot("ui_confirm").select("A003")
    assert first_pass_unselected(review) == ["battle_hit"]
