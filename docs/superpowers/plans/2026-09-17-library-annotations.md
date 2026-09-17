# Library Annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user rate, tag and annotate any file in the audio library from three places (review window dock, Add Candidate dialog, standalone viewer), stored in one sidecar JSON next to the library, without touching the audio files or the review loop.

**Architecture:** A pure-Python `LibraryAnnotations` store (one per audio root, one per process) backed by `<root>/audio-picker-library.json`. One reusable `AnnotationEditor` widget writes straight through to the store and emits `changed`. Hosts own the debounced save timer. The standalone `LibraryWindow` adds search, tag and rating filters, and a transport bar, and is launched from the CLI or from the review window's File menu.

**Tech Stack:** Python 3.11+, PySide6 6.11, pytest + pytest-qt, ruff. Tests run with `.venv/Scripts/python -m pytest` (the `python` on PATH is a dead stub; always use the venv).

**Spec:** `docs/superpowers/specs/2026-09-17-library-annotations-design.md`. Deviations from the spec made in this plan, all minor:
- The round-trip fixture lives at `tests/fixtures/library-annotations.json`, not inside `tests/fixtures/audio/`, so UI tests that run against the checked-in audio fixture never find or write a sidecar there. UI tests that annotate copy the audio fixture to a temp root first.
- A constructor never raises: `LibraryAnnotations.__init__` catches the load error into `load_error` so hosts can always build the object. `reload()` still raises.
- Opening another review with a different root closes an open standalone viewer instead of re-pointing it.
- Empty entries are dropped immediately in memory rather than only at save time; the on-disk result is identical.
- The editor gets an `escape()` method for hosts with a window-level Escape shortcut and an `escape_pressed` signal for the dialog, which has none.
- The editor emits `changed(rel)`; hosts forward it to `AnnotationHub.notify_changed`, which owns the save timer and fans the change out to every other host.
- The review's yes/no "Quit without saving?" dialog is replaced by the three-way unsaved-changes dialog from spec section 6, so one dialog covers both files on quit and on opening another review.
- The standalone viewer gets a Rescan action (F5) so a fixed sidecar can be recovered without restarting.

**Conventions for every task:**
- Run `.venv/Scripts/ruff check audio_picker tests` and `.venv/Scripts/ruff format audio_picker tests` before each commit. Line length is 120, imports sorted.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` on its own line after a blank line.
- Every test module that touches Qt inherits the offscreen platform from `tests/conftest.py`; nothing to set.

---

## File map

| Path | Responsibility |
|---|---|
| `audio_picker/annotations.py` (new) | `Annotation`, `normalise_tag`, `LibraryAnnotations`, `AnnotationsError`. Sidecar load, validate, mutate, save. No Qt. |
| `audio_picker/model.py` (modify) | Extract `relative_path_problem()` from `_check_candidate_path` so the sidecar validates keys with the same rule. |
| `audio_picker/library.py` (modify) | `search()` gains `annotations=` and `#tag` terms. |
| `audio_picker/ui/path_delegate.py` (new) | `PathDelegate` moved out of `dialogs.py`, with an optional muted summary drawn after the path. |
| `audio_picker/ui/keys.py` (new) | `text_field_focused()` moved out of `MainWindow` so `LibraryWindow` shares the single-key rule. |
| `audio_picker/ui/annotation_editor.py` (new) | `FlowLayout`, `TagChip`, `AnnotationEditor`. Disabled while the store is read-only. |
| `audio_picker/ui/annotation_hub.py` (new) | `AnnotationHub`: store reference, save timer, `changed` / `reloaded` / `save_failed` signals. |
| `tests/test_annotation_hub.py` (new) | Hub tests. |
| `audio_picker/ui/slot_panel.py` (modify) | New `active_changed` signal. |
| `audio_picker/ui/dialogs.py` (modify) | `AddCandidateDialog` takes the hub and hosts an editor; `Dialogs.add_candidate` passes it through; `Dialogs.unsaved` replaces `quit_without_saving`. |
| `audio_picker/ui/library_window.py` (new) | `LibraryWindow`. |
| `audio_picker/ui/main_window.py` (modify) | Hub creation, `flush() -> bool`, unsaved-changes settling on quit and open, dock, View menu, `saveState`, rescan reload, root switch, viewer launch. |
| `audio_picker/ui/app.py` (modify) | `run_library(root)`. |
| `audio_picker/cli.py` (modify) | `library --root DIR` subcommand. |
| `tests/test_annotations.py` (new) | Store tests, no Qt. |
| `tests/fixtures/library-annotations.json` (new) | Canonical-form fixture for the byte-identical round trip. |
| `tests/test_library.py` (modify) | `#tag` search. |
| `tests/test_annotation_editor.py` (new) | Editor widget tests. |
| `tests/test_library_window.py` (new) | Viewer tests. |
| `tests/test_ui_smoke.py` (modify) | `FakeDialogs.add_candidate` signature, dock and persistence tests. |
| `tests/test_screenshots.py` (modify) | Dock, widened dialog, viewer. |
| `tests/test_cli.py` (modify) | `library` dispatch. |
| `README.md` (modify) | Commands, library notes section, shortcuts. |

---

### Task 1: Shared relative-path rule in `model.py`

**Files:**
- Modify: `audio_picker/model.py:179-186`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_model.py`:

```python
# -- relative path rule ---------------------------------------------------------


def test_relative_path_problem_names_each_rule():
    from audio_picker.model import relative_path_problem

    assert relative_path_problem("packA/click.wav") is None
    assert relative_path_problem("") == "path is empty"
    assert "absolute" in relative_path_problem("/abs/x.wav")
    assert "absolute" in relative_path_problem("C:/abs/x.wav")
    assert "absolute" in relative_path_problem("\\\\server\\x.wav")
    assert "'.' or '..'" in relative_path_problem("packA/../x.wav")
    assert "'.' or '..'" in relative_path_problem("./x.wav")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_model.py::test_relative_path_problem_names_each_rule -q`
Expected: FAIL with `ImportError: cannot import name 'relative_path_problem'`

- [ ] **Step 3: Implement**

In `audio_picker/model.py` replace the whole `_check_candidate_path` function with:

```python
def relative_path_problem(path: str) -> str | None:
    """None if `path` is a usable root-relative path, else a short description of what is wrong."""
    if not path:
        return "path is empty"
    if path[0] in "/\\" or re.match(r"^[A-Za-z]:", path):
        return f"path {path!r} is absolute; paths are relative to root"
    parts = re.split(r"[/\\]", path)
    if any(p in (".", "..") for p in parts):
        return f"path {path!r} contains a '.' or '..' component"
    return None


def _check_candidate_path(path: str, where: str) -> None:
    problem = relative_path_problem(path)
    if problem is not None:
        raise ReviewError(f"{where}: {problem}")
```

- [ ] **Step 4: Run the model tests**

Run: `.venv/Scripts/python -m pytest tests/test_model.py tests/test_model_validation.py -q`
Expected: all PASS (the existing validation messages are unchanged).

- [ ] **Step 5: Commit**

```bash
git add audio_picker/model.py tests/test_model.py
git commit -m "Expose the relative-path rule as relative_path_problem

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `annotations.py` — tag normalisation, loading and validation

**Files:**
- Create: `audio_picker/annotations.py`
- Create: `tests/fixtures/library-annotations.json`
- Create: `tests/test_annotations.py`

- [ ] **Step 1: Create the fixture**

Write `tests/fixtures/library-annotations.json` exactly (two-space indent, LF, trailing newline; this is what `json.dumps(indent=2)` produces):

```json
{
  "version": 1,
  "tags": [
    "click",
    "orphan",
    "ui"
  ],
  "files": {
    "packA/click.wav": {
      "rating": 4,
      "tags": [
        "click",
        "ui"
      ],
      "note": "Clean and short."
    },
    "packZ/gone.wav": {
      "tags": [
        "orphan"
      ]
    }
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_annotations.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_annotations.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_picker.annotations'`

- [ ] **Step 4: Implement loading and validation**

Create `audio_picker/annotations.py`:

```python
"""Library-wide annotations: rating, tags and note per audio file.

Stored in `<root>/audio-picker-library.json` (library annotations spec,
section 3). One store per audio root per process. Imports nothing from Qt.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import relative_path_problem

SIDECAR_NAME = "audio-picker-library.json"
ANNOTATIONS_VERSION = 1
RATINGS = (1, 2, 3, 4, 5)

_WS_RE = re.compile(r"\s+")
_TOP_KEYS = ("version", "tags", "files")
_FILE_KEYS = ("rating", "tags", "note")


class AnnotationsError(Exception):
    """The sidecar file failed validation. The message names the problem."""


def normalise_tag(raw: str) -> str:
    """Strip, lowercase, internal whitespace to '-'. Raises ValueError if nothing is left."""
    tag = _WS_RE.sub("-", raw.strip().lower())
    if not tag:
        raise ValueError("tag is empty")
    return tag


@dataclass
class Annotation:
    rating: int | None = None
    tags: list[str] = field(default_factory=list)
    note: str = ""

    def is_empty(self) -> bool:
        return self.rating is None and not self.tags and not self.note


# -- parsing -------------------------------------------------------------------------


def _check_tag(raw: Any, where: str) -> str:
    if not isinstance(raw, str):
        raise AnnotationsError(f"{where}: tags must be a list of strings")
    try:
        normalised = normalise_tag(raw)
    except ValueError:
        normalised = ""
    if normalised != raw:
        raise AnnotationsError(f"{where}: tag {raw!r} is not normalised (expected {normalised!r})")
    return raw


def _check_tags(raw: Any, where: str) -> list[str]:
    if not isinstance(raw, list):
        raise AnnotationsError(f"{where}: tags must be a list of strings")
    return sorted({_check_tag(t, where) for t in raw})


def _check_rating(raw: Any, where: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw not in RATINGS:
        raise AnnotationsError(f"{where}: rating must be an integer from 1 to 5")
    return raw


def from_dict(data: Any) -> tuple[dict[str, Annotation], set[str]]:
    """Validate parsed JSON. Returns (files, vocabulary)."""
    where = "annotations"
    if not isinstance(data, dict):
        raise AnnotationsError(f"{where}: expected an object, got {type(data).__name__}")
    if data.get("version") != ANNOTATIONS_VERSION:
        raise AnnotationsError(
            f"{where}: unsupported version {data.get('version')!r} (expected {ANNOTATIONS_VERSION})"
        )
    extra = [k for k in data if k not in _TOP_KEYS]
    if extra:
        raise AnnotationsError(f"{where}: unknown key(s) {', '.join(extra)}")
    vocabulary = set(_check_tags(data.get("tags", []), f"{where} tags"))
    files_raw = data.get("files", {})
    if not isinstance(files_raw, dict):
        raise AnnotationsError(f"{where}: files must be an object")

    files: dict[str, Annotation] = {}
    for key, raw in files_raw.items():
        fwhere = f"file {key!r}"
        problem = relative_path_problem(key)
        if problem is not None:
            raise AnnotationsError(f"{fwhere}: {problem}")
        if not isinstance(raw, dict):
            raise AnnotationsError(f"{fwhere}: expected an object, got {type(raw).__name__}")
        unknown = [k for k in raw if k not in _FILE_KEYS]
        if unknown:
            raise AnnotationsError(f"{fwhere}: unknown key(s) {', '.join(unknown)}")
        note = raw.get("note", "")
        if not isinstance(note, str):
            raise AnnotationsError(f"{fwhere}: note must be a string")
        annotation = Annotation(
            rating=_check_rating(raw.get("rating"), fwhere),
            tags=_check_tags(raw.get("tags", []), fwhere),
            note=note,
        )
        if not annotation.is_empty():
            files[key] = annotation
            vocabulary.update(annotation.tags)
    return files, vocabulary


def _parse(path: Path) -> tuple[dict[str, Annotation], set[str]]:
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as e:
        raise AnnotationsError(f"cannot read {path}: {e.strerror or e}") from e
    except UnicodeDecodeError as e:
        raise AnnotationsError(f"{path}: not valid UTF-8 ({e})") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AnnotationsError(f"{path}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}") from e
    return from_dict(data)


# -- store ---------------------------------------------------------------------------


class LibraryAnnotations:
    """Annotations for one audio root. Mutators mark `dirty`; the host decides when to `save()`."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / SIDECAR_NAME
        self.dirty = False
        self.read_only = False
        self.load_error: str | None = None
        self._files: dict[str, Annotation] = {}
        self._vocabulary: set[str] = set()
        try:
            self.reload()
        except AnnotationsError:
            pass  # recorded in load_error; the store is empty and read_only

    def reload(self) -> None:
        """Re-read from disk. A missing file gives an empty store.

        A malformed file empties the store, sets `read_only` and `load_error`,
        and raises AnnotationsError.
        """
        self._files = {}
        self._vocabulary = set()
        self.dirty = False
        if not self.path.exists():
            self.read_only = False
            self.load_error = None
            return
        try:
            self._files, self._vocabulary = _parse(self.path)
        except AnnotationsError as e:
            self.read_only = True
            self.load_error = str(e)
            raise
        self.read_only = False
        self.load_error = None

    # -- reading ------------------------------------------------------------------

    def get(self, rel: str) -> Annotation:
        """A copy; an empty Annotation for an unknown path."""
        a = self._files.get(rel)
        return Annotation(a.rating, list(a.tags), a.note) if a is not None else Annotation()

    def has(self, rel: str) -> bool:
        return rel in self._files

    def has_tag(self, rel: str, tag: str) -> bool:
        a = self._files.get(rel)
        return a is not None and tag in a.tags

    def vocabulary(self) -> list[str]:
        return sorted(self._vocabulary)

    def annotated(self) -> list[str]:
        return sorted(self._files)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_annotations.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add audio_picker/annotations.py tests/test_annotations.py tests/fixtures/library-annotations.json
git commit -m "Add the library annotations store: load and validate the sidecar

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `annotations.py` — mutators, filters and atomic save

**Files:**
- Modify: `audio_picker/annotations.py`
- Test: `tests/test_annotations.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_annotations.py`:

```python
# -- mutators ------------------------------------------------------------------------


def test_set_rating_marks_dirty_and_validates(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.set_rating("a.wav", 3)
    assert store.dirty
    assert store.get("a.wav").rating == 3
    store.set_rating("a.wav", None)
    assert store.get("a.wav").rating is None
    for bad in (0, 6, True, "4"):
        with pytest.raises(ValueError):
            store.set_rating("a.wav", bad)


def test_add_tag_normalises_sorts_and_grows_vocabulary(tmp_path):
    store = LibraryAnnotations(tmp_path)
    assert store.add_tag("a.wav", " UI ") == "ui"
    assert store.add_tag("a.wav", "Click") == "click"
    assert store.get("a.wav").tags == ["click", "ui"]
    assert store.vocabulary() == ["click", "ui"]
    assert store.dirty


def test_add_duplicate_tag_is_a_no_op(root):
    store = LibraryAnnotations(root)
    assert store.add_tag("packA/click.wav", "ui") == "ui"
    assert store.get("packA/click.wav").tags == ["click", "ui"]
    assert not store.dirty


def test_add_empty_tag_raises(tmp_path):
    store = LibraryAnnotations(tmp_path)
    with pytest.raises(ValueError):
        store.add_tag("a.wav", "  ")
    assert not store.dirty


def test_remove_tag_keeps_the_vocabulary(root):
    store = LibraryAnnotations(root)
    store.remove_tag("packZ/gone.wav", "orphan")
    assert not store.has("packZ/gone.wav"), "an entry with nothing left is dropped"
    assert "orphan" in store.vocabulary()
    assert store.dirty


def test_remove_unknown_tag_is_a_no_op(root):
    store = LibraryAnnotations(root)
    store.remove_tag("packA/click.wav", "nope")
    store.remove_tag("nope.wav", "ui")
    assert not store.dirty


def test_set_note_and_clearing_everything_drops_the_entry(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.set_note("a.wav", "hello")
    assert store.get("a.wav").note == "hello"
    assert store.annotated() == ["a.wav"]
    store.set_note("a.wav", "")
    assert store.annotated() == []


def test_set_note_to_same_text_is_a_no_op(root):
    store = LibraryAnnotations(root)
    store.set_note("packA/click.wav", "Clean and short.")
    store.set_note("other.wav", "")
    assert not store.dirty


# -- filters ---------------------------------------------------------------------------


def test_files_with_and_min_rating(root):
    store = LibraryAnnotations(root)
    store.set_rating("packB/hit.mp3", 2)
    store.add_tag("packB/hit.mp3", "ui")
    assert store.files_with("UI") == ["packA/click.wav", "packB/hit.mp3"]
    assert store.files_with("orphan") == ["packZ/gone.wav"]
    assert store.files_with("nope") == []
    assert store.min_rating(1) == ["packA/click.wav", "packB/hit.mp3"]
    assert store.min_rating(3) == ["packA/click.wav"]
    assert store.min_rating(5) == []


# -- saving --------------------------------------------------------------------------


def test_round_trip_is_byte_identical(root):
    store = LibraryAnnotations(root)
    store.dirty = True
    store.save()
    assert (root / SIDECAR_NAME).read_bytes() == FIXTURE.read_bytes()
    assert not store.dirty
    assert not (root / (SIDECAR_NAME + ".tmp")).exists()


def test_save_writes_sorted_keys_lf_and_omits_empty_fields(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.add_tag("z.wav", "b")
    store.set_rating("a.wav", 5)
    store.set_note("m.wav", "line1\nline2")
    store.save()
    raw = (tmp_path / SIDECAR_NAME).read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"}\n")
    data = json.loads(raw)
    assert list(data) == ["version", "tags", "files"]
    assert list(data["files"]) == ["a.wav", "m.wav", "z.wav"]
    assert data["files"]["a.wav"] == {"rating": 5}
    assert data["files"]["m.wav"] == {"note": "line1\nline2"}
    assert data["files"]["z.wav"] == {"tags": ["b"]}
    assert data["tags"] == ["b"]


def test_save_is_a_no_op_when_read_only(tmp_path):
    p = write_sidecar(tmp_path, {"version": 9})
    store = LibraryAnnotations(tmp_path)
    store.set_rating("a.wav", 1)
    store.save()
    assert json.loads(p.read_text(encoding="utf-8")) == {"version": 9}
    assert store.dirty


def test_save_failure_raises_oserror_and_keeps_dirty(tmp_path):
    store = LibraryAnnotations(tmp_path)
    store.set_rating("a.wav", 1)
    (tmp_path / SIDECAR_NAME).mkdir()  # a directory in the way
    with pytest.raises(OSError):
        store.save()
    assert store.dirty


def test_reload_picks_up_a_disk_change(tmp_path):
    store = LibraryAnnotations(tmp_path)
    write_sidecar(tmp_path, {"version": 1, "tags": [], "files": {"n.wav": {"rating": 2}}})
    assert not store.has("n.wav")
    store.reload()
    assert store.get("n.wav").rating == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_annotations.py -q`
Expected: the new tests FAIL with `AttributeError: 'LibraryAnnotations' object has no attribute 'set_rating'` and similar.

- [ ] **Step 3: Implement**

Append inside the `LibraryAnnotations` class in `audio_picker/annotations.py`:

```python
    # -- mutating -----------------------------------------------------------------

    def _entry(self, rel: str) -> Annotation:
        return self._files.setdefault(rel, Annotation())

    def _settle(self, rel: str) -> None:
        """Drop an entry that has nothing left, then mark dirty."""
        a = self._files.get(rel)
        if a is not None and a.is_empty():
            del self._files[rel]
        self.dirty = True

    def set_rating(self, rel: str, rating: int | None) -> None:
        if rating is not None and (isinstance(rating, bool) or rating not in RATINGS):
            raise ValueError(f"rating must be 1 to 5 or None, got {rating!r}")
        if self.get(rel).rating == rating:
            return
        self._entry(rel).rating = rating
        self._settle(rel)

    def add_tag(self, rel: str, tag: str) -> str:
        """Normalise, add if absent, grow the vocabulary. Returns the normalised tag."""
        tag = normalise_tag(tag)
        entry = self._files.get(rel)
        if entry is not None and tag in entry.tags:
            return tag
        entry = self._entry(rel)
        entry.tags = sorted(entry.tags + [tag])
        self._vocabulary.add(tag)
        self._settle(rel)
        return tag

    def remove_tag(self, rel: str, tag: str) -> None:
        tag = normalise_tag(tag)
        entry = self._files.get(rel)
        if entry is None or tag not in entry.tags:
            return
        entry.tags.remove(tag)
        self._settle(rel)

    def set_note(self, rel: str, note: str) -> None:
        if self.get(rel).note == note:
            return
        self._entry(rel).note = note
        self._settle(rel)

    # -- filters ------------------------------------------------------------------

    def files_with(self, tag: str) -> list[str]:
        tag = normalise_tag(tag)
        return sorted(k for k, a in self._files.items() if tag in a.tags)

    def min_rating(self, n: int) -> list[str]:
        return sorted(k for k, a in self._files.items() if a.rating is not None and a.rating >= n)

    # -- writing ------------------------------------------------------------------

    def to_dict(self) -> dict:
        files: dict[str, dict] = {}
        for key in sorted(self._files):
            a = self._files[key]
            entry: dict = {}
            if a.rating is not None:
                entry["rating"] = a.rating
            if a.tags:
                entry["tags"] = list(a.tags)
            if a.note:
                entry["note"] = a.note
            files[key] = entry
        return {"version": ANNOTATIONS_VERSION, "tags": self.vocabulary(), "files": files}

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def save(self) -> None:
        """Atomic write through `<file>.tmp`. A no-op while `read_only`. Raises OSError."""
        if self.read_only:
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        data = self.dumps().encode("utf-8")
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        self.dirty = False
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_annotations.py -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format audio_picker tests
git add audio_picker/annotations.py tests/test_annotations.py
git commit -m "Annotations store: mutators, filters and atomic save

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `#tag` terms in `AudioLibrary.search`

**Files:**
- Modify: `audio_picker/library.py:44-48`
- Test: `tests/test_library.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_library.py`:

```python
# -- tag terms -----------------------------------------------------------------------


def test_hash_terms_match_tags_from_the_store(root):
    from audio_picker.annotations import LibraryAnnotations

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_library.py -q`
Expected: the two new tests FAIL with `TypeError: ... unexpected keyword argument 'annotations'`.

- [ ] **Step 3: Implement**

Replace the `search` method in `audio_picker/library.py` with:

```python
    def search(self, query: str, limit: int = 500, annotations=None) -> list[str]:
        """Case-insensitive. Every whitespace-separated term must match.

        A term starting with `#` names a tag in `annotations` (a
        `LibraryAnnotations`); other terms are path substrings. Tag terms
        match nothing without a store. A bare `#` is ignored.
        """
        terms = query.lower().split()
        tag_terms = [t[1:] for t in terms if t.startswith("#") and len(t) > 1]
        path_terms = [t for t in terms if not t.startswith("#")]
        if tag_terms and annotations is None:
            return []
        hits: list[str] = []
        for p in self._paths:
            low = p.lower()
            if not all(t in low for t in path_terms):
                continue
            if tag_terms and not all(annotations.has_tag(p, t) for t in tag_terms):
                continue
            hits.append(p)
            if len(hits) >= limit:
                break
        return hits
```

Also update the module docstring's first paragraph in `library.py` to mention: "`search` accepts `#tag` terms when given a `LibraryAnnotations` store."

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_library.py -q`
Expected: all PASS, including the existing cap and empty-query tests.

- [ ] **Step 5: Commit**

```bash
git add audio_picker/library.py tests/test_library.py
git commit -m "Library search: #tag terms backed by the annotations store

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Shared `PathDelegate` and `text_field_focused`

**Files:**
- Create: `audio_picker/ui/path_delegate.py`
- Create: `audio_picker/ui/keys.py`
- Modify: `audio_picker/ui/dialogs.py` (remove `_PathDelegate`, import `PathDelegate`)
- Modify: `audio_picker/ui/main_window.py` (`_text_focused` delegates to `keys.text_field_focused`)

No new behaviour, so no new tests; the existing suite covers both.

- [ ] **Step 1: Create `audio_picker/ui/path_delegate.py`**

```python
"""List delegate for relative library paths: pack folder bold, optional muted summary."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPalette, QTextDocument
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .theme import dim_color

PATH_ROLE = Qt.ItemDataRole.UserRole
SUMMARY_ROLE = Qt.ItemDataRole.UserRole + 1


def path_html(rel: str, color: str, summary: str = "", dim: str = "") -> str:
    folder, sep, rest = rel.partition("/")
    body = f"<b>{escape(folder)}</b>/{escape(rest)}" if sep else escape(rel)
    html = f'<span style="color: {color}">{body}</span>'
    if summary:
        html += f'&nbsp;&nbsp;<span style="color: {dim}">{escape(summary)}</span>'
    return html


class PathDelegate(QStyledItemDelegate):
    """Draws `PATH_ROLE` with its first component bold and `SUMMARY_ROLE` dimmed after it."""

    def _document(self, option: QStyleOptionViewItem, index, selected: bool = False) -> QTextDocument:
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(2)
        rel = index.data(PATH_ROLE) or index.data() or ""
        summary = index.data(SUMMARY_ROLE) or ""
        color = option.palette.color(role).name()
        dim = color if selected else dim_color(option.palette).name()
        doc.setHtml(path_html(rel, color, summary, dim))
        return doc

    def paint(self, painter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QStyle()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        doc = self._document(opt, index, selected=bool(opt.state & QStyle.StateFlag.State_Selected))
        painter.save()
        painter.translate(opt.rect.left(), opt.rect.top() + (opt.rect.height() - doc.size().height()) / 2)
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        doc = self._document(option, index)
        return QSize(int(doc.idealWidth()), int(doc.size().height()))
```

- [ ] **Step 2: Create `audio_picker/ui/keys.py`**

```python
"""Keyboard rules shared by the windows (design 13.6)."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit


def text_field_focused() -> bool:
    """True while a text-entry widget has focus, when single-key shortcuts must stay quiet."""
    w = QApplication.focusWidget()
    if isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
        return True
    return isinstance(w, QComboBox) and w.isEditable()
```

- [ ] **Step 3: Use them in `dialogs.py`**

In `audio_picker/ui/dialogs.py`:
- Delete the whole `class _PathDelegate(QStyledItemDelegate): ...` block (lines 70 to 103).
- Remove `QSize` from the `PySide6.QtCore` import, `QPalette` and `QTextDocument` from the `PySide6.QtGui` import, and `QStyle`, `QStyledItemDelegate`, `QStyleOptionViewItem` from the `QtWidgets` import.
- Add `from .path_delegate import PATH_ROLE, PathDelegate` after `from ..paths import ...`.
- In `AddCandidateDialog.__init__` change `self.results.setItemDelegate(_PathDelegate(self.results))` to `self.results.setItemDelegate(PathDelegate(self.results))`.
- In `_refresh_results` change `item.setData(Qt.ItemDataRole.UserRole, rel)` to `item.setData(PATH_ROLE, rel)`, and in `_on_current_result` change `current.data(Qt.ItemDataRole.UserRole)` to `current.data(PATH_ROLE)`.

- [ ] **Step 4: Use `text_field_focused` in `main_window.py`**

In `audio_picker/ui/main_window.py`:
- Remove `QAbstractSpinBox`, `QComboBox`, `QLineEdit`, `QPlainTextEdit`, `QTextEdit` from the `QtWidgets` import (keep `QApplication` only if still used; after this change it is not, so remove it too).
- Add `from .keys import text_field_focused`.
- Replace the `_text_focused` static method body with:

```python
    @staticmethod
    def _text_focused() -> bool:
        return text_field_focused()
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/python -m pytest -q`
Expected: 194 + the tests added so far all PASS.

- [ ] **Step 6: Commit**

```bash
git add audio_picker/ui/path_delegate.py audio_picker/ui/keys.py audio_picker/ui/dialogs.py audio_picker/ui/main_window.py
git commit -m "Share PathDelegate and the text-field focus rule between windows

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `AnnotationEditor` widget

**Files:**
- Create: `audio_picker/ui/annotation_editor.py`
- Create: `tests/test_annotation_editor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_annotation_editor.py`:

```python
"""AnnotationEditor writes straight through to the store (spec section 4)."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from audio_picker.annotations import SIDECAR_NAME, LibraryAnnotations
from audio_picker.ui.annotation_editor import AnnotationEditor


@pytest.fixture
def store(tmp_path: Path) -> LibraryAnnotations:
    s = LibraryAnnotations(tmp_path)
    s.add_tag("packA/click.wav", "ui")
    s.add_tag("packB/hit.mp3", "hit")
    s.set_rating("packA/click.wav", 4)
    s.set_note("packA/click.wav", "Clean.")
    s.dirty = False
    return s


@pytest.fixture
def editor(qtbot, store):
    e = AnnotationEditor(store)
    qtbot.addWidget(e)
    e.resize(280, 400)
    e.show()
    qtbot.waitExposed(e)
    return e


def test_no_path_disables_everything(editor):
    editor.set_path(None)
    assert "No file" in editor.path_label.text()
    assert not editor.tag_input.isEnabled()
    assert not editor.note.isEnabled()
    assert not any(s.isEnabled() for s in editor.stars)


def test_set_path_loads_the_annotation(editor):
    editor.set_path("packA/click.wav")
    assert "packA" in editor.path_label.text() and "click.wav" in editor.path_label.text()
    assert editor.path_label.toolTip() == "packA/click.wav"
    assert [s.text() for s in editor.stars] == ["★", "★", "★", "★", "☆"]
    assert not editor.unrated.isVisible()
    assert editor.chip_tags() == ["ui"]
    assert editor.note.toPlainText() == "Clean."
    assert editor.tag_input.isEnabled()


def test_unannotated_path_shows_unrated_and_empty(editor):
    editor.set_path("packB/hit.mp3")
    assert [s.text() for s in editor.stars] == ["☆"] * 5
    assert editor.unrated.isVisible()
    assert editor.chip_tags() == ["hit"]
    assert editor.note.toPlainText() == ""


def test_star_click_sets_and_reclick_clears(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    with qtbot.waitSignal(editor.changed) as blocker:
        editor.stars[2].click()
    assert blocker.args == ["packB/hit.mp3"]
    assert store.get("packB/hit.mp3").rating == 3
    assert [s.text() for s in editor.stars] == ["★", "★", "★", "☆", "☆"]
    editor.stars[2].click()
    assert store.get("packB/hit.mp3").rating is None
    assert editor.unrated.isVisible()


def test_enter_commits_a_normalised_tag(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    editor.tag_input.setFocus()
    qtbot.keyClicks(editor.tag_input, " Metallic Hit ")
    with qtbot.waitSignal(editor.changed):
        qtbot.keyClick(editor.tag_input, Qt.Key.Key_Return)
    assert store.get("packB/hit.mp3").tags == ["hit", "metallic-hit"]
    assert editor.chip_tags() == ["hit", "metallic-hit"]
    assert editor.tag_input.text() == ""
    assert "metallic-hit" in editor.completer_words()


def test_comma_commits_a_tag_and_keeps_the_rest(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    qtbot.keyClicks(editor.tag_input, "loop,sea")
    assert store.get("packB/hit.mp3").tags == ["hit", "loop"]
    assert editor.tag_input.text() == "sea"


def test_duplicate_or_empty_tag_is_a_no_op(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    qtbot.keyClicks(editor.tag_input, "HIT")
    qtbot.keyClick(editor.tag_input, Qt.Key.Key_Return)
    qtbot.keyClick(editor.tag_input, Qt.Key.Key_Return)
    assert store.get("packB/hit.mp3").tags == ["hit"]
    assert not store.dirty
    assert editor.tag_input.text() == ""


def test_chip_remove_button_removes_the_tag(qtbot, editor, store):
    editor.set_path("packA/click.wav")
    with qtbot.waitSignal(editor.changed):
        editor.chips[0].remove.click()
    assert store.get("packA/click.wav").tags == []
    assert editor.chip_tags() == []


def test_note_writes_through_per_keystroke(qtbot, editor, store):
    editor.set_path("packB/hit.mp3")
    editor.note.setFocus()
    qtbot.keyClicks(editor.note, "abc")
    assert store.get("packB/hit.mp3").note == "abc"
    assert editor.note.textCursor().position() == 3


def test_set_path_does_not_emit_changed_or_dirty(qtbot, editor, store):
    with qtbot.assertNotEmitted(editor.changed):
        editor.set_path("packA/click.wav")
        editor.set_path("packB/hit.mp3")
        editor.set_path(None)
    assert not store.dirty


def test_refresh_reflects_outside_changes_without_moving_the_cursor(qtbot, editor, store):
    editor.set_path("packA/click.wav")
    store.add_tag("packA/click.wav", "extra")
    store.set_rating("packA/click.wav", 1)
    editor.refresh()
    assert editor.chip_tags() == ["extra", "ui"]
    assert [s.text() for s in editor.stars] == ["★", "☆", "☆", "☆", "☆"]
    assert editor.note.toPlainText() == "Clean."


def test_escape_clears_the_tag_field_and_signals(qtbot, editor):
    editor.set_path("packA/click.wav")
    editor.tag_input.setFocus()
    qtbot.keyClicks(editor.tag_input, "half")
    with qtbot.waitSignal(editor.escape_pressed):
        qtbot.keyClick(editor.tag_input, Qt.Key.Key_Escape)
    assert editor.tag_input.text() == ""


def test_read_only_store_shows_but_disables_editing(qtbot, tmp_path):
    (tmp_path / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    broken = LibraryAnnotations(tmp_path)
    assert broken.read_only
    e = AnnotationEditor(broken)
    qtbot.addWidget(e)
    e.set_path("a.wav")
    assert "a.wav" in e.path_label.text()
    assert not e.tag_input.isEnabled()
    assert not e.note.isEnabled()
    assert not any(s.isEnabled() for s in e.stars)
    assert "read-only" in e.tag_input.placeholderText()


def test_completer_matches_anywhere_case_insensitively(editor):
    editor.set_path("packA/click.wav")
    editor.completer.setCompletionPrefix("I")
    words = [
        editor.completer.completionModel().index(i, 0).data()
        for i in range(editor.completer.completionModel().rowCount())
    ]
    assert words == ["hit", "ui"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_annotation_editor.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_picker.ui.annotation_editor'`

- [ ] **Step 3: Implement the widget**

Create `audio_picker/ui/annotation_editor.py`:

```python
"""Rating, tags and note for one library file (library annotations spec, section 4).

Knows the `LibraryAnnotations` store and a current relative path, nothing
about reviews, slots or the player. Every control change writes straight
through to the store and emits `changed(rel)`.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..annotations import RATINGS, LibraryAnnotations, normalise_tag
from .path_delegate import path_html
from .theme import dim_color, dim_css

FILLED, EMPTY = "★", "☆"


class FlowLayout(QLayout):
    """Wraps its items into rows, like text. Port of Qt's flowlayout example."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), dry_run=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, dry_run=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, *, dry_run: bool) -> int:
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and row_height > 0:
                x = rect.x()
                y += row_height + self._spacing
                row_height = 0
            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y()


class TagChip(QFrame):
    removed = Signal(str)

    def __init__(self, tag: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tag = tag
        self.setObjectName("tagChip")
        self.setStyleSheet(
            "#tagChip { border: 1px solid palette(mid); border-radius: 9px; background: palette(alternate-base); }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 2, 1)
        layout.setSpacing(2)
        self.label = QLabel(tag)
        self.remove = QToolButton()
        self.remove.setText("×")
        self.remove.setAutoRaise(True)
        self.remove.setToolTip(f"Remove tag {tag}")
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.clicked.connect(lambda: self.removed.emit(self.tag))
        layout.addWidget(self.label)
        layout.addWidget(self.remove)


class AnnotationEditor(QWidget):
    changed = Signal(str)  # relative path whose annotation was edited
    escape_pressed = Signal()  # Escape in a text field, after the tag field was cleared

    def __init__(self, store: LibraryAnnotations, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._rel: str | None = None
        self._loading = False
        self.chips: list[TagChip] = []
        self.setMinimumWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.path_label = QLabel()
        self.path_label.setTextFormat(Qt.TextFormat.RichText)
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.path_label)

        rating_row = QWidget()
        rating_row.setToolTip("Recording quality, not preference")
        rating_layout = QHBoxLayout(rating_row)
        rating_layout.setContentsMargins(0, 0, 0, 0)
        rating_layout.setSpacing(0)
        self.stars: list[QToolButton] = []
        for n in RATINGS:
            star = QToolButton()
            star.setText(EMPTY)
            star.setAutoRaise(True)
            star.setCursor(Qt.CursorShape.PointingHandCursor)
            star.setStyleSheet("font-size: 16pt;")
            star.setToolTip(f"Rate {n} of 5" + (" (junk)" if n == 1 else ""))
            star.clicked.connect(lambda _checked=False, n=n: self._on_star(n))
            rating_layout.addWidget(star)
            self.stars.append(star)
        self.unrated = QLabel("unrated")
        self.unrated.setStyleSheet(dim_css())
        rating_layout.addSpacing(6)
        rating_layout.addWidget(self.unrated)
        rating_layout.addStretch(1)
        layout.addWidget(rating_row)

        self.chips_container = QWidget()
        self.chips_layout = FlowLayout(self.chips_container)
        layout.addWidget(self.chips_container)

        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Add tag (Enter or comma)")
        self.tag_input.setClearButtonEnabled(True)
        self._completer_model = QStringListModel(self)
        self.completer = QCompleter(self._completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.tag_input.setCompleter(self.completer)
        # Enter is handled in eventFilter so a dialog's default button never sees it.
        self.tag_input.textEdited.connect(self._on_tag_text_edited)
        self.tag_input.installEventFilter(self)
        layout.addWidget(self.tag_input)

        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("Note: what you learned listening to this file")
        self.note.setTabChangesFocus(True)
        self.note.setMinimumHeight(self.note.fontMetrics().lineSpacing() * 4 + 12)
        self.note.textChanged.connect(self._on_note_changed)
        self.note.installEventFilter(self)
        layout.addWidget(self.note, 1)

        self.set_path(None)

    # -- public ---------------------------------------------------------------

    @property
    def path(self) -> str | None:
        return self._rel

    def set_store(self, store: LibraryAnnotations) -> None:
        self._store = store
        self.set_path(None)

    def set_path(self, rel: str | None) -> None:
        self._rel = rel
        self._load()

    def refresh(self) -> None:
        """Re-read the current path from the store; leaves the note cursor alone when the text is unchanged."""
        self._load()

    def escape(self) -> None:
        """Clear a half-typed tag. Hosts with a window-level Escape shortcut call this."""
        self.tag_input.clear()

    def chip_tags(self) -> list[str]:
        return [c.tag for c in self.chips]

    def completer_words(self) -> list[str]:
        return list(self._completer_model.stringList())

    # -- loading --------------------------------------------------------------

    def _load(self) -> None:
        self._loading = True
        try:
            rel = self._rel
            read_only = self._store.read_only
            enabled = rel is not None and not read_only
            for star in self.stars:
                star.setEnabled(enabled)
            self.tag_input.setEnabled(enabled)
            self.note.setEnabled(enabled)
            self.tag_input.setPlaceholderText(
                "Library notes are read-only until the sidecar is fixed" if read_only else "Add tag (Enter or comma)"
            )
            self._completer_model.setStringList(self._store.vocabulary())
            if rel is None:
                self.path_label.setText('<span style="color: %s">No file</span>' % dim_color().name())
                self.path_label.setToolTip("")
                self._show_rating(None)
                self._show_tags([])
                if self.note.toPlainText():
                    self.note.clear()
                return
            annotation = self._store.get(rel)
            self._render_path()
            self._show_rating(annotation.rating)
            self._show_tags(annotation.tags)
            if self.note.toPlainText() != annotation.note:
                self.note.setPlainText(annotation.note)
        finally:
            self._loading = False

    def _render_path(self) -> None:
        rel = self._rel or ""
        self.path_label.setToolTip(rel)
        folder, sep, rest = rel.partition("/")
        fm = self.path_label.fontMetrics()
        available = max(40, self.path_label.width() - 8)
        if sep:
            rest = fm.elidedText(rest, Qt.TextElideMode.ElideMiddle, available - fm.horizontalAdvance(folder + "/"))
            shown = f"{folder}/{rest}"
        else:
            shown = fm.elidedText(rel, Qt.TextElideMode.ElideMiddle, available)
        self.path_label.setText(path_html(shown, self.palette().text().color().name()))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self._rel is not None:
            self._render_path()

    def _show_rating(self, rating: int | None) -> None:
        for n, star in zip(RATINGS, self.stars):
            star.setText(FILLED if rating is not None and n <= rating else EMPTY)
        self.unrated.setVisible(rating is None and self._rel is not None)

    def _show_tags(self, tags: list[str]) -> None:
        for chip in self.chips:
            self.chips_layout.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self.chips = []
        for tag in tags:
            chip = TagChip(tag)
            chip.removed.connect(self._remove_tag)
            self.chips_layout.addWidget(chip)
            self.chips.append(chip)
        self.chips_container.setVisible(bool(tags))
        self.chips_container.updateGeometry()

    # -- editing --------------------------------------------------------------

    def _emit(self) -> None:
        if self._rel is not None:
            self.changed.emit(self._rel)

    def _on_star(self, n: int) -> None:
        if self._rel is None:
            return
        current = self._store.get(self._rel).rating
        self._store.set_rating(self._rel, None if current == n else n)
        self._show_rating(self._store.get(self._rel).rating)
        self._emit()

    def _commit_tag(self, text: str) -> bool:
        """Add `text` as a tag if it normalises to something new. Returns True if the store changed."""
        if self._rel is None:
            return False
        try:
            tag = normalise_tag(text)
        except ValueError:
            return False
        if self._store.has_tag(self._rel, tag):
            return False
        self._store.add_tag(self._rel, tag)
        self._show_tags(self._store.get(self._rel).tags)
        self._completer_model.setStringList(self._store.vocabulary())
        self._emit()
        return True

    def _commit_tag_field(self) -> None:
        self._commit_tag(self.tag_input.text())
        self.tag_input.clear()

    def _on_tag_text_edited(self, text: str) -> None:
        if "," not in text:
            return
        *done, remainder = text.split(",")
        for part in done:
            self._commit_tag(part)
        self.tag_input.setText(remainder.lstrip())

    def _remove_tag(self, tag: str) -> None:
        if self._rel is None:
            return
        self._store.remove_tag(self._rel, tag)
        self._show_tags(self._store.get(self._rel).tags)
        self._emit()

    def _on_note_changed(self) -> None:
        if self._loading or self._rel is None:
            return
        text = self.note.toPlainText()
        if self._store.get(self._rel).note == text:
            return
        self._store.set_note(self._rel, text)
        self._emit()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if obj is self.tag_input and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._commit_tag_field()
                return True  # consumed: a dialog's default button must not fire
            if key == Qt.Key.Key_Escape:
                if obj is self.tag_input and self.completer.popup().isVisible():
                    return False  # let the completer close its popup first
                self.escape()
                self.escape_pressed.emit()
                return True
        return super().eventFilter(obj, event)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_annotation_editor.py -q`
Expected: all PASS. If `test_completer_matches_anywhere_case_insensitively` fails because the completion model is empty, call `editor.completer.complete()` is not needed; instead ensure `setCompletionPrefix` runs after `set_path` populated the model (it does). If the star buttons report `isEnabled()` true while hidden, the test only checks `isEnabled`, which is independent of visibility.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format audio_picker tests
git add audio_picker/ui/annotation_editor.py tests/test_annotation_editor.py
git commit -m "Add the AnnotationEditor widget: stars, tag chips, note

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `SlotPanel.active_changed` signal

**Files:**
- Modify: `audio_picker/ui/slot_panel.py`
- Test: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ui_smoke.py` under a new heading:

```python
# -- active candidate signal -----------------------------------------------------------


def test_panel_emits_active_changed_on_slot_change_play_and_empty_slot(qtbot, win):
    seen: list = []
    win.panel.active_changed.connect(seen.append)
    win.tree.select_slot("ui_confirm")  # one candidate: A003 becomes active by default
    assert seen[-1] == "A003"
    win.tree.select_slot("ui_click")
    assert seen[-1] == "A001"
    press(qtbot, win, Qt.Key.Key_2)
    assert seen[-1] == "A002"
    n = len(seen)
    press(qtbot, win, Qt.Key.Key_2)  # stopping keeps A002 active: no new emission
    assert len(seen) == n
    win.tree.select_slot("horn_distant")
    assert seen[-1] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_ui_smoke.py::test_panel_emits_active_changed_on_slot_change_play_and_empty_slot -q`
Expected: FAIL with `AttributeError: 'SlotPanel' object has no attribute 'active_changed'`

- [ ] **Step 3: Implement**

In `audio_picker/ui/slot_panel.py`:

Add to the signal list at the top of `SlotPanel`:

```python
    active_changed = Signal(object)  # candidate id (str) or None, emitted only when it differs
```

In `__init__`, after `self._playing: str | None = None`, add:

```python
        self._emitted_active: str | None = None
```

In `show_slot`, replace:

```python
        if slot is None:
            self.gap_notes.setVisible(False)
            return
```

with:

```python
        if slot is None:
            self.gap_notes.setVisible(False)
            self._update_active()
            return
```

Replace `_update_active` with:

```python
    def _update_active(self) -> None:
        active = self.active_candidate_id()
        for row in self.rows:
            row.set_active(row.cid == active)
        if active != self._emitted_active:
            self._emitted_active = active
            self.active_changed.emit(active)
```

- [ ] **Step 4: Run the smoke tests**

Run: `.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add audio_picker/ui/slot_panel.py tests/test_ui_smoke.py
git commit -m "SlotPanel: emit active_changed when the active candidate changes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: `AnnotationHub`

**Files:**
- Create: `audio_picker/ui/annotation_hub.py`
- Create: `tests/test_annotation_hub.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_annotation_hub.py`:

```python
"""AnnotationHub: change fan-out and the debounced sidecar save (spec section 3.5)."""

import json
from pathlib import Path

import pytest

from audio_picker.annotations import SIDECAR_NAME, LibraryAnnotations
from audio_picker.ui.annotation_hub import AnnotationHub


@pytest.fixture
def hub(qtbot, tmp_path: Path) -> AnnotationHub:
    return AnnotationHub(LibraryAnnotations(tmp_path))


def test_notify_changed_emits_and_autosaves(qtbot, hub, tmp_path):
    hub.store.set_rating("a.wav", 3)
    with qtbot.waitSignal(hub.changed) as blocker:
        hub.notify_changed("a.wav")
    assert blocker.args == ["a.wav"]
    qtbot.waitUntil(lambda: (tmp_path / SIDECAR_NAME).exists(), timeout=3000)
    assert not hub.store.dirty


def test_flush_saves_now_and_reports_true(hub, tmp_path):
    hub.store.set_note("a.wav", "x")
    hub.notify_changed("a.wav")
    assert hub.flush()
    assert LibraryAnnotations(tmp_path).get("a.wav").note == "x"
    assert hub.flush(), "nothing pending counts as success"


def test_failed_save_emits_save_failed_and_keeps_dirty(qtbot, hub, tmp_path):
    (tmp_path / SIDECAR_NAME).mkdir()
    hub.store.set_rating("a.wav", 1)
    with qtbot.waitSignal(hub.save_failed) as blocker:
        assert not hub.flush()
    assert "library notes" in blocker.args[0].lower()
    assert hub.store.dirty


def test_reload_refuses_a_dirty_store_but_still_emits(qtbot, hub):
    hub.store.set_rating("a.wav", 1)
    with qtbot.waitSignal(hub.reloaded):
        text = hub.reload()
    assert "not reloaded" in text
    assert hub.store.get("a.wav").rating == 1


def test_reload_reads_the_disk_when_clean(qtbot, hub, tmp_path):
    good = {"version": 1, "tags": [], "files": {"b.wav": {"rating": 2}}}
    (tmp_path / SIDECAR_NAME).write_text(json.dumps(good), encoding="utf-8")
    with qtbot.waitSignal(hub.reloaded):
        text = hub.reload()
    assert text == "library notes reloaded"
    assert hub.store.get("b.wav").rating == 2


def test_reload_reports_a_still_broken_file(hub, tmp_path):
    (tmp_path / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    assert hub.reload() == "library notes not loaded"
    assert hub.store.read_only


def test_set_store_stops_the_timer_and_emits(qtbot, hub, tmp_path):
    hub.store.set_rating("a.wav", 1)
    hub.notify_changed("a.wav")
    other = LibraryAnnotations(tmp_path / "other")
    with qtbot.waitSignal(hub.reloaded):
        hub.set_store(other)
    assert hub.store is other
    qtbot.wait(700)
    assert not (tmp_path / SIDECAR_NAME).exists(), "the old store was dropped, not saved"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_annotation_hub.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_picker.ui.annotation_hub'`

- [ ] **Step 3: Implement**

Create `audio_picker/ui/annotation_hub.py`:

```python
"""The one Qt object between the pure annotations store and its hosts (spec section 3.5).

Hosts call `notify_changed` after every write and subscribe to `changed`
and `reloaded`. The hub owns the debounced save; the window that created
the hub shows `save_failed`.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from ..annotations import AnnotationsError, LibraryAnnotations

AUTOSAVE_MS = 500


class AnnotationHub(QObject):
    changed = Signal(str)  # a host wrote this relative path to the store
    reloaded = Signal()  # store replaced or re-read, or the library index changed: re-read everything
    save_failed = Signal(str)  # message for the owning window to show

    def __init__(self, store: LibraryAnnotations, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTOSAVE_MS)
        self._timer.timeout.connect(self._autosave)

    def notify_changed(self, rel: str) -> None:
        """Call after every write to the store."""
        self._timer.start()
        self.changed.emit(rel)

    def set_store(self, store: LibraryAnnotations) -> None:
        """Swap in the store for another root. The old one must already be settled or discarded."""
        self._timer.stop()
        self.store = store
        self.reloaded.emit()

    def reload(self) -> str:
        """Rescan hook: re-read the sidecar unless dirty; always emit `reloaded`. Returns a status fragment."""
        if self.store.dirty:
            text = "library notes not reloaded (unsaved edits)"
        else:
            try:
                self.store.reload()
            except AnnotationsError:
                pass  # recorded in store.load_error; the store is empty and read_only
            text = "library notes not loaded" if self.store.read_only else "library notes reloaded"
        self.reloaded.emit()
        return text

    def _autosave(self) -> None:
        if self.store.dirty:
            self.save()

    def save(self) -> bool:
        """Write if dirty. False means the sidecar is still unsaved and `save_failed` was emitted."""
        if not self.store.dirty or self.store.read_only:
            return True
        try:
            self.store.save()
        except OSError as e:
            self._timer.stop()
            self.save_failed.emit(f"Could not write library notes to {self.store.path}:\n{e}")
            return False
        return True

    def flush(self) -> bool:
        self._timer.stop()
        return self.save()
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_annotation_hub.py -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format audio_picker tests
git add audio_picker/ui/annotation_hub.py tests/test_annotation_hub.py
git commit -m "Add AnnotationHub: shared change fan-out and debounced sidecar save

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Hub in the review window; flush, unsaved-changes settling, rescan, root switch

**Files:**
- Modify: `audio_picker/ui/main_window.py`
- Modify: `audio_picker/ui/dialogs.py` (`Dialogs.unsaved` replaces `quit_without_saving`)
- Modify: `tests/test_ui_smoke.py`

No dock yet; that is Task 10.

- [ ] **Step 1: Update the fake and the existing quit test**

In `tests/test_ui_smoke.py`, add imports:

```python
from audio_picker.annotations import SIDECAR_NAME, LibraryAnnotations
from audio_picker.ui.annotation_hub import AnnotationHub
```

In `FakeDialogs.__init__` replace `self.quit_answer = True` with `self.unsaved_answer = "discard"`, and replace the `quit_without_saving` method with:

```python
    def unsaved(self, parent, action: str, files: list[str]) -> str:
        self.calls.append(("unsaved", action, tuple(files)))
        return self.unsaved_answer
```

Add a fixture after `review_file`:

```python
@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    """A writable copy of the audio fixture so annotation saves never touch the repo."""
    dst = tmp_path / "audio"
    shutil.copytree(FIXTURE_ROOT, dst)
    return dst
```

Replace `test_quit_after_cancelled_save_asks_for_confirmation` with:

```python
def test_quit_after_cancelled_save_asks_and_can_be_cancelled(qtbot, win, review_file):
    _rewrite_on_disk(review_file, "edited-elsewhere")
    win.tree.select_slot("ui_confirm")
    press(qtbot, win, Qt.Key.Key_Y)
    win.dialogs.unsaved_answer = "cancel"
    assert not win.close()
    assert ("unsaved", "quit", ("review.json",)) in win.dialogs.calls
    win.dialogs.unsaved_answer = "discard"
    assert win.close()
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_ui_smoke.py`:

```python
# -- library annotations hub -------------------------------------------------------------


def test_window_builds_the_hub_for_its_root(make_win, tmp_root):
    w = make_win(tmp_root)
    assert isinstance(w.hub, AnnotationHub)
    assert w.hub.store.path == tmp_root / SIDECAR_NAME


def test_hub_change_autosaves_the_sidecar(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    w.hub.store.set_rating("packA/click.wav", 4)
    w.hub.notify_changed("packA/click.wav")
    qtbot.waitUntil(lambda: (tmp_root / SIDECAR_NAME).exists(), timeout=3000)
    assert LibraryAnnotations(tmp_root).get("packA/click.wav").rating == 4


def test_ctrl_s_flushes_the_sidecar(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    w.hub.store.add_tag("packA/click.wav", "ui")
    w.hub.notify_changed("packA/click.wav")
    press(qtbot, w, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert LibraryAnnotations(tmp_root).has_tag("packA/click.wav", "ui")


def test_close_flushes_the_sidecar(make_win, tmp_root):
    w = make_win(tmp_root)
    w.hub.store.set_note("packA/click.wav", "bye")
    w.hub.notify_changed("packA/click.wav")
    assert w.close()
    assert LibraryAnnotations(tmp_root).get("packA/click.wav").note == "bye"


def _break_sidecar_saves(w, tmp_root) -> None:
    """A directory where the sidecar should be makes every save raise OSError."""
    (tmp_root / SIDECAR_NAME).mkdir()
    w.hub.store.set_rating("packA/click.wav", 2)
    w.hub.notify_changed("packA/click.wav")


def test_sidecar_save_failure_shows_an_error(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    qtbot.waitUntil(
        lambda: any(c[0] == "error" and "library notes" in c[1].lower() for c in w.dialogs.calls), timeout=3000
    )
    assert w.hub.store.dirty


def test_quit_with_unsaved_sidecar_asks_and_cancel_keeps_the_window(make_win, tmp_root):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    w.dialogs.unsaved_answer = "cancel"
    assert not w.close()
    assert ("unsaved", "quit", (SIDECAR_NAME,)) in w.dialogs.calls
    w.dialogs.unsaved_answer = "discard"
    assert w.close()


def test_quit_retry_succeeds_once_the_obstacle_is_gone(make_win, tmp_root):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    answers = iter(["retry", "cancel"])

    def unsaved(parent, action, files):
        w.dialogs.calls.append(("unsaved", action, tuple(files)))
        (tmp_root / SIDECAR_NAME).rmdir()
        return next(answers)

    w.dialogs.unsaved = unsaved
    assert w.close()
    assert LibraryAnnotations(tmp_root).get("packA/click.wav").rating == 2
    assert [c for c in w.dialogs.calls if c[0] == "unsaved"] == [("unsaved", "quit", (SIDECAR_NAME,))]


def test_unsaved_dialog_names_both_files(qtbot, make_win, tmp_root, review_file):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    _rewrite_on_disk(review_file, "edited-elsewhere")  # the review save will hit the conflict dialog (cancel)
    w.tree.select_slot("ui_confirm")
    press(qtbot, w, Qt.Key.Key_Y)
    w.dialogs.unsaved_answer = "cancel"
    assert not w.close()
    assert ("unsaved", "quit", ("review.json", SIDECAR_NAME)) in w.dialogs.calls


def test_open_other_with_unsaved_sidecar_cancel_keeps_everything(make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    _break_sidecar_saves(w, tmp_root)
    w.dialogs.unsaved_answer = "cancel"
    w.dialogs.open_target = tmp_path / "never.json"
    w.actions["open"].trigger()
    assert ("unsaved", "open another review", (SIDECAR_NAME,)) in w.dialogs.calls
    assert ("open_review_path",) not in w.dialogs.calls
    assert w.hub.store.dirty


def _other_review(tmp_path: Path) -> tuple[Path, Path]:
    other_root = tmp_path / "other_audio"
    shutil.copytree(FIXTURE_ROOT, other_root)
    other_review = tmp_path / "other" / "review.json"
    other_review.parent.mkdir()
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["root"] = "../other_audio"
    other_review.write_text(json.dumps(data), encoding="utf-8")
    return other_review, other_root


def test_open_other_review_flushes_and_switches_the_store(make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    w.hub.store.add_tag("packA/click.wav", "first")
    w.hub.notify_changed("packA/click.wav")
    other_review, other_root = _other_review(tmp_path)
    w.dialogs.open_target = other_review
    w.actions["open"].trigger()
    assert LibraryAnnotations(tmp_root).has_tag("packA/click.wav", "first")
    assert w.hub.store.path == other_root / SIDECAR_NAME
    assert not w.hub.store.has_tag("packA/click.wav", "first")


def test_malformed_sidecar_is_reported_once_and_the_store_is_read_only(make_win, tmp_root):
    (tmp_root / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    w = make_win(tmp_root)
    assert sum(1 for c in w.dialogs.calls if c[0] == "error" and "version" in c[1]) == 1
    assert w.hub.store.read_only
    assert w.annotations_warning.isVisible()
    assert "rescan" in w.annotations_warning.text()


def test_rescan_reloads_a_fixed_sidecar_and_clears_the_warning(make_win, tmp_root):
    (tmp_root / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    w = make_win(tmp_root)
    good = {"version": 1, "tags": [], "files": {"packA/click.wav": {"tags": ["fixed"]}}}
    (tmp_root / SIDECAR_NAME).write_text(json.dumps(good), encoding="utf-8")
    w.actions["rescan"].trigger()
    assert not w.hub.store.read_only
    assert not w.annotations_warning.isVisible()
    assert w.hub.store.has_tag("packA/click.wav", "fixed")
    assert "reloaded" in w.statusBar().currentMessage()


def test_rescan_keeps_a_dirty_store_and_says_so(make_win, tmp_root):
    w = make_win(tmp_root)
    w.hub.store.add_tag("packA/click.wav", "mine")
    w.hub.notify_changed("packA/click.wav")
    w.actions["rescan"].trigger()  # fires before the 500 ms autosave, so the store is still dirty
    assert w.hub.store.has_tag("packA/click.wav", "mine")
    assert "not reloaded" in w.statusBar().currentMessage()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q`
Expected: the new tests FAIL with `AttributeError: 'MainWindow' object has no attribute 'hub'`; the rewritten quit test FAILS because `quit_without_saving` no longer exists on the fake.

- [ ] **Step 4: Replace `quit_without_saving` in `dialogs.py`**

In `audio_picker/ui/dialogs.py` replace the `quit_without_saving` method of `Dialogs` with:

```python
    def unsaved(self, parent: QWidget | None, action: str, files: list[str]) -> str:
        """Files could not be saved. Returns "retry", "discard" or "cancel"."""
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"{' and '.join(files)} could not be saved.")
        box.setInformativeText(f"Try again, or discard the unsaved changes and {action}.")
        retry = box.addButton("Try again", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(f"Discard and {action}", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is retry:
            return "retry"
        if clicked is discard:
            return "discard"
        return "cancel"
```

- [ ] **Step 5: Implement in `main_window.py`**

Imports: add `QLabel` to the `QtWidgets` import, and

```python
from ..annotations import LibraryAnnotations
from .annotation_hub import AnnotationHub
from .theme import error_css
```

In `__init__`, right after `self.library = AudioLibrary(self.root)`:

```python
        self.hub = AnnotationHub(LibraryAnnotations(self.root), self)
        self.hub.save_failed.connect(lambda message: self.dialogs.error(self, "Save failed", message))
        self.hub.reloaded.connect(self._on_annotations_reloaded)
```

After `self._run_check()` near the end of `__init__`: `self._report_annotations_load()`.

In `_build_widgets`, replace `self.statusBar()` with:

```python
        self.annotations_warning = QLabel()
        self.annotations_warning.setStyleSheet(error_css())
        self.annotations_warning.hide()
        self.statusBar().addPermanentWidget(self.annotations_warning)
```

Replace `flush` with:

```python
    def flush(self) -> bool:
        """Cancel the timers and save both files now if dirty. False if either is still unsaved."""
        self._save_timer.stop()
        review_ok = self._save() if self._dirty else True
        notes_ok = self.hub.flush()
        return review_ok and notes_ok
```

Add a new section after `flush`:

```python
    # -- unsaved changes ------------------------------------------------------------------

    def _unsaved_files(self) -> list[str]:
        files = []
        if self._dirty:
            files.append(self.review_path.name)
        if self.hub.store.dirty:
            files.append(self.hub.store.path.name)
        return files

    def settle_unsaved(self, action: str) -> bool:
        """Flush both files; on failure ask try again / discard / cancel. True means go ahead."""
        while not self.flush():
            answer = self.dialogs.unsaved(self, action, self._unsaved_files())
            if answer == "discard":
                return True
            if answer != "retry":
                return False
        return True

    # -- library annotations ----------------------------------------------------------------

    def _report_annotations_load(self) -> None:
        """Show a malformed-sidecar error and keep a permanent warning while the store is read-only."""
        store = self.hub.store
        if store.load_error:
            self.dialogs.error(self, "Library notes not loaded", store.load_error)
        self.annotations_warning.setText(
            f"Library notes not loaded: fix {store.path.name} and rescan" if store.read_only else ""
        )
        self.annotations_warning.setVisible(store.read_only)

    def _on_annotations_reloaded(self) -> None:
        self._report_annotations_load()
```

Replace `_rescan`:

```python
    def _rescan(self) -> None:
        self.library.refresh()
        self._run_check()
        self.tree.set_missing(self._missing_slots)
        self.panel.set_missing(self._missing_cids)
        notes = self.hub.reload()
        self._status(f"Library rescanned: {len(self.library)} audio files; {notes}. " + self.statusBar().currentMessage())
```

In `_open_other`, replace the first line `self.flush()` with:

```python
        if not self.settle_unsaved("open another review"):
            return
```

and after `self.library = AudioLibrary(root)` add `self.hub.set_store(LibraryAnnotations(root))`.

Replace `closeEvent`:

```python
    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.settle_unsaved("quit"):
            event.ignore()
            return
        self.player.stop()
        self.settings.setValue("window/geometry", self.saveGeometry())
        event.accept()
```

`_on_current_slot` and `_export` keep calling `flush()` and ignoring its result, as they do today: a failed save there already shows its own error and the change stays in memory.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all PASS. `test_unsaved_dialog_names_both_files` depends on the review save failing through the conflict dialog with the fake's default `conflict_answer = "cancel"`, which returns False from `_save`.

- [ ] **Step 7: Lint and commit**

```bash
.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format audio_picker tests
git add audio_picker/ui/main_window.py audio_picker/ui/dialogs.py tests/test_ui_smoke.py
git commit -m "Review window owns the annotation hub; unsaved changes block quit and open

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 10: "Library notes" dock in the review window

**Files:**
- Modify: `audio_picker/ui/main_window.py`
- Modify: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_smoke.py`:

```python
# -- library notes dock ------------------------------------------------------------------


def test_dock_is_hidden_by_default_and_toggles_from_the_view_menu(win):
    assert not win.notes_dock.isVisible()
    win.notes_dock.toggleViewAction().trigger()
    assert win.notes_dock.isVisible()
    assert win.notes_dock.objectName() == "libraryNotesDock"
    assert [a.text() for a in win.menuBar().actions()] == ["&File", "&Slot", "&Candidate", "&View", "&Help"]


def test_dock_follows_the_active_candidate(qtbot, win):
    win.notes_dock.show()
    assert win.notes_editor.path == "packA/click.wav"
    press(qtbot, win, Qt.Key.Key_2)
    assert win.notes_editor.path == "packA/confirm.ogg"
    win.tree.select_slot("battle_hit")
    assert win.notes_editor.path == "packB/hit.mp3"
    win.tree.select_slot("horn_distant")
    assert win.notes_editor.path is None


def test_dock_edit_goes_through_the_hub_and_autosaves(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    w.notes_dock.show()
    with qtbot.waitSignal(w.hub.changed):
        w.notes_editor.stars[4].click()
    assert w.hub.store.get("packA/click.wav").rating == 5
    qtbot.waitUntil(lambda: (tmp_root / SIDECAR_NAME).exists(), timeout=3000)


def test_dock_reflects_a_change_made_elsewhere(make_win, tmp_root):
    w = make_win(tmp_root)
    w.notes_dock.show()
    w.hub.store.set_rating("packA/click.wav", 3)
    w.hub.notify_changed("packA/click.wav")
    assert [s.text() for s in w.notes_editor.stars] == ["★", "★", "★", "☆", "☆"]


def test_typing_y_in_the_dock_note_does_not_mark_a_decision(qtbot, win):
    win.notes_dock.show()
    win.notes_editor.note.setFocus()
    qtbot.keyClicks(win.notes_editor.note, "yn1")
    assert win.review.slot("ui_click").candidate("A002").decision == "unreviewed"
    assert not any(c[0] == "play" for c in win.player.calls)
    assert win.hub.store.get("packA/click.wav").note == "yn1"


def test_escape_in_the_dock_clears_the_tag_field_and_returns_to_the_tree(qtbot, win):
    win.notes_dock.show()
    win.notes_editor.tag_input.setFocus()
    qtbot.keyClicks(win.notes_editor.tag_input, "half")
    qtbot.keyClick(win.notes_editor.tag_input, Qt.Key.Key_Escape)
    assert win.notes_editor.tag_input.text() == ""
    assert win.tree.view.hasFocus()


def test_dock_state_is_saved_and_restored(qtbot, tmp_path, review_file):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(review_file, FIXTURE_ROOT, player=FakePlayer(), dialogs=FakeDialogs(), settings=settings)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.notes_dock.show()
    assert w.close()
    w2 = MainWindow(review_file, FIXTURE_ROOT, player=FakePlayer(), dialogs=FakeDialogs(), settings=settings)
    qtbot.addWidget(w2)
    w2.show()
    qtbot.waitExposed(w2)
    assert w2.notes_dock.isVisible()


def test_dock_is_disabled_while_the_sidecar_is_malformed_and_recovers_on_rescan(make_win, tmp_root):
    (tmp_root / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    w = make_win(tmp_root)
    w.notes_dock.show()
    assert w.notes_editor.path == "packA/click.wav"
    assert not w.notes_editor.note.isEnabled()
    (tmp_root / SIDECAR_NAME).write_text('{"version": 1, "tags": [], "files": {}}', encoding="utf-8")
    w.actions["rescan"].trigger()
    assert w.notes_editor.path == "packA/click.wav"
    assert w.notes_editor.note.isEnabled()
    assert not w.annotations_warning.isVisible()


def test_open_other_review_repoints_the_dock(make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    w.notes_dock.show()
    other_review, other_root = _other_review(tmp_path)
    w.dialogs.open_target = other_review
    w.actions["open"].trigger()
    assert w.notes_editor.path == "packA/click.wav"
    w.notes_editor.stars[0].click()
    assert w.hub.store.path == other_root / SIDECAR_NAME
    assert w.hub.store.get("packA/click.wav").rating == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q -k dock`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute 'notes_dock'`.

- [ ] **Step 3: Implement**

In `audio_picker/ui/main_window.py`:

Imports: add `QDockWidget` to the `QtWidgets` import and `from .annotation_editor import AnnotationEditor`.

In `_build_widgets`, after the status bar block:

```python
        self.notes_editor = AnnotationEditor(self.hub.store)
        self.notes_editor.changed.connect(self.hub.notify_changed)
        self.notes_editor.escape_pressed.connect(self.tree.view.setFocus)  # only fires when the dock floats
        self.notes_dock = QDockWidget("Library notes", self)
        self.notes_dock.setObjectName("libraryNotesDock")
        self.notes_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)
        self.notes_dock.setWidget(self.notes_editor)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.notes_dock)
        self.notes_dock.hide()
```

At the end of `_build_widgets`, with the other signal connections:

```python
        self.panel.active_changed.connect(self._on_active_changed)
        self.hub.changed.connect(self._on_annotation_changed)
```

In `_build_menus`, between the Candidate menu and the Help menu:

```python
        view_menu = bar.addMenu("&View")
        view_menu.addAction(self.notes_dock.toggleViewAction())
```

In `__init__`, after the geometry block:

```python
        state = self.settings.value("window/state")
        if state is not None:
            self.restoreState(state)
```

In `closeEvent`, after the geometry line: `self.settings.setValue("window/state", self.saveState())`.

Add near `_on_current_slot`:

```python
    def _on_active_changed(self, cid) -> None:
        slot = self._slot()
        candidate = slot.candidate(cid) if slot is not None and cid else None
        self.notes_editor.set_path(candidate.path if candidate is not None else None)
```

Change `_escape` to:

```python
    def _escape(self) -> None:
        self.notes_editor.escape()
        self.tree.view.setFocus()
```

In the library annotations section:

```python
    def _on_annotation_changed(self, rel: str) -> None:
        if self.notes_editor.path == rel:
            self.notes_editor.refresh()

    def _on_annotations_reloaded(self) -> None:
        self._report_annotations_load()
        self.notes_editor.set_store(self.hub.store)
        self._on_active_changed(self.panel.active_candidate_id())
```

(This replaces the one-line `_on_annotations_reloaded` from Task 9.)

Construction order: `_build_widgets` reads `self.hub`, which Task 9 created before `_build_widgets()` runs; `restoreState` runs after `_build_widgets`, so the dock exists when the state is applied.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format audio_picker tests
git add audio_picker/ui/main_window.py tests/test_ui_smoke.py
git commit -m "Add the Library notes dock that follows the active candidate

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Editor in the Add Candidate dialog

**Files:**
- Modify: `audio_picker/ui/dialogs.py`
- Modify: `audio_picker/ui/main_window.py` (`_add_candidate`)
- Modify: `tests/test_ui_smoke.py` (`FakeDialogs.add_candidate` signature)
- Modify: `tests/test_screenshots.py` (dialog constructor)
- Create: `tests/test_add_candidate_dialog.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_add_candidate_dialog.py`:

```python
"""Add Candidate dialog hosts the annotation editor (spec section 5.2)."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from audio_picker.annotations import LibraryAnnotations
from audio_picker.library import AudioLibrary
from audio_picker.model import load
from audio_picker.ui.annotation_hub import AnnotationHub
from audio_picker.ui.dialogs import AddCandidateDialog
from tests.test_ui_smoke import FakePlayer

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "review.json"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    dst = tmp_path / "audio"
    shutil.copytree(FIXTURE_ROOT, dst)
    return dst


@pytest.fixture
def dialog(qtbot, root):
    store = LibraryAnnotations(root)
    store.add_tag("packB/hit.mp3", "hit")
    d = AddCandidateDialog(load(EXAMPLE), AudioLibrary(root), root, FakePlayer(), AnnotationHub(store))
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    return d


def test_editor_follows_the_highlighted_result(dialog):
    assert dialog.editor.path is None
    dialog.results.setCurrentRow(3)  # packB/hit.mp3
    assert dialog.editor.path == "packB/hit.mp3"
    assert dialog.editor.chip_tags() == ["hit"]
    assert dialog.width() >= 900
    assert "even if you cancel" in dialog.notes_hint.text()


def test_hash_search_uses_the_store(dialog):
    dialog.search.setText("#hit")
    assert [dialog.results.item(i).text() for i in range(dialog.results.count())] == ["packB/hit.mp3"]


def test_edit_notifies_the_hub_and_autosaves_while_open(qtbot, dialog, root):
    dialog.results.setCurrentRow(1)  # packA/click.wav
    with qtbot.waitSignal(dialog.hub.changed) as blocker:
        dialog.editor.stars[1].click()
    assert blocker.args == ["packA/click.wav"]
    qtbot.waitUntil(lambda: LibraryAnnotations(root).get("packA/click.wav").rating == 2, timeout=3000)
    assert dialog.isVisible()


def test_enter_in_the_tag_field_adds_a_tag_and_does_not_accept_the_dialog(qtbot, dialog):
    dialog.results.setCurrentRow(1)
    dialog.editor.tag_input.setFocus()
    qtbot.keyClicks(dialog.editor.tag_input, "dry")
    qtbot.keyClick(dialog.editor.tag_input, Qt.Key.Key_Return)
    assert dialog.hub.store.has_tag("packA/click.wav", "dry")
    assert dialog.isVisible()
    assert dialog.result() != dialog.DialogCode.Accepted


def test_escape_in_the_tag_field_does_not_close_the_dialog(qtbot, dialog):
    dialog.results.setCurrentRow(1)
    dialog.editor.tag_input.setFocus()
    qtbot.keyClicks(dialog.editor.tag_input, "x")
    qtbot.keyClick(dialog.editor.tag_input, Qt.Key.Key_Escape)
    assert dialog.isVisible()
    assert dialog.editor.tag_input.text() == ""
    assert dialog.search.hasFocus()
```

Update `tests/test_ui_smoke.py`: change the fake's method to

```python
    def add_candidate(self, parent, review, library, root, player, hub):
        self.calls.append(("add_candidate",))
        return None
```

and add this test at the end of the dock section:

```python
def test_add_candidate_edits_autosave_while_open_even_when_cancelled(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)

    def fake_add(parent, review, library, root, player, hub):
        hub.store.add_tag("packA/confirm.ogg", "warm")
        hub.notify_changed("packA/confirm.ogg")
        qtbot.waitUntil(lambda: LibraryAnnotations(tmp_root).has_tag("packA/confirm.ogg", "warm"), timeout=3000)
        return None  # cancelled

    w.dialogs.add_candidate = fake_add
    w.actions["add_candidate"].trigger()
    assert [c.id for c in w.review.slot("ui_click").candidates] == ["A001", "A002"]
    assert w.hub.store.has_tag("packA/confirm.ogg", "warm")
```

Update `tests/test_screenshots.py` in `test_dialog_screenshots`: the dialog constructor becomes

```python
    add = AddCandidateDialog(
        review, AudioLibrary(FIXTURE_ROOT), FIXTURE_ROOT, FakePlayer(), AnnotationHub(LibraryAnnotations(FIXTURE_ROOT))
    )
```

with `from audio_picker.annotations import LibraryAnnotations` and `from audio_picker.ui.annotation_hub import AnnotationHub` added to the imports. No sidecar exists in the fixture root and screenshots never edit, so nothing is written there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_add_candidate_dialog.py -q`
Expected: FAIL with a `TypeError` about the number of positional arguments.

- [ ] **Step 3: Implement**

In `audio_picker/ui/dialogs.py`:

Add imports: `from .annotation_editor import AnnotationEditor`, `from .annotation_hub import AnnotationHub`, and `dim_css` to the `.theme` import.

Replace `AddCandidateDialog.__init__` so the dialog is a horizontal split with the buttons under both columns:

```python
class AddCandidateDialog(QDialog):
    def __init__(
        self,
        review: Review,
        library: AudioLibrary,
        root: Path,
        player,
        hub: AnnotationHub,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add candidate")
        self.resize(920, 480)
        self._review = review
        self._library = library
        self._root = root
        self._player = player
        self.hub = hub
        self._chosen: str | None = None

        outer = QVBoxLayout(self)
        columns = QHBoxLayout()
        outer.addLayout(columns, 1)
        left = QWidget()
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        columns.addWidget(left, 1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the audio library (every word must match; #tag matches a tag)")
        self.search.textChanged.connect(self._refresh_results)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.setItemDelegate(PathDelegate(self.results))
        self.results.currentItemChanged.connect(self._on_current_result)
        self.results.itemDoubleClicked.connect(lambda _i: self._preview())
        layout.addWidget(self.results, 1)

        row = QHBoxLayout()
        self.preview = QPushButton("Preview")
        self.preview.setEnabled(False)
        self.preview.clicked.connect(self._preview)
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self._browse)
        self.chosen_label = QLabel("No file chosen")
        self.chosen_label.setWordWrap(True)
        row.addWidget(self.preview)
        row.addWidget(self.browse)
        row.addWidget(self.chosen_label, 1)
        layout.addLayout(row)

        form = QFormLayout()
        self.role = QComboBox()
        self.role.addItems(ROLES)
        self.role.setCurrentText("alternative")
        self.why = QLineEdit()
        self.why.setPlaceholderText("Why is this file a candidate?")
        form.addRow("Role", self.role)
        form.addRow("Why", self.why)
        layout.addLayout(form)

        right = QWidget()
        right.setFixedWidth(280)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.editor = AnnotationEditor(hub.store)
        self.editor.changed.connect(hub.notify_changed)
        self.editor.escape_pressed.connect(self.search.setFocus)
        self.notes_hint = QLabel("Notes are saved to the library even if you cancel.")
        self.notes_hint.setWordWrap(True)
        self.notes_hint.setStyleSheet(dim_css())
        self.notes_hint.setContentsMargins(8, 0, 8, 4)
        right_layout.addWidget(self.editor, 1)
        right_layout.addWidget(self.notes_hint)
        columns.addWidget(right)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        outer.addWidget(self.buttons)

        self._refresh_results("")
        self.search.setFocus()
```

Change `_refresh_results` to `for rel in self._library.search(query, annotations=self.hub.store):`.

Change `_set_chosen` to also drive the editor:

```python
    def _set_chosen(self, rel: str | None, note: str = "") -> None:
        self._chosen = rel
        self.chosen_label.setText(rel or note or "No file chosen")
        self.preview.setEnabled(rel is not None)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(rel is not None)
        self.editor.set_path(rel)
```

Change `Dialogs.add_candidate`:

```python
    def add_candidate(
        self, parent, review: Review, library: AudioLibrary, root: Path, player, hub: AnnotationHub
    ) -> AddCandidateResult | None:
        dialog = AddCandidateDialog(review, library, root, player, hub, parent)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return dialog.result_value() if accepted else None
        finally:
            player.stop()  # a preview never outlives the dialog
```

Enter in the tag field is consumed by the editor's event filter (Task 6), so the dialog's default OK button never fires from it; the `why` and `search` fields keep their existing Enter behaviour. The hub's timer runs during `exec()` because the dialog's modal loop still processes events, so edits save while the dialog is open.

In `audio_picker/ui/main_window.py` `_add_candidate`, change the dialog call to:

```python
        result = self.dialogs.add_candidate(self, self.review, self.library, self.root, self.player, self.hub)
```

Nothing else changes there: the dock already refreshes through `hub.changed`.

- [ ] **Step 4: Run the suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format audio_picker tests
git add audio_picker/ui/dialogs.py audio_picker/ui/main_window.py tests/test_add_candidate_dialog.py tests/test_ui_smoke.py tests/test_screenshots.py
git commit -m "Add Candidate dialog hosts the annotation editor and saves as you go

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 12: `LibraryWindow` standalone viewer

**Files:**
- Create: `audio_picker/ui/library_window.py`
- Create: `tests/test_library_window.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_library_window.py`:

```python
"""Standalone library viewer (spec section 5.3)."""

import json
import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from audio_picker.annotations import SIDECAR_NAME, LibraryAnnotations
from audio_picker.library import AudioLibrary
from audio_picker.player import PlayerState
from audio_picker.ui.annotation_hub import AnnotationHub
from audio_picker.ui.library_window import LibraryWindow
from audio_picker.ui.path_delegate import SUMMARY_ROLE
from tests.test_ui_smoke import FakeDialogs, FakePlayer

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"
ALL_FILES = ["loose/miss.wav", "packA/click.wav", "packA/confirm.ogg", "packB/hit.mp3"]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    dst = tmp_path / "audio"
    shutil.copytree(FIXTURE_ROOT, dst)
    store = LibraryAnnotations(dst)
    store.add_tag("packA/click.wav", "ui")
    store.set_rating("packA/click.wav", 4)
    store.add_tag("packB/hit.mp3", "hit")
    store.set_rating("packB/hit.mp3", 2)
    store.add_tag("packZ/gone.wav", "orphan")
    store.save()
    return dst


@pytest.fixture
def make_lw(qtbot, tmp_path, root):
    def _make(*, owns_hub: bool = True, player=None, hub=None) -> LibraryWindow:
        settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
        w = LibraryWindow(
            root,
            AudioLibrary(root),
            hub or AnnotationHub(LibraryAnnotations(root)),
            player or FakePlayer(),
            settings,
            owns_hub=owns_hub,
            owns_player=owns_hub,
            dialogs=FakeDialogs(),
        )
        qtbot.addWidget(w)
        w.show()
        qtbot.waitExposed(w)
        w.activateWindow()
        qtbot.waitActive(w)
        return w

    return _make


@pytest.fixture
def lw(make_lw) -> LibraryWindow:
    return make_lw()


def rows(w: LibraryWindow) -> list[str]:
    return [w.list.item(i).text() for i in range(w.list.count())]


def tag_choices(w: LibraryWindow) -> list[str]:
    return [w.tag_filter.itemText(i) for i in range(w.tag_filter.count())]


def press(qtbot, w, key, modifier=Qt.KeyboardModifier.NoModifier) -> None:
    qtbot.keyClick(QApplication.focusWidget() or w, key, modifier)


# -- listing and filters ---------------------------------------------------------------


def test_lists_every_file_then_orphans_greyed(lw):
    assert rows(lw) == ALL_FILES + ["packZ/gone.wav"]
    orphan = lw.list.item(4)
    assert "Missing on disk" in orphan.toolTip()
    assert lw.is_orphan(orphan)
    assert lw.list.item(1).data(SUMMARY_ROLE) == "★4 ui"
    assert lw.list.item(2).data(SUMMARY_ROLE) == ""
    assert lw.windowTitle().endswith("Audio Picker")


def test_search_hides_orphans_and_hash_terms_work(lw):
    lw.search.setText("pack")
    assert rows(lw) == ["packA/click.wav", "packA/confirm.ogg", "packB/hit.mp3"]
    lw.search.setText("#ui")
    assert rows(lw) == ["packA/click.wav"]
    lw.search.setText("")
    assert len(rows(lw)) == 5


def test_tag_and_rating_filters_combine(lw):
    assert tag_choices(lw) == ["Any tag", "hit", "orphan", "ui"]
    lw.tag_filter.setCurrentText("hit")
    assert rows(lw) == ["packB/hit.mp3"]
    lw.tag_filter.setCurrentText("Any tag")
    lw.rating_filter.setCurrentText("3+")
    assert rows(lw) == ["packA/click.wav"]
    lw.rating_filter.setCurrentText("1+")
    lw.tag_filter.setCurrentText("ui")
    assert rows(lw) == ["packA/click.wav"]


# -- editing and synchronisation ----------------------------------------------------------


def test_current_row_drives_the_editor_and_edits_update_the_row(qtbot, lw):
    lw.list.setCurrentRow(2)  # packA/confirm.ogg
    assert lw.editor.path == "packA/confirm.ogg"
    lw.editor.stars[2].click()
    assert lw.list.item(2).data(SUMMARY_ROLE) == "★3"
    qtbot.keyClicks(lw.editor.tag_input, "warm")
    qtbot.keyClick(lw.editor.tag_input, Qt.Key.Key_Return)
    assert lw.list.item(2).data(SUMMARY_ROLE) == "★3 warm"
    assert tag_choices(lw) == ["Any tag", "hit", "orphan", "ui", "warm"]
    assert lw.editor.path == "packA/confirm.ogg", "repainting a row keeps the current one"


def test_removing_the_filtered_tag_drops_the_row(lw):
    lw.tag_filter.setCurrentText("ui")
    assert rows(lw) == ["packA/click.wav"]
    assert lw.editor.path == "packA/click.wav"
    lw.editor.chips[0].remove.click()
    assert rows(lw) == []
    assert lw.editor.path is None


def test_lowering_the_rating_below_the_threshold_drops_the_row(lw):
    lw.rating_filter.setCurrentText("3+")
    assert rows(lw) == ["packA/click.wav"]
    lw.editor.stars[1].click()  # rating 2
    assert rows(lw) == []


def test_clearing_an_orphan_removes_it(lw):
    lw.list.setCurrentRow(4)
    lw.editor.chips[0].remove.click()
    assert rows(lw) == ALL_FILES


def test_change_from_another_host_updates_row_and_editor(lw):
    lw.list.setCurrentRow(2)
    lw.hub.store.set_rating("packA/confirm.ogg", 5)
    lw.hub.notify_changed("packA/confirm.ogg")
    assert lw.list.item(2).data(SUMMARY_ROLE) == "★5"
    assert [s.text() for s in lw.editor.stars] == ["★"] * 5


def test_reloaded_rebuilds_from_the_store_and_library(lw, root):
    (root / "packA" / "new.wav").write_bytes(b"")
    good = {"version": 1, "tags": [], "files": {"packA/new.wav": {"rating": 1}}}
    (root / SIDECAR_NAME).write_text(json.dumps(good), encoding="utf-8")
    lw.library.refresh()
    lw.hub.reload()
    assert "packA/new.wav" in rows(lw)
    assert lw.list.item(rows(lw).index("packA/new.wav")).data(SUMMARY_ROLE) == "★1"
    assert tag_choices(lw) == ["Any tag"]


def test_rescan_action_refreshes_library_and_notes(lw, root):
    (root / "packA" / "new.wav").write_bytes(b"")
    lw.actions["rescan"].trigger()
    assert "packA/new.wav" in rows(lw)
    assert "reloaded" in lw.statusBar().currentMessage()


# -- playback -------------------------------------------------------------------------------


def test_double_click_and_space_play_pause_and_stop(qtbot, lw):
    lw.list.setCurrentRow(1)
    lw.list.itemDoubleClicked.emit(lw.list.item(1))
    assert lw.player.calls[-1] == ("play", lw.root / "packA" / "click.wav")
    assert "click.wav" in lw.transport.now_playing.text()
    lw.list.setFocus()
    press(qtbot, lw, Qt.Key.Key_Space)
    assert lw.player.calls[-1] == ("pause",)
    press(qtbot, lw, Qt.Key.Key_Space)
    assert lw.player.calls[-1] == ("resume",)
    press(qtbot, lw, Qt.Key.Key_S)
    assert lw.player.calls[-1] == ("stop",)
    assert lw.transport.now_playing.text() == "Nothing playing"


def test_space_on_an_orphan_does_not_play(qtbot, lw):
    lw.list.setCurrentRow(4)
    lw.list.setFocus()
    press(qtbot, lw, Qt.Key.Key_Space)
    assert not any(c[0] == "play" for c in lw.player.calls)


def test_space_in_a_text_field_types_instead_of_playing(qtbot, lw):
    lw.list.setCurrentRow(1)
    lw.editor.note.setFocus()
    qtbot.keyClicks(lw.editor.note, "a b")
    assert not any(c[0] == "play" for c in lw.player.calls)
    assert lw.hub.store.get("packA/click.wav").note == "a b"


def test_escape_returns_focus_to_the_list(qtbot, lw):
    lw.list.setCurrentRow(1)
    lw.editor.tag_input.setFocus()
    qtbot.keyClicks(lw.editor.tag_input, "zz")
    qtbot.keyClick(lw.editor.tag_input, Qt.Key.Key_Escape)
    assert lw.editor.tag_input.text() == ""
    assert lw.list.hasFocus()


def test_play_requested_is_emitted_before_playing(qtbot, lw):
    lw.list.setCurrentRow(1)
    with qtbot.waitSignal(lw.play_requested):
        lw.list.itemDoubleClicked.emit(lw.list.item(1))


def test_someone_else_playing_clears_now_playing(lw):
    lw.list.setCurrentRow(1)
    lw.list.itemDoubleClicked.emit(lw.list.item(1))
    lw.player.play(lw.root / "packB" / "hit.mp3")  # as if the review window played
    assert lw.transport.now_playing.text() == "Nothing playing"


def test_stopped_state_from_the_player_clears_now_playing(lw):
    lw.list.setCurrentRow(1)
    lw.list.itemDoubleClicked.emit(lw.list.item(1))
    lw.player._set(PlayerState.STOPPED)
    assert lw.transport.now_playing.text() == "Nothing playing"


# -- persistence and ownership ----------------------------------------------------------------


def test_owned_hub_autosaves_and_flushes_on_close(qtbot, lw, root):
    lw.list.setCurrentRow(2)
    lw.editor.stars[0].click()
    qtbot.waitUntil(lambda: LibraryAnnotations(root).get("packA/confirm.ogg").rating == 1, timeout=3000)
    lw.editor.note.setFocus()
    qtbot.keyClicks(lw.editor.note, "bye")
    assert lw.close()
    assert LibraryAnnotations(root).get("packA/confirm.ogg").note == "bye"
    assert lw.player.calls[-1] == ("stop",)
    assert lw.settings.value("library_window/geometry") is not None


def test_owned_hub_save_failure_reports_then_close_asks(qtbot, lw, root):
    lw.list.setCurrentRow(2)
    (root / SIDECAR_NAME).unlink()
    (root / SIDECAR_NAME).mkdir()
    lw.editor.stars[0].click()
    qtbot.waitUntil(lambda: any(c[0] == "error" for c in lw.dialogs.calls), timeout=3000)
    assert lw.hub.store.dirty
    lw.dialogs.unsaved_answer = "cancel"
    assert not lw.close()
    assert ("unsaved", "close", (SIDECAR_NAME,)) in lw.dialogs.calls
    lw.dialogs.unsaved_answer = "discard"
    assert lw.close()


def test_unowned_hub_neither_reports_nor_stops_the_player(qtbot, make_lw, root):
    hub = AnnotationHub(LibraryAnnotations(root))
    w = make_lw(owns_hub=False, hub=hub)
    (root / SIDECAR_NAME).unlink()
    (root / SIDECAR_NAME).mkdir()
    w.list.setCurrentRow(2)
    with qtbot.waitSignal(hub.save_failed):
        w.editor.stars[0].click()
    assert not any(c[0] in ("error", "unsaved") for c in w.dialogs.calls)
    assert w.close()
    assert not any(c == ("stop",) for c in w.player.calls)


def test_owned_hub_with_malformed_sidecar_reports_and_disables_editing(make_lw, root):
    (root / SIDECAR_NAME).write_text('{"version": 9}', encoding="utf-8")
    w = make_lw()
    assert sum(1 for c in w.dialogs.calls if c[0] == "error" and "version" in c[1]) == 1
    assert w.warning.isVisible() and "rescan" in w.warning.text().lower()
    w.list.setCurrentRow(1)
    assert not w.editor.note.isEnabled()
    (root / SIDECAR_NAME).write_text('{"version": 1, "tags": [], "files": {}}', encoding="utf-8")
    w.actions["rescan"].trigger()
    assert w.editor.note.isEnabled()
    assert not w.warning.isVisible()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_library_window.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_picker.ui.library_window'`

- [ ] **Step 3: Implement**

Create `audio_picker/ui/library_window.py`:

```python
"""Standalone library viewer: search, filters, annotation editor, transport (spec section 5.3).

Opened from the CLI (`audio-picker library --root DIR`, owning its hub and
player) or from the review window (sharing both). Single keys follow the
review window's rule: quiet while a text field has focus.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..annotations import LibraryAnnotations
from ..library import AudioLibrary
from ..paths import to_absolute
from ..player import PlayerState
from .annotation_editor import AnnotationEditor
from .annotation_hub import AnnotationHub
from .dialogs import Dialogs
from .keys import text_field_focused
from .path_delegate import PATH_ROLE, SUMMARY_ROLE, PathDelegate
from .theme import dim_color, error_css
from .transport_bar import TransportBar

ORPHAN_ROLE = Qt.ItemDataRole.UserRole + 2
ANY_TAG = "Any tag"
RATING_CHOICES = [("Any rating", 0), ("1+", 1), ("2+", 2), ("3+", 3), ("4+", 4), ("5", 5)]


def summary_for(annotations: LibraryAnnotations, rel: str) -> str:
    a = annotations.get(rel)
    parts = [f"★{a.rating}"] if a.rating is not None else []
    return " ".join(parts + a.tags)


class LibraryWindow(QMainWindow):
    play_requested = Signal()  # emitted just before this window starts playback

    def __init__(
        self,
        root: Path,
        library: AudioLibrary,
        hub: AnnotationHub,
        player,
        settings: QSettings,
        *,
        owns_hub: bool,
        owns_player: bool = False,
        dialogs=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.root = Path(root)
        self.library = library
        self.hub = hub
        self.player = player
        self.settings = settings
        self.owns_hub = owns_hub
        self.owns_player = owns_player
        self.dialogs = dialogs or Dialogs()
        self._playing_rel: str | None = None
        self._refreshing = False
        self._listed: list[tuple[str, bool]] = []

        self._build_widgets()
        self._build_actions()
        self._connect_player()
        self.hub.changed.connect(self._on_hub_changed)
        self.hub.reloaded.connect(self._on_hub_reloaded)
        if owns_hub:
            self.hub.save_failed.connect(lambda message: self.dialogs.error(self, "Save failed", message))

        self.setWindowTitle(f"Library — {self.root.name} — Audio Picker")
        self.setMinimumSize(760, 480)
        geometry = self.settings.value("library_window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1000, 640)
        self._report_load()
        self.refresh_list()
        self.list.setFocus()

    @property
    def annotations(self) -> LibraryAnnotations:
        return self.hub.store

    # -- construction ----------------------------------------------------------------

    def _build_widgets(self) -> None:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 4, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search paths, #tag for tags")
        self.search.setClearButtonEnabled(True)
        left_layout.addWidget(self.search)

        filters = QHBoxLayout()
        self.tag_filter = QComboBox()
        self.tag_filter.setToolTip("Only files carrying this tag")
        self.rating_filter = QComboBox()
        self.rating_filter.setToolTip("Only files rated at least this")
        for text, value in RATING_CHOICES:
            self.rating_filter.addItem(text, value)
        filters.addWidget(self.tag_filter, 1)
        filters.addWidget(self.rating_filter)
        left_layout.addLayout(filters)

        self.list = QListWidget()
        self.list.setItemDelegate(PathDelegate(self.list))
        self.list.currentItemChanged.connect(self._on_current_item)
        self.list.itemDoubleClicked.connect(lambda _i: self._play_current(restart=True))
        left_layout.addWidget(self.list, 1)
        self.count_label = QLabel()
        left_layout.addWidget(self.count_label)

        self.editor = AnnotationEditor(self.hub.store)
        self.editor.setMinimumWidth(260)
        self.editor.changed.connect(self.hub.notify_changed)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.editor)
        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([700, 300])

        self.transport = TransportBar(self.player, self.settings)
        self.transport.play_pause_clicked.connect(self._space)
        self.transport.stop_clicked.connect(self.player.stop)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.transport)
        self.setCentralWidget(central)

        self.warning = QLabel()
        self.warning.setStyleSheet(error_css())
        self.warning.hide()
        self.statusBar().addPermanentWidget(self.warning)

        self._refresh_tag_filter()
        self.search.textChanged.connect(lambda _t: self.refresh_list())
        self.tag_filter.currentIndexChanged.connect(lambda _i: self.refresh_list())
        self.rating_filter.currentIndexChanged.connect(lambda _i: self.refresh_list())

    def _action(self, key: str, text: str, shortcut: str, handler: Callable[[], None], *, single_key: bool) -> None:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if single_key:
            action.triggered.connect(lambda: None if text_field_focused() else handler())
        else:
            action.triggered.connect(lambda: handler())
        self.addAction(action)
        self.actions[key] = action

    def _build_actions(self) -> None:
        self.actions: dict[str, QAction] = {}
        self._action("space", "Play / pause", "Space", self._space, single_key=True)
        self._action("stop", "Stop", "S", self.player.stop, single_key=True)
        self._action("loop", "Toggle loop", "L", self.transport.loop.toggle, single_key=True)
        self._action("search", "Find", "Ctrl+F", self._focus_search, single_key=False)
        self._action("save", "Save now", "Ctrl+S", self.flush, single_key=False)
        self._action("rescan", "Rescan library", "F5", self._rescan, single_key=False)
        self._action("close", "Close", "Ctrl+W", self.close, single_key=False)
        escape = QShortcut(QKeySequence("Escape"), self)
        escape.setContext(Qt.ShortcutContext.WindowShortcut)
        escape.activated.connect(self._escape)

    def _connect_player(self) -> None:
        self.player.state_changed.connect(self._on_player_state)
        self.player.source_changed.connect(lambda _source: self._check_source())
        self.player.error.connect(lambda text: self.statusBar().showMessage(f"Playback error: {text}"))

    # -- rows --------------------------------------------------------------------------------

    def _filters_active(self) -> bool:
        return (
            bool(self.search.text().strip())
            or self.tag_filter.currentIndex() > 0
            or int(self.rating_filter.currentData() or 0) > 0
        )

    def _rows(self) -> list[tuple[str, bool]]:
        """(relative path, is_orphan) for everything the current search and filters admit."""
        store = self.hub.store
        hits = self.library.search(self.search.text(), limit=max(1, len(self.library)), annotations=store)
        tag = self.tag_filter.currentText() if self.tag_filter.currentIndex() > 0 else None
        min_rating = int(self.rating_filter.currentData() or 0)
        if tag is not None:
            hits = [p for p in hits if store.has_tag(p, tag)]
        if min_rating:
            hits = [p for p in hits if (store.get(p).rating or 0) >= min_rating]
        rows = [(p, False) for p in hits]
        if not self._filters_active():
            known = set(self.library.paths)
            rows += [(p, True) for p in store.annotated() if p not in known]
        return rows

    def refresh_list(self) -> None:
        """Rebuild the rows, keeping the current path selected where it still exists."""
        self._refreshing = True
        try:
            current = self.current_path()
            self._listed = self._rows()
            self.list.clear()
            for rel, orphan in self._listed:
                self.list.addItem(self._item(rel, orphan))
            files = sum(1 for _rel, orphan in self._listed if not orphan)
            orphans = len(self._listed) - files
            text = f"{files} file{'s' if files != 1 else ''}"
            if orphans:
                text += f", {orphans} annotated file{'s' if orphans != 1 else ''} missing on disk"
            self.count_label.setText(text)
            self._select_path(current)
        finally:
            self._refreshing = False
        self._on_current_item(self.list.currentItem(), None)

    def _item(self, rel: str, orphan: bool) -> QListWidgetItem:
        item = QListWidgetItem(rel)
        item.setData(PATH_ROLE, rel)
        item.setData(SUMMARY_ROLE, summary_for(self.hub.store, rel))
        item.setData(ORPHAN_ROLE, orphan)
        if orphan:
            item.setForeground(dim_color())
            item.setToolTip("Missing on disk: annotated, but no such file under the root")
        return item

    @staticmethod
    def is_orphan(item: QListWidgetItem | None) -> bool:
        return bool(item is not None and item.data(ORPHAN_ROLE))

    def current_path(self) -> str | None:
        item = self.list.currentItem()
        return item.data(PATH_ROLE) if item is not None else None

    def _row_for(self, rel: str) -> QListWidgetItem | None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(PATH_ROLE) == rel:
                return item
        return None

    def _select_path(self, rel: str | None) -> None:
        item = self._row_for(rel) if rel is not None else None
        if item is not None:
            self.list.setCurrentItem(item)
        elif self.list.count():
            self.list.setCurrentRow(0)

    def _refresh_tag_filter(self) -> None:
        wanted = [ANY_TAG] + self.hub.store.vocabulary()
        have = [self.tag_filter.itemText(i) for i in range(self.tag_filter.count())]
        if wanted == have:
            return
        keep = self.tag_filter.currentText()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItems(wanted)
        self.tag_filter.setCurrentText(keep if keep in wanted else ANY_TAG)
        self.tag_filter.blockSignals(False)

    def _on_current_item(self, current: QListWidgetItem | None, _previous) -> None:
        if self._refreshing:
            return
        self.editor.set_path(current.data(PATH_ROLE) if current is not None else None)

    # -- hub -----------------------------------------------------------------------------------

    def _on_hub_changed(self, rel: str) -> None:
        """Any host edited `rel`: re-apply the filters, or just repaint the row when nothing moved."""
        if self._rows() != self._listed:
            self.refresh_list()
        else:
            item = self._row_for(rel)
            if item is not None:
                item.setData(SUMMARY_ROLE, summary_for(self.hub.store, rel))
        self._refresh_tag_filter()
        if self.editor.path == rel:
            self.editor.refresh()

    def _on_hub_reloaded(self) -> None:
        self.editor.set_store(self.hub.store)
        self._report_load()
        self._refresh_tag_filter()
        self.refresh_list()

    def _rescan(self) -> None:
        self.library.refresh()
        notes = self.hub.reload()
        self.statusBar().showMessage(f"Library rescanned: {len(self.library)} audio files; {notes}.")

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _escape(self) -> None:
        self.editor.escape()
        self.list.setFocus()

    # -- playback ---------------------------------------------------------------------------

    def _play_current(self, *, restart: bool = False) -> None:
        item = self.list.currentItem()
        if item is None or self.is_orphan(item):
            return
        rel = item.data(PATH_ROLE)
        if not restart and self._playing_rel == rel and self.player.state is not PlayerState.STOPPED:
            self.player.stop()
            return
        self.play_requested.emit()
        self._playing_rel = rel
        self.player.play(to_absolute(self.root, rel))
        self.transport.set_now_playing(AudioLibrary.pack_folder(rel) or "library", rel.rsplit("/", 1)[-1])

    def _space(self) -> None:
        state = self.player.state
        if state is PlayerState.PLAYING:
            self.player.pause()
        elif state is PlayerState.PAUSED:
            self.player.resume()
        else:
            self._play_current()

    def _on_player_state(self, state: PlayerState) -> None:
        if state is PlayerState.STOPPED:
            self._playing_rel = None
            self.transport.set_now_playing(None, None)
        else:
            self._check_source()

    def _check_source(self) -> None:
        """Forget our now-playing when the shared player is playing someone else's file."""
        if self._playing_rel is not None and self.player.source != to_absolute(self.root, self._playing_rel):
            self._playing_rel = None  # the review window took the player
            self.transport.set_now_playing(None, None)

    # -- persistence -------------------------------------------------------------------------

    def _report_load(self) -> None:
        store = self.hub.store
        if self.owns_hub and store.load_error:
            self.dialogs.error(self, "Library notes not loaded", store.load_error)
        self.warning.setText(
            f"Library notes not loaded: fix {store.path.name} and rescan (F5)" if store.read_only else ""
        )
        self.warning.setVisible(store.read_only)

    def flush(self) -> bool:
        if not self.owns_hub:
            return True
        ok = self.hub.flush()
        if ok and not self.hub.store.dirty:
            self.statusBar().showMessage(f"Saved {datetime.now().strftime('%H:%M:%S')}")
        return ok

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        if self.owns_hub:
            while not self.hub.flush():
                answer = self.dialogs.unsaved(self, "close", [self.hub.store.path.name])
                if answer == "discard":
                    break
                if answer != "retry":
                    event.ignore()
                    return
        if self.owns_player:
            self.player.stop()
        self.settings.setValue("library_window/geometry", self.saveGeometry())
        event.accept()
```

Notes for the implementer:
- `test_someone_else_playing_clears_now_playing` relies on `source_changed`, not `state_changed`: the fake player is already PLAYING when the second `play` happens, so no state signal fires.
- The filter signals are connected at the end of `_build_widgets`, after `_refresh_tag_filter` has populated the combo, so construction never triggers `refresh_list` before `self.list` exists.
- `FakeDialogs.unsaved_answer` defaults to `"discard"`, which is what the owned-hub close tests rely on until they set it.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_library_window.py -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format audio_picker tests
git add audio_picker/ui/library_window.py tests/test_library_window.py
git commit -m "Add the standalone library viewer window

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 13: Launch the viewer from the review window

**Files:**
- Modify: `audio_picker/ui/main_window.py`
- Modify: `tests/test_ui_smoke.py`

- [ ] **Step 1: Write the failing tests**

Add `from audio_picker.ui.path_delegate import SUMMARY_ROLE` to the imports of `tests/test_ui_smoke.py`, then append:

```python
# -- library viewer from the review window --------------------------------------------


def test_library_viewer_opens_once_shares_hub_and_player_and_stops_review_playback(qtbot, win):
    press(qtbot, win, Qt.Key.Key_1)
    n = len(win.player.calls)
    win.actions["library"].trigger()
    lw = win.library_window
    assert lw.isVisible()
    assert lw.player is win.player
    assert lw.hub is win.hub
    assert ("stop",) in win.player.calls[n:]  # the viewer's transport bar also logs set_loop after it
    assert not lw.owns_hub and not lw.owns_player
    win.actions["library"].trigger()
    assert win.library_window is lw
    assert [a.text() for a in win.menuBar().actions()[0].menu().actions() if a.text()][:5] == [
        "&Open…",
        "&Save now",
        "&Export manifest…",
        "&Rescan library",
        "&Library viewer…",
    ]


def test_viewer_playback_clears_the_review_highlight(qtbot, win):
    press(qtbot, win, Qt.Key.Key_1)
    win.actions["library"].trigger()
    lw = win.library_window
    press(qtbot, win, Qt.Key.Key_1)  # the review plays again while the viewer is open
    assert win.panel.rows[0].is_playing
    lw.list.setCurrentRow(3)
    lw.list.itemDoubleClicked.emit(lw.list.item(3))
    assert not win.panel.rows[0].is_playing
    assert win.transport.now_playing.text() == "Nothing playing"


def test_viewer_and_dock_stay_in_sync_through_the_hub(qtbot, make_win, tmp_root):
    w = make_win(tmp_root)
    w.notes_dock.show()
    w.actions["library"].trigger()
    lw = w.library_window
    lw.list.setCurrentRow(1)  # packA/click.wav, also the dock's file
    lw.editor.stars[3].click()
    assert [s.text() for s in w.notes_editor.stars] == ["★", "★", "★", "★", "☆"]
    qtbot.waitUntil(lambda: LibraryAnnotations(tmp_root).get("packA/click.wav").rating == 4, timeout=3000)
    w.notes_editor.stars[0].click()
    assert lw.list.item(1).data(SUMMARY_ROLE) == "★1"


def test_rescan_in_the_review_window_refreshes_an_open_viewer(make_win, tmp_root):
    w = make_win(tmp_root)
    w.actions["library"].trigger()
    lw = w.library_window
    (tmp_root / "packA" / "new.wav").write_bytes(b"")
    w.actions["rescan"].trigger()
    assert "packA/new.wav" in [lw.list.item(i).text() for i in range(lw.list.count())]


def test_open_other_review_closes_the_viewer(make_win, tmp_root, tmp_path):
    w = make_win(tmp_root)
    w.actions["library"].trigger()
    other_review, _other_root = _other_review(tmp_path)
    w.dialogs.open_target = other_review
    w.actions["open"].trigger()
    assert w.library_window is None


def test_quit_closes_the_viewer(make_win, tmp_root):
    w = make_win(tmp_root)
    w.actions["library"].trigger()
    lw = w.library_window
    assert w.close()
    assert not lw.isVisible()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ui_smoke.py -q -k viewer`
Expected: FAIL with `KeyError: 'library'`.

- [ ] **Step 3: Implement**

In `audio_picker/ui/main_window.py`:

Import: `from .library_window import LibraryWindow`.

In `__init__`, after `self._playing_cid: str | None = None`: `self.library_window: LibraryWindow | None = None`.

In `_build_actions`, after the `rescan` action: `self._action("library", "&Library viewer…", None, self._open_library_window)`.

In `_build_menus`, the File menu loop becomes `for key in ("open", "save", "export", "rescan", "library"):`.

Add methods in the library annotations section:

```python
    def _open_library_window(self) -> None:
        if self.library_window is not None:
            self.library_window.show()
            self.library_window.raise_()
            self.library_window.activateWindow()
            return
        self.player.stop()
        self._playing_cid = None
        lw = LibraryWindow(
            self.root,
            self.library,
            self.hub,
            self.player,
            self.settings,
            owns_hub=False,
            owns_player=False,
            dialogs=self.dialogs,
            parent=self,
        )
        lw.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        lw.destroyed.connect(lambda *_a: setattr(self, "library_window", None))
        lw.play_requested.connect(self._on_viewer_play)
        self.library_window = lw
        lw.show()

    def _close_library_window(self) -> None:
        if self.library_window is not None:
            lw = self.library_window
            self.library_window = None
            lw.close()

    def _on_viewer_play(self) -> None:
        self._playing_cid = None
        self.panel.set_playing(None)
        self.transport.set_now_playing(None, None)
```

A `QMainWindow` is a top-level window even with a parent, so the viewer floats beside the review window and closes with it.

In `_open_other`, right after the `settle_unsaved` check: `self._close_library_window()`.

In `closeEvent`, before `self.player.stop()`: `self._close_library_window()`.

Nothing connects the viewer's edits to the review window: both subscribe to the same hub, which Task 12 already wired on the viewer side and Task 10 on the dock side.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format audio_picker tests
git add audio_picker/ui/main_window.py tests/test_ui_smoke.py
git commit -m "Open the library viewer from the review window, sharing hub and player

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: CLI `library --root DIR` and `run_library`

**Files:**
- Modify: `audio_picker/cli.py`
- Modify: `audio_picker/ui/app.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -q -k library`
Expected: FAIL with `AttributeError: module 'audio_picker.cli' has no attribute '_launch_library'`.

- [ ] **Step 3: Implement**

In `audio_picker/cli.py`:

Docstring: add `    audio-picker library --root DIR                  # browse, rate and tag the library` after the `check` line.

`SUBCOMMANDS = ("gui", "import-csv", "export", "check", "library")`.

After `_launch_gui`:

```python
def _launch_library(root: Path) -> int:
    from .ui.app import run_library

    return run_library(root)
```

In `build_parser`, after the `check` parser:

```python
    lib = sub.add_parser("library", help="browse, rate and tag the audio library without a review file")
    lib.add_argument("--root", required=True, help="audio library directory")
```

Add a handler and register it:

```python
def _cmd_library(args: argparse.Namespace) -> int:
    root = resolve_root("", None, args.root)  # only the --root branch of resolve_root is used
    return _launch_library(root)
```

```python
_HANDLERS = {
    "gui": _cmd_gui,
    "check": _cmd_check,
    "export": _cmd_export,
    "import-csv": _cmd_import,
    "library": _cmd_library,
}
```

In `audio_picker/ui/app.py`, add:

```python
def run_library(root: Path) -> int:
    """Open the standalone library viewer owning its own hub and player."""
    ensure_media_backend()
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from ..annotations import LibraryAnnotations
    from ..library import AudioLibrary
    from .annotation_hub import AnnotationHub
    from .library_window import LibraryWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("audio-picker")
    app.setApplicationName("audio-picker")
    root = Path(root)
    window = LibraryWindow(
        root,
        AudioLibrary(root),
        AnnotationHub(LibraryAnnotations(root)),
        Player(),
        QSettings("audio-picker", "audio-picker"),
        owns_hub=True,
        owns_player=True,
    )
    window.show()
    return app.exec()
```

(`LibraryWindow._report_load` shows the malformed-sidecar dialog itself when it owns the hub.)

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -q`
Expected: all PASS. `test_library_bad_root_is_exit_1` passes because `resolve_root` raises `ReviewError`, which `main` maps to exit 1 with the message on stderr.

- [ ] **Step 5: Manual launch check**

Run: `.venv/Scripts/audio-picker library --root tests/fixtures/audio`
Expected: the viewer opens listing four files; double-click plays; F5 rescans; close it. Then run the review GUI on `examples/review.json`, open File, Library viewer, confirm it opens and closes, and that View, Library notes shows the dock. Delete `tests/fixtures/audio/audio-picker-library.json` if the manual session created one; `git status` must show nothing under `tests/fixtures/`.

- [ ] **Step 6: Lint and commit**

```bash
.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format audio_picker tests
git add audio_picker/cli.py audio_picker/ui/app.py tests/test_cli.py
git commit -m "Add the library subcommand that opens the standalone viewer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 15: Screenshots

**Files:**
- Modify: `tests/test_screenshots.py`

- [ ] **Step 1: Add the screenshot tests**

Add to the imports of `tests/test_screenshots.py` (the annotations and hub imports were added in Task 11):

```python
from audio_picker.ui.library_window import LibraryWindow
```

Extend `test_main_window_screenshots` by adding, before the `horn_distant` line:

```python
    window.notes_dock.show()
    window.notes_editor.tag_input.setFocus()
    _save(window, f"main_dock_{theme}")
    window.notes_dock.hide()
```

Add a new test:

```python
def test_library_window_screenshot(qtbot, tmp_path, theme):
    root = tmp_path / "audio"
    shutil.copytree(FIXTURE_ROOT, root)
    store = LibraryAnnotations(root)
    store.add_tag("packA/click.wav", "ui")
    store.add_tag("packA/click.wav", "click")
    store.set_rating("packA/click.wav", 4)
    store.set_note("packA/click.wav", "Clean and short. Pair with confirm for release.")
    store.add_tag("packZ/gone.wav", "orphan")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = LibraryWindow(
        root,
        AudioLibrary(root),
        AnnotationHub(store),
        FakePlayer(),
        settings,
        owns_hub=True,
        owns_player=True,
        dialogs=FakeDialogs(),
    )
    w.resize(1100, 640)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.list.setCurrentRow(1)
    _save(w, f"library_{theme}")
```

- [ ] **Step 2: Run the screenshot tests and look at the images**

Run: `.venv/Scripts/python -m pytest tests/test_screenshots.py -q`
Expected: PASS. Then open `screenshots/main_dock_light.png`, `screenshots/main_dock_dark.png`, `screenshots/dialog_add_candidate_light.png`, `screenshots/dialog_add_candidate_dark.png`, `screenshots/library_light.png` and `screenshots/library_dark.png` with the Read tool and check: stars visible and legible, chips readable in dark, the dimmed row summary readable in dark, the dock not squeezing the slot panel below usable width, the dialog's two columns and the hint line both visible at 920 px. Fix any contrast problem in `annotation_editor.py` styles (use `dim_css()` and palette roles, never fixed colours) and rerun.

- [ ] **Step 3: Commit**

```bash
git add tests/test_screenshots.py
git commit -m "Screenshot the notes dock, the widened dialog and the library viewer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 16: README and shortcuts dialog

**Files:**
- Modify: `README.md`
- Modify: `audio_picker/ui/dialogs.py` (`SHORTCUTS` list)

- [ ] **Step 1: Update the README**

In the Commands block add:

```
audio-picker library --root DIR                      # browse, rate and tag the library without a review
```

Add a new section before "Codec check":

```markdown
## Library notes

Any file in the library can carry a quality rating (1 to 5 stars, meaning
how clean the recording is, not whether you like it), a set of tags and a
note. They are stored in `audio-picker-library.json` in the audio root, so
they belong to the library, not to one review, and survive reuse of the same
packs in another project. The audio files and folders are never touched.

Three places edit the same data:

- **View, Library notes** in the review window shows a dock that follows the
  active candidate.
- The **Add candidate** dialog shows the same editor for the highlighted
  result, and `#tag` in its search box matches a tag. Notes made there are
  kept even if you cancel adding the candidate.
- **File, Library viewer** (or `audio-picker library --root DIR`) opens a
  standalone browser with a tag filter, a minimum-rating filter, `#tag`
  search, playback with Space and `S`, and `F5` to rescan. Annotated files
  that no longer exist on disk are listed greyed at the end.

Edits autosave after half a second and on `Ctrl+S`. Quitting or opening
another review first saves both the review and the library notes; if either
cannot be written you are asked to try again, discard, or cancel. If the
sidecar is malformed the app says so once, library notes become read-only,
and Rescan library retries the load. Rescan also reloads a hand-edited
sidecar when nothing is unsaved.
```

- [ ] **Step 2: Update the shortcuts dialog**

In `audio_picker/ui/dialogs.py` `SHORTCUTS`, change the Escape row to
`("Escape", "Leave a text field (clears a half-typed tag) and return to the slot tree")`.

- [ ] **Step 3: Run the whole suite one last time**

Run: `.venv/Scripts/ruff check audio_picker tests && .venv/Scripts/ruff format --check audio_picker tests && .venv/Scripts/python -m pytest -q`
Expected: all PASS, no lint output. Check `git status` shows no stray `audio-picker-library.json` under `tests/fixtures/audio/`.

- [ ] **Step 4: Commit**

```bash
git add README.md audio_picker/ui/dialogs.py
git commit -m "Document library notes and the library subcommand

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
