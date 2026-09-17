"""CSV import (design section 8): the fixture cut of the real spreadsheet, every
warning case, and every error case."""

import csv
from pathlib import Path

import pytest

from audio_picker.csv_import import COLUMNS, import_csv, slugify_pack
from audio_picker.model import ReviewError, from_dict, to_dict

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "audio-review-cut.csv"
FIXTURE_ROOT = Path(r"D:\Projects\one-more-turn\vendor\audio")


def _fixture_rows() -> dict[str, dict]:
    with open(FIXTURE, encoding="utf-8-sig", newline="") as f:
        return {r["ID"]: r for r in csv.DictReader(f)}


@pytest.fixture
def imported():
    warnings: list[str] = []
    review = import_csv(FIXTURE, FIXTURE_ROOT, "one-more-turn", warnings.append)
    return review, warnings


# -- the real cut ------------------------------------------------------------


def test_fixture_imports_without_warnings(imported):
    review, warnings = imported
    assert warnings == []
    assert review.project == "one-more-turn"
    assert review.version == 1


def test_slots_in_first_appearance_order(imported):
    review, _ = imported
    assert [s.id for s in review.slots] == [
        "title_theme",
        "exploration_loop",
        "village_music",
        "ui_click",
        "ui_hover",
        "panel_open",
        "turn_advance",
        "march_grass",
        "beast_tell",
        "horn_distant",
    ]


def test_categories_distinct_in_first_appearance_order(imported):
    review, _ = imported
    assert review.categories == ["Music", "UI", "Movement", "World tells", "Unfilled"]


def test_packs_slugified_with_folder_and_license(imported):
    review, _ = imported
    assert set(review.packs) == {
        "epic_asian",
        "eastern_music",
        "kenney_ui",
        "inventory_sfx",
        "kenney_rpg",
        "pack_100_cc0",
        "nature",
        "creature_cc0",
    }
    assert review.packs["pack_100_cc0"].name == "100 CC0"
    assert review.packs["pack_100_cc0"].folder == "100-CC0-SFX"
    assert review.packs["pack_100_cc0"].license.startswith("CC0 pack; bundled credits.txt")
    assert review.packs["kenney_ui"].folder == "kenney-ui-audio"
    assert review.packs["epic_asian"].license == "Paid; Tao & Sound EULA.txt and purchase invoice"


def test_candidate_fields_are_verbatim_and_path_is_relative(imported):
    review, _ = imported
    row = _fixture_rows()["A010"]
    c = review.slot("ui_click").candidate("A010")
    assert c.path == "kenney-ui-audio/Audio/click1.ogg"
    assert c.pack == "kenney_ui"
    assert c.role == "first"
    assert c.decision == "unreviewed"
    assert c.why == row["Why this candidate"]
    assert c.listen_for == row["Listen for"]
    assert c.proposed_use == row["Proposed use after approval"]
    assert c.notes == row["Your notes"]
    assert not hasattr(c, "assessment")
    assert not hasattr(c, "candidate")


def test_role_mapping(imported):
    review, _ = imported
    assert review.slot("title_theme").candidate("A001").role == "reference"
    assert review.slot("exploration_loop").candidate("A002").role == "first"
    assert review.slot("exploration_loop").candidate("A003").role == "alternative"


def test_priority_mapping(imported):
    review, _ = imported
    p = {s.id: s.priority for s in review.slots}
    assert p["title_theme"] == "first_pass"
    assert p["village_music"] == "later"
    assert p["ui_hover"] == "optional"
    assert p["horn_distant"] == "later", "Gap maps to later; gap-ness is the empty list"


def test_two_candidate_slot_groups_rows_and_takes_header_from_first(imported):
    review, _ = imported
    slot = review.slot("exploration_loop")
    assert [c.id for c in slot.candidates] == ["A002", "A003"]
    assert slot.category == "Music"
    assert slot.function == "Quiet overworld planning and travel"
    assert [c.pack for c in slot.candidates] == ["epic_asian", "eastern_music"]


def test_gap_row_makes_empty_slot_with_joined_notes(imported):
    review, _ = imported
    row = _fixture_rows()["A067"]
    slot = review.slot("horn_distant")
    assert slot.candidates == []
    assert slot.notes == row["Why this candidate"] + "\n\n" + row["Proposed use after approval"]
    assert "A067" not in review.all_candidate_ids()


def test_selected_is_null_everywhere(imported):
    review, _ = imported
    assert all(s.selected is None for s in review.slots)


def test_result_passes_model_validation(imported):
    review, _ = imported
    assert from_dict(to_dict(review)) == review


# -- synthetic CSVs ----------------------------------------------------------


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    return tmp_path / "lib"


def _row(lib: Path, **over) -> dict:
    base = {
        "ID": "A001",
        "Decision (Yay/Nay)": "",
        "Your notes": "",
        "Priority": "First pass",
        "Category": "UI",
        "Game function": "Button press",
        "Slot": "ui_click",
        "Choice": "First choice",
        "Candidate": "click.wav",
        "Why this candidate": "why",
        "Listen for": "listen",
        "Proposed use after approval": "use",
        "Pack": "Kenney UI",
        "License provenance": "CC0",
        "Source path": str(lib / "kenney-ui-audio" / "click.wav"),
        "Assessment": "boilerplate",
    }
    base.update(over)
    return base


def _write(tmp_path: Path, rows: list[dict], columns=COLUMNS, bom=True) -> Path:
    p = tmp_path / "in.csv"
    with open(p, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return p


def _import(tmp_path, lib, rows, **kw):
    warnings: list[str] = []
    review = import_csv(_write(tmp_path, rows, **kw), lib, "t", warnings.append)
    return review, warnings


def test_works_without_bom(tmp_path, lib):
    review, _ = _import(tmp_path, lib, [_row(lib)], bom=False)
    assert review.slot("ui_click").candidate("A001").path == "kenney-ui-audio/click.wav"


def test_decision_is_case_insensitive(tmp_path, lib):
    review, _ = _import(
        tmp_path,
        lib,
        [
            _row(lib, ID="A001", **{"Decision (Yay/Nay)": "YAY"}),
            _row(lib, ID="A002", Choice="Alternative", **{"Decision (Yay/Nay)": "nay"}),
        ],
    )
    slot = review.slot("ui_click")
    assert slot.candidate("A001").decision == "yay"
    assert slot.candidate("A002").decision == "nay"


def test_variation_choice_maps_to_variation(tmp_path, lib):
    review, _ = _import(tmp_path, lib, [_row(lib, Choice="Variation")])
    assert review.slot("ui_click").candidate("A001").role == "variation"


def test_dotdot_inside_root_is_normalised(tmp_path, lib):
    path = str(lib / "kenney-ui-audio" / ".." / "kenney-ui-audio" / "click.wav")
    review, _ = _import(tmp_path, lib, [_row(lib, **{"Source path": path})])
    assert review.slot("ui_click").candidate("A001").path == "kenney-ui-audio/click.wav"


def test_pack_slug_rules():
    assert slugify_pack("Epic Asian") == "epic_asian"
    assert slugify_pack("100 CC0") == "pack_100_cc0"
    assert slugify_pack("  Kenney--UI  ") == "kenney_ui"
    assert slugify_pack("Nature") == "nature"


def test_pack_with_no_name_leaves_candidate_pack_null(tmp_path, lib):
    review, _ = _import(tmp_path, lib, [_row(lib, Pack="", **{"License provenance": ""})])
    assert review.packs == {}
    assert review.slot("ui_click").candidate("A001").pack is None


# warnings


def test_warns_when_category_differs_within_slot_and_keeps_first(tmp_path, lib):
    review, warnings = _import(
        tmp_path,
        lib,
        [_row(lib, ID="A001"), _row(lib, ID="A002", Choice="Alternative", Category="Menus")],
    )
    assert review.slot("ui_click").category == "UI"
    assert len(warnings) == 1 and "ui_click" in warnings[0] and "Category" in warnings[0]


def test_warns_when_function_differs_within_slot(tmp_path, lib):
    _, warnings = _import(
        tmp_path,
        lib,
        [_row(lib, ID="A001"), _row(lib, ID="A002", Choice="Alternative", **{"Game function": "other"})],
    )
    assert len(warnings) == 1 and "Game function" in warnings[0]


def test_warns_when_pack_license_disagrees_and_keeps_first(tmp_path, lib):
    review, warnings = _import(
        tmp_path,
        lib,
        [_row(lib, ID="A001"), _row(lib, ID="A002", Slot="ui_hover", **{"License provenance": "MIT"})],
    )
    assert review.packs["kenney_ui"].license == "CC0"
    assert len(warnings) == 1 and "Kenney UI" in warnings[0] and "license" in warnings[0].lower()


def test_warns_when_pack_folder_disagrees_and_keeps_first(tmp_path, lib):
    other = str(lib / "kenney-ui-2" / "x.wav")
    review, warnings = _import(
        tmp_path,
        lib,
        [_row(lib, ID="A001"), _row(lib, ID="A002", Slot="ui_hover", Candidate="x.wav", **{"Source path": other})],
    )
    assert review.packs["kenney_ui"].folder == "kenney-ui-audio"
    assert len(warnings) == 1 and "folder" in warnings[0].lower()


def test_warns_when_candidate_column_is_not_basename(tmp_path, lib):
    _, warnings = _import(tmp_path, lib, [_row(lib, Candidate="wrong.wav")])
    assert len(warnings) == 1 and "A001" in warnings[0] and "wrong.wav" in warnings[0]


# errors


def _rejects(tmp_path, lib, rows, *needles, **kw):
    with pytest.raises(ReviewError) as info:
        _import(tmp_path, lib, rows, **kw)
    for n in needles:
        assert n in str(info.value), str(info.value)


def test_error_path_outside_root_names_row_and_path(tmp_path, lib):
    outside = str(tmp_path / "elsewhere" / "x.wav")
    _rejects(tmp_path, lib, [_row(lib, **{"Source path": outside})], "A001", "x.wav")


def test_error_dotdot_escaping_root(tmp_path, lib):
    escaped = str(lib / "kenney-ui-audio" / ".." / ".." / "x.wav")
    _rejects(tmp_path, lib, [_row(lib, **{"Source path": escaped})], "A001")


def test_error_empty_path_on_non_gap_row(tmp_path, lib):
    _rejects(tmp_path, lib, [_row(lib, **{"Source path": ""})], "A001", "empty")


def test_error_unknown_priority(tmp_path, lib):
    _rejects(tmp_path, lib, [_row(lib, Priority="Urgent")], "A001", "Urgent")


def test_error_unknown_choice(tmp_path, lib):
    _rejects(tmp_path, lib, [_row(lib, Choice="Maybe")], "A001", "Maybe")


def test_error_unknown_decision(tmp_path, lib):
    _rejects(tmp_path, lib, [_row(lib, **{"Decision (Yay/Nay)": "meh"})], "A001", "meh")


def test_error_two_pack_names_slugify_to_one_id(tmp_path, lib):
    _rejects(
        tmp_path,
        lib,
        [_row(lib, ID="A001"), _row(lib, ID="A002", Slot="ui_hover", Pack="kenney-ui")],
        "kenney_ui",
        "Kenney UI",
        "kenney-ui",
    )


def test_error_duplicate_candidate_id(tmp_path, lib):
    _rejects(tmp_path, lib, [_row(lib, ID="A001"), _row(lib, ID="A001", Slot="ui_hover")], "A001")


def test_error_bad_candidate_id(tmp_path, lib):
    _rejects(tmp_path, lib, [_row(lib, ID="a1")], "a1")


def test_error_missing_required_column(tmp_path, lib):
    cols = [c for c in COLUMNS if c != "Listen for"]
    row = {k: v for k, v in _row(lib).items() if k != "Listen for"}
    _rejects(tmp_path, lib, [row], "Listen for", columns=cols)


def test_error_bad_slot_id(tmp_path, lib):
    _rejects(tmp_path, lib, [_row(lib, Slot="UI Click")], "UI Click")
