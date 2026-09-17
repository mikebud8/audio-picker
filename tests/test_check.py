"""Check report (design section 10): one test per finding code."""

from pathlib import Path

import pytest

from audio_picker.check import CheckReport, Finding, check_review
from audio_picker.model import Pack, load

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "review.json"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"


@pytest.fixture
def review():
    return load(EXAMPLE)


def _codes(report: CheckReport, slot: str | None = None) -> list[str]:
    return [f.code for f in report.findings if slot is None or f.slot == slot]


def test_example_against_fixture_root_has_no_errors(review):
    report = check_review(review, FIXTURE_ROOT)
    assert report.errors() == []


def test_missing_file(review, tmp_path):
    report = check_review(review, tmp_path)  # empty root: every file missing
    missing = [f for f in report.findings if f.code == "missing_file"]
    assert {(f.slot, f.candidate) for f in missing} == {
        ("ui_click", "A001"),
        ("ui_click", "A002"),
        ("ui_confirm", "A003"),
        ("battle_hit", "A004"),
        ("battle_hit", "A005"),
        ("battle_miss", "A006"),
    }
    assert all(f.severity == "error" for f in missing)
    assert "packA/click.wav" in next(f.message for f in missing if f.candidate == "A001")


def test_selected_missing_is_emitted_in_addition(review, tmp_path):
    report = check_review(review, tmp_path)
    ui_click = _codes(report, "ui_click")
    assert ui_click.count("missing_file") == 2
    assert ui_click.count("selected_missing") == 1
    finding = next(f for f in report.findings if f.code == "selected_missing")
    assert finding.candidate == "A001"
    assert finding.severity == "error"


def test_unmatched_pack_folder(review):
    report = check_review(review, FIXTURE_ROOT)
    f = next(f for f in report.findings if f.code == "unmatched_pack_folder")
    assert (f.slot, f.candidate, f.severity) == ("battle_miss", "A006", "warning")
    assert "loose" in f.message


def test_pack_mismatch(review):
    review.slot("ui_click").candidates[0].pack = "pack_b"  # path is under packA
    report = check_review(review, FIXTURE_ROOT)
    f = next(f for f in report.findings if f.code == "pack_mismatch")
    assert (f.slot, f.candidate, f.severity) == ("ui_click", "A001", "warning")
    assert "pack_a" in f.message and "pack_b" in f.message


def test_unused_pack(review):
    review.packs["pack_c"] = Pack("Pack C", "packC", "CC0")
    report = check_review(review, FIXTURE_ROOT)
    f = next(f for f in report.findings if f.code == "unused_pack")
    assert f.slot == ""
    assert f.candidate is None
    assert "pack_c" in f.message
    assert "unused_pack" not in _codes(check_review(load(EXAMPLE), FIXTURE_ROOT))


def test_first_pass_unselected_covers_unselected_and_rejected(review):
    review.slot("battle_hit").priority = "first_pass"  # rejected
    report = check_review(review, FIXTURE_ROOT)
    slots = sorted(f.slot for f in report.findings if f.code == "first_pass_unselected")
    assert slots == ["battle_hit", "ui_confirm"]
    assert "ui_click" not in slots, "a selected first-pass slot is fine"


def test_first_pass_gap(review):
    review.slot("horn_distant").priority = "first_pass"
    report = check_review(review, FIXTURE_ROOT)
    assert _codes(report, "horn_distant") == ["first_pass_gap"]
    assert "first_pass_unselected" not in _codes(report, "horn_distant")


def test_non_first_pass_slots_raise_no_priority_findings(review):
    report = check_review(review, FIXTURE_ROOT)
    assert "first_pass_gap" not in _codes(report)  # horn_distant is `later`
    assert _codes(report, "battle_hit") == []  # rejected but `later`


def test_report_helpers():
    report = CheckReport(
        [
            Finding("missing_file", "error", "s", "A1", "m"),
            Finding("unused_pack", "warning", "", None, "m"),
        ]
    )
    assert report.has("missing_file")
    assert report.has("nope", "unused_pack")
    assert not report.has("nope")
    assert [f.code for f in report.errors()] == ["missing_file"]
    assert CheckReport([]).errors() == []


def test_findings_are_ordered_by_slot_file_order(review, tmp_path):
    report = check_review(review, tmp_path)
    slot_order = [s.id for s in review.slots]
    seen = [f.slot for f in report.findings if f.slot]
    assert seen == sorted(seen, key=slot_order.index)
