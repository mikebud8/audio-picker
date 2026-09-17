"""Library-wide annotations: rating, tags and note per audio file.

Stored in `<root>/audio-picker-library.json` (library annotations spec,
section 3). One store per audio root per process. Imports nothing from Qt.
"""

from __future__ import annotations

import json
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


def _key_is_canonical(key: str) -> bool:
    if "\\" in key:
        return False
    if key.strip() != key:
        return False
    parts = key.split("/")
    if any(p == "" for p in parts):
        return False
    return True


def from_dict(data: Any) -> tuple[dict[str, Annotation], set[str]]:
    """Validate parsed JSON. Returns (files, vocabulary)."""
    where = "annotations"
    if not isinstance(data, dict):
        raise AnnotationsError(f"{where}: expected an object, got {type(data).__name__}")
    if data.get("version") != ANNOTATIONS_VERSION:
        raise AnnotationsError(f"{where}: unsupported version {data.get('version')!r} (expected {ANNOTATIONS_VERSION})")
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
        if not _key_is_canonical(key):
            raise AnnotationsError(f"{fwhere}: key is not a canonical relative path")
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
