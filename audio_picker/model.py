"""Review file model (design section 5): dataclasses, validation, load/save.

Imports nothing from Qt so the data layer is testable without a display.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = 1
PRIORITIES = ("first_pass", "later", "optional")
ROLES = ("first", "alternative", "variation", "reference")
DECISIONS = ("unreviewed", "yay", "nay")
AUDIO_SUFFIXES = {".wav", ".ogg", ".mp3", ".flac"}

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CANDIDATE_ID_RE = re.compile(r"^[A-Z]+[0-9]+$")

Status = Literal["gap", "selected", "rejected", "unselected"]


class ReviewError(Exception):
    """A review file failed validation. The message names the offending item."""


# -- dataclasses --------------------------------------------------------------


@dataclass
class Pack:
    name: str
    folder: str
    license: str


@dataclass
class Candidate:
    id: str
    path: str
    pack: str | None
    role: str
    why: str
    listen_for: str
    proposed_use: str
    decision: str
    notes: str


@dataclass
class Slot:
    id: str
    category: str
    function: str
    priority: str
    notes: str
    selected: str | None
    candidates: list[Candidate] = field(default_factory=list)

    def status(self) -> Status:
        if not self.candidates:
            return "gap"
        if self.selected is not None:
            return "selected"
        if all(c.decision == "nay" for c in self.candidates):
            return "rejected"
        return "unselected"

    def candidate(self, cid: str) -> Candidate | None:
        for c in self.candidates:
            if c.id == cid:
                return c
        return None

    def _require(self, cid: str) -> Candidate:
        c = self.candidate(cid)
        if c is None:
            raise KeyError(f"no candidate {cid!r} in slot {self.id!r}")
        return c

    def set_decision(self, cid: str, decision: str) -> None:
        """Apply a decision; marking the selected candidate `nay` clears `selected`."""
        if decision not in DECISIONS:
            raise ValueError(f"unknown decision {decision!r}")
        c = self._require(cid)
        c.decision = decision
        if decision == "nay" and self.selected == cid:
            self.selected = None

    def select(self, cid: str) -> None:
        """Select a candidate; refuses `nay`, promotes `unreviewed` to `yay`."""
        c = self._require(cid)
        if c.decision == "nay":
            raise ValueError(f"candidate {cid!r} is marked nay; change the rating to select")
        if c.decision == "unreviewed":
            c.decision = "yay"
        self.selected = cid


@dataclass
class Review:
    version: int
    project: str
    root: str
    categories: list[str]
    packs: dict[str, Pack]
    slots: list[Slot]

    def slot(self, sid: str) -> Slot | None:
        for s in self.slots:
            if s.id == sid:
                return s
        return None

    def all_candidate_ids(self) -> set[str]:
        return {c.id for s in self.slots for c in s.candidates}

    def next_candidate_id(self, prefix: str = "A") -> str:
        return next_candidate_id_for(self.all_candidate_ids(), prefix)


def next_candidate_id_for(existing: set[str], prefix: str = "A") -> str:
    """`prefix` + (highest existing number for that prefix + 1), zero-padded to 3."""
    highest = 0
    for cid in existing:
        if cid.startswith(prefix) and cid[len(prefix) :].isdigit():
            highest = max(highest, int(cid[len(prefix) :]))
    return f"{prefix}{highest + 1:03d}"


# -- validation and conversion -------------------------------------------------

_PACK_KEYS = {"name": str, "folder": str, "license": str}
_CANDIDATE_KEYS = {
    "id": str,
    "path": str,
    "pack": (str, type(None)),
    "role": str,
    "why": str,
    "listen_for": str,
    "proposed_use": str,
    "decision": str,
    "notes": str,
}
_SLOT_KEYS = {
    "id": str,
    "category": str,
    "function": str,
    "priority": str,
    "notes": str,
    "selected": (str, type(None)),
    "candidates": list,
}
_TOP_KEYS = {
    "version": int,
    "project": str,
    "root": str,
    "categories": list,
    "packs": dict,
    "slots": list,
}


def _check_keys(obj: Any, keys: dict[str, Any], where: str) -> None:
    if not isinstance(obj, dict):
        raise ReviewError(f"{where}: expected an object, got {type(obj).__name__}")
    missing = [k for k in keys if k not in obj]
    if missing:
        raise ReviewError(f"{where}: missing required key(s) {', '.join(missing)}")
    extra = [k for k in obj if k not in keys]
    if extra:
        raise ReviewError(f"{where}: unknown key(s) {', '.join(extra)}")
    for k, typ in keys.items():
        v = obj[k]
        # bool is an int subclass; never accept it where an int is expected.
        if isinstance(v, bool) or not isinstance(v, typ):
            expected = typ.__name__ if isinstance(typ, type) else "string or null"
            raise ReviewError(f"{where}: key {k!r} must be {expected}")


def _check_enum(value: str, allowed: tuple[str, ...], where: str, key: str) -> None:
    if value not in allowed:
        raise ReviewError(f"{where}: {key} {value!r} is not one of {', '.join(allowed)}")


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


def from_dict(data: dict) -> Review:
    """Build a Review from parsed JSON, applying every rule in design section 5.6."""
    # Version first: a file from another schema should say so before anything
    # about its keys, which are allowed to differ.
    if isinstance(data, dict) and "version" in data and data["version"] != SCHEMA_VERSION:
        raise ReviewError(f"review: unsupported version {data['version']!r} (expected {SCHEMA_VERSION})")
    _check_keys(data, _TOP_KEYS, "review")
    if not all(isinstance(c, str) for c in data["categories"]):
        raise ReviewError("review: categories must be a list of strings")

    packs: dict[str, Pack] = {}
    folders: dict[str, str] = {}
    for pid, raw in data["packs"].items():
        where = f"pack {pid!r}"
        if not ID_RE.match(pid):
            raise ReviewError(f"{where}: id must match {ID_RE.pattern}")
        _check_keys(raw, _PACK_KEYS, where)
        if raw["folder"] in folders:
            raise ReviewError(f"{where}: folder {raw['folder']!r} is already used by pack {folders[raw['folder']]!r}")
        folders[raw["folder"]] = pid
        packs[pid] = Pack(**raw)

    slots: list[Slot] = []
    slot_ids: set[str] = set()
    candidate_ids: set[str] = set()
    for i, raw_slot in enumerate(data["slots"]):
        where = f"slot #{i + 1}"
        _check_keys(raw_slot, _SLOT_KEYS, where)
        sid = raw_slot["id"]
        where = f"slot {sid!r}"
        if not ID_RE.match(sid):
            raise ReviewError(f"{where}: id must match {ID_RE.pattern}")
        if sid in slot_ids:
            raise ReviewError(f"{where}: duplicate slot id")
        slot_ids.add(sid)
        _check_enum(raw_slot["priority"], PRIORITIES, where, "priority")

        candidates: list[Candidate] = []
        for j, raw_c in enumerate(raw_slot["candidates"]):
            cwhere = f"{where} candidate #{j + 1}"
            _check_keys(raw_c, _CANDIDATE_KEYS, cwhere)
            cid = raw_c["id"]
            cwhere = f"{where} candidate {cid!r}"
            if not CANDIDATE_ID_RE.match(cid):
                raise ReviewError(f"{cwhere}: id must match {CANDIDATE_ID_RE.pattern}")
            if cid in candidate_ids:
                raise ReviewError(f"{cwhere}: duplicate candidate id")
            candidate_ids.add(cid)
            _check_candidate_path(raw_c["path"], cwhere)
            if raw_c["pack"] is not None and raw_c["pack"] not in packs:
                raise ReviewError(f"{cwhere}: pack {raw_c['pack']!r} is not in packs")
            _check_enum(raw_c["role"], ROLES, cwhere, "role")
            _check_enum(raw_c["decision"], DECISIONS, cwhere, "decision")
            candidates.append(Candidate(**raw_c))

        selected = raw_slot["selected"]
        if selected is not None:
            chosen = next((c for c in candidates if c.id == selected), None)
            if chosen is None:
                raise ReviewError(f"{where}: selected {selected!r} is not one of its candidates")
            if chosen.decision == "nay":
                raise ReviewError(f"{where}: selected candidate {selected!r} is marked nay")

        slots.append(
            Slot(
                id=sid,
                category=raw_slot["category"],
                function=raw_slot["function"],
                priority=raw_slot["priority"],
                notes=raw_slot["notes"],
                selected=selected,
                candidates=candidates,
            )
        )

    return Review(
        version=data["version"],
        project=data["project"],
        root=data["root"],
        categories=list(data["categories"]),
        packs=packs,
        slots=slots,
    )


def to_dict(review: Review) -> dict:
    """Plain dict in canonical key order (section 5), ready for json.dump."""
    return {
        "version": review.version,
        "project": review.project,
        "root": review.root,
        "categories": list(review.categories),
        "packs": {pid: {"name": p.name, "folder": p.folder, "license": p.license} for pid, p in review.packs.items()},
        "slots": [
            {
                "id": s.id,
                "category": s.category,
                "function": s.function,
                "priority": s.priority,
                "notes": s.notes,
                "selected": s.selected,
                "candidates": [
                    {
                        "id": c.id,
                        "path": c.path,
                        "pack": c.pack,
                        "role": c.role,
                        "why": c.why,
                        "listen_for": c.listen_for,
                        "proposed_use": c.proposed_use,
                        "decision": c.decision,
                        "notes": c.notes,
                    }
                    for c in s.candidates
                ],
            }
            for s in review.slots
        ],
    }


def load(path: Path) -> Review:
    """Read and validate a review file. Raises ReviewError; never repairs."""
    path = Path(path)
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as e:
        raise ReviewError(f"cannot read {path}: {e.strerror or e}") from e
    except UnicodeDecodeError as e:
        raise ReviewError(f"{path}: not valid UTF-8 ({e})") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ReviewError(f"{path}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}") from e
    return from_dict(data)


def dumps(review: Review) -> str:
    """Canonical text form: two-space indent, ordered keys, trailing newline."""
    return json.dumps(to_dict(review), indent=2, ensure_ascii=False) + "\n"


def save(review: Review, path: Path) -> None:
    """Atomic write: `<file>.tmp` beside the target, then os.replace."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    data = dumps(review).encode("utf-8")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
