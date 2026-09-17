"""Command line (design section 7): dispatch, exit codes, and file behaviour."""

import json
import shutil
from pathlib import Path

import pytest

from audio_picker import cli
from audio_picker.model import load

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "review.json"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"
FIXTURE_CSV = Path(__file__).resolve().parent / "fixtures" / "audio-review-cut.csv"
CSV_ROOT = r"D:\Projects\one-more-turn\vendor\audio"


@pytest.fixture
def review_file(tmp_path: Path) -> Path:
    dst = tmp_path / "review.json"
    shutil.copy(EXAMPLE, dst)
    return dst


@pytest.fixture
def gui(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_launch_gui", lambda review_path, root: calls.append((review_path, root)) or 0)
    return calls


# -- dispatch and exit codes --------------------------------------------------


def test_bare_review_file_opens_gui(review_file, gui):
    assert cli.main([str(review_file), "--root", str(FIXTURE_ROOT)]) == 0
    assert gui == [(review_file, FIXTURE_ROOT)]


def test_gui_subcommand_is_equivalent(review_file, gui):
    assert cli.main(["gui", str(review_file), "--root", str(FIXTURE_ROOT)]) == 0
    assert gui == [(review_file, FIXTURE_ROOT)]


def test_gui_resolves_root_from_review_before_launch(review_file, gui, tmp_path):
    # examples/review.json says "../tests/fixtures/audio" relative to the file.
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "audio").mkdir()
    sub = tmp_path / "sub"
    sub.mkdir()
    moved = sub / "review.json"
    shutil.move(str(review_file), moved)
    assert cli.main([str(moved)]) == 0
    assert gui == [(moved, tmp_path / "tests" / "fixtures" / "audio")]


def test_gui_bad_root_fails_before_launch(review_file, gui, capsys):
    assert cli.main([str(review_file), "--root", str(review_file.parent / "nope")]) == 1
    assert gui == []
    assert "nope" in capsys.readouterr().err


def test_gui_invalid_review_fails_with_message(tmp_path, gui, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": 2}', encoding="utf-8")
    assert cli.main([str(bad), "--root", str(FIXTURE_ROOT)]) == 1
    assert gui == []
    assert "version" in capsys.readouterr().err


def test_missing_review_file_is_exit_1(tmp_path, gui, capsys):
    assert cli.main([str(tmp_path / "nope.json"), "--root", str(FIXTURE_ROOT)]) == 1
    assert "nope.json" in capsys.readouterr().err


def test_usage_error_is_exit_2(capsys):
    assert cli.main([]) == 2
    assert cli.main(["export"]) == 2


# -- check ---------------------------------------------------------------------


def test_check_prints_findings_and_exits_0_without_errors(review_file, capsys):
    assert cli.main(["check", str(review_file), "--root", str(FIXTURE_ROOT)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "warning first_pass_unselected ui_confirm: first-pass slot is unselected" in out
    assert any(line.startswith("warning unmatched_pack_folder battle_miss/A006: ") for line in out)


def test_check_exits_1_on_missing_files(review_file, tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["check", str(review_file), "--root", str(empty)]) == 1
    out = capsys.readouterr().out
    assert "error missing_file ui_click/A001: file not found: packA/click.wav" in out
    assert "error selected_missing ui_click/A001: " in out


# -- export --------------------------------------------------------------------


def test_export_to_stdout(review_file, capsys):
    assert cli.main(["export", str(review_file), "--root", str(FIXTURE_ROOT)]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["manifest_version"] == 1
    assert manifest["selections"][0]["candidate"] == "A001"


def test_export_to_file(review_file, tmp_path):
    out = tmp_path / "manifest.json"
    assert cli.main(["export", str(review_file), "--root", str(FIXTURE_ROOT), "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert json.loads(text)["project"] == "example"


def test_export_strict_fails_on_first_pass_unselected_but_still_writes(review_file, tmp_path, capsys):
    out = tmp_path / "manifest.json"
    code = cli.main(["export", str(review_file), "--root", str(FIXTURE_ROOT), "-o", str(out), "--strict"])
    assert code == 1
    assert out.exists()
    assert "ui_confirm" in capsys.readouterr().err


def test_export_strict_passes_when_first_pass_slots_are_selected(review_file, tmp_path):
    review = load(review_file)
    review.slot("ui_confirm").select("A003")
    from audio_picker.model import save

    save(review, review_file)
    out = tmp_path / "manifest.json"
    assert cli.main(["export", str(review_file), "--root", str(FIXTURE_ROOT), "-o", str(out), "--strict"]) == 0


def test_export_strict_fails_on_selected_missing(review_file, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["export", str(review_file), "--root", str(empty), "--strict", "-o", str(tmp_path / "m.json")]) == 1


# -- import-csv ------------------------------------------------------------------


def test_import_csv_writes_review_with_relative_root(tmp_path, capsys):
    docs = tmp_path / "docs" / "audio"
    docs.mkdir(parents=True)
    root = tmp_path / "vendor" / "audio"
    root.mkdir(parents=True)
    out = docs / "review.json"
    # The fixture CSV's absolute paths live under CSV_ROOT, so relativise against that;
    # here we only care about how --root is recorded, so pass CSV_ROOT and an output elsewhere.
    code = cli.main(["import-csv", str(FIXTURE_CSV), "-o", str(out), "--root", CSV_ROOT, "--project", "omt"])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["project"] == "omt"
    assert len(data["slots"]) == 10
    if Path(CSV_ROOT).drive.lower() == out.drive.lower():
        assert not Path(data["root"]).is_absolute()
        assert (out.parent / data["root"]).resolve() == Path(CSV_ROOT).resolve()
    else:
        assert data["root"] == CSV_ROOT.replace("\\", "/")
    assert capsys.readouterr().err == ""


def test_import_csv_root_relative_when_same_drive(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    lib = tmp_path / "vendor" / "audio" / "kenney-ui-audio"
    lib.mkdir(parents=True)
    csv_path = tmp_path / "in.csv"
    from audio_picker.csv_import import COLUMNS

    row = dict.fromkeys(COLUMNS, "")
    row.update(
        {
            "ID": "A001",
            "Priority": "First pass",
            "Category": "UI",
            "Game function": "f",
            "Slot": "ui_click",
            "Choice": "First choice",
            "Candidate": "click.wav",
            "Pack": "Kenney UI",
            "License provenance": "CC0",
            "Source path": str(lib / "click.wav"),
        }
    )
    import csv

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerow(row)
    out = docs / "review.json"
    assert (
        cli.main(
            [
                "import-csv",
                str(csv_path),
                "-o",
                str(out),
                "--root",
                str(tmp_path / "vendor" / "audio"),
                "--project",
                "p",
            ]
        )
        == 0
    )
    assert json.loads(out.read_text(encoding="utf-8"))["root"] == "../vendor/audio"


def test_import_csv_refuses_overwrite_without_force(tmp_path, capsys):
    out = tmp_path / "review.json"
    out.write_text("old", encoding="utf-8")
    code = cli.main(["import-csv", str(FIXTURE_CSV), "-o", str(out), "--root", CSV_ROOT, "--project", "omt"])
    assert code == 1
    assert out.read_text(encoding="utf-8") == "old"
    assert "--force" in capsys.readouterr().err
    assert (
        cli.main(["import-csv", str(FIXTURE_CSV), "-o", str(out), "--root", CSV_ROOT, "--project", "omt", "--force"])
        == 0
    )
    assert out.read_text(encoding="utf-8").startswith("{")


def test_import_csv_warnings_go_to_stderr_prefixed(tmp_path, capsys):
    import csv

    from audio_picker.csv_import import COLUMNS

    lib = tmp_path / "lib"
    rows = []
    for rid, cat in (("A001", "UI"), ("A002", "Menus")):
        row = dict.fromkeys(COLUMNS, "")
        row.update(
            {
                "ID": rid,
                "Priority": "First pass",
                "Category": cat,
                "Game function": "f",
                "Slot": "ui_click",
                "Choice": "First choice" if rid == "A001" else "Alternative",
                "Candidate": "x.wav",
                "Source path": str(lib / "p" / "x.wav"),
            }
        )
        rows.append(row)
    csv_path = tmp_path / "in.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    out = tmp_path / "out.json"
    assert cli.main(["import-csv", str(csv_path), "-o", str(out), "--root", str(lib), "--project", "p"]) == 0
    err = capsys.readouterr().err.splitlines()
    assert len(err) == 1 and err[0].startswith("warning: ") and "Menus" in err[0]


def test_import_csv_error_writes_nothing(tmp_path, capsys):
    out = tmp_path / "review.json"
    code = cli.main(["import-csv", str(FIXTURE_CSV), "-o", str(out), "--root", str(tmp_path), "--project", "omt"])
    assert code == 1
    assert not out.exists()
    assert "A001" in capsys.readouterr().err


# -- library ---------------------------------------------------------------------


@pytest.fixture
def library_gui(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_launch_library", lambda root: calls.append(root) or 0)
    return calls


def test_library_subcommand_launches_the_viewer(library_gui):
    assert cli.main(["library", "--root", str(FIXTURE_ROOT)]) == 0
    assert library_gui == [FIXTURE_ROOT]


def test_library_requires_root(capsys):
    assert cli.main(["library"]) == 2


def test_library_bad_root_is_exit_1(library_gui, tmp_path, capsys):
    assert cli.main(["library", "--root", str(tmp_path / "nope")]) == 1
    assert library_gui == []
    assert "nope" in capsys.readouterr().err
