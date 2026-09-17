"""Command line (design section 7).

    audio-picker REVIEW.json [--root DIR]            # opens the GUI
    audio-picker gui REVIEW.json [--root DIR]
    audio-picker import-csv INPUT.csv -o REVIEW.json --root DIR --project NAME [--force]
    audio-picker export REVIEW.json [--root DIR] [-o MANIFEST.json] [--strict]
    audio-picker check REVIEW.json [--root DIR]
    audio-picker library --root DIR                  # browse, rate and tag the library

Exit codes: 0 success; 1 validation or file error (message on stderr);
2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .check import check_review
from .csv_import import import_csv
from .export import build_manifest
from .model import ReviewError, load, save
from .paths import resolve_root

SUBCOMMANDS = ("gui", "import-csv", "export", "check", "library")


def _launch_gui(review_path: Path, root: Path) -> int:
    """Imported lazily so the data-layer commands never load Qt."""
    from .ui.app import run

    return run(review_path, root)


def _launch_library(root: Path) -> int:
    from .ui.app import run_library

    return run_library(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audio-picker",
        description="Audition and pick sound assets for a game from a review file.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    gui = sub.add_parser("gui", help="open the review in the GUI (default)")
    gui.add_argument("review", help="review JSON file")
    gui.add_argument("--root", help="audio library directory (overrides the file's root)")

    imp = sub.add_parser("import-csv", help="convert the spreadsheet CSV into a review file")
    imp.add_argument("input", help="CSV file")
    imp.add_argument("-o", "--output", required=True, help="review JSON to write")
    imp.add_argument("--root", required=True, help="audio library directory the CSV paths live under")
    imp.add_argument("--project", required=True, help="project display name")
    imp.add_argument("--force", action="store_true", help="overwrite an existing output file")

    exp = sub.add_parser("export", help="write the manifest of selected files")
    exp.add_argument("review", help="review JSON file")
    exp.add_argument("--root", help="audio library directory (overrides the file's root)")
    exp.add_argument("-o", "--output", help="manifest JSON to write (default: stdout)")
    exp.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if any first-pass slot is unselected or a selected file is missing",
    )

    chk = sub.add_parser("check", help="report missing files and other findings")
    chk.add_argument("review", help="review JSON file")
    chk.add_argument("--root", help="audio library directory (overrides the file's root)")

    lib = sub.add_parser("library", help="browse, rate and tag the audio library without a review file")
    lib.add_argument("--root", required=True, help="audio library directory")
    return parser


def _open(review_arg: str, root_arg: str | None):
    review_path = Path(review_arg)
    review = load(review_path)
    root = resolve_root(review_path, review.root, root_arg)
    return review_path, review, root


def _cmd_gui(args: argparse.Namespace) -> int:
    review_path, _review, root = _open(args.review, args.root)
    return _launch_gui(review_path, root)


def _cmd_check(args: argparse.Namespace) -> int:
    _path, review, root = _open(args.review, args.root)
    report = check_review(review, root)
    for f in report.findings:
        where = f.slot or "-"
        if f.candidate:
            where += f"/{f.candidate}"
        print(f"{f.severity} {f.code} {where}: {f.message}")
    return 1 if report.errors() else 0


def _cmd_export(args: argparse.Namespace) -> int:
    _path, review, root = _open(args.review, args.root)
    manifest = build_manifest(review, root, datetime.now(timezone.utc))
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        try:
            Path(args.output).write_text(text, encoding="utf-8", newline="\n")
        except OSError as e:
            raise ReviewError(f"cannot write {args.output}: {e.strerror or e}") from e
    else:
        sys.stdout.write(text)
    if args.strict:
        report = check_review(review, root)
        bad = [f for f in report.findings if f.code in ("first_pass_unselected", "selected_missing")]
        if bad:
            for f in bad:
                print(f"strict: {f.code} {f.slot}: {f.message}", file=sys.stderr)
            return 1
    return 0


def _record_root(root: Path, output: Path) -> str:
    """`--root` relative to the output's directory when both share a drive, else absolute."""
    root_abs = os.path.abspath(root)
    out_dir = os.path.abspath(output.parent)
    same_anchor = os.path.normcase(os.path.splitdrive(root_abs)[0]) == os.path.normcase(os.path.splitdrive(out_dir)[0])
    if same_anchor:
        return os.path.relpath(root_abs, out_dir).replace("\\", "/")
    return root_abs.replace("\\", "/")


def _cmd_import(args: argparse.Namespace) -> int:
    output = Path(args.output)
    if output.exists() and not args.force:
        raise ReviewError(f"{output} exists; pass --force to overwrite it")
    root = Path(args.root)
    review = import_csv(Path(args.input), root, args.project, lambda m: print(f"warning: {m}", file=sys.stderr))
    review.root = _record_root(root, output)
    try:
        save(review, output)
    except OSError as e:
        raise ReviewError(f"cannot write {output}: {e.strerror or e}") from e
    return 0


def _cmd_library(args: argparse.Namespace) -> int:
    root = resolve_root("", None, args.root)  # only the --root branch of resolve_root is used
    return _launch_library(root)


_HANDLERS = {
    "gui": _cmd_gui,
    "check": _cmd_check,
    "export": _cmd_export,
    "import-csv": _cmd_import,
    "library": _cmd_library,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "gui")
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    try:
        return _HANDLERS[args.command](args)
    except ReviewError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
