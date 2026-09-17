"""Export manifest (design section 9): the hand-off point for per-project copy steps.

Nothing is copied. `root` and every `absolute_path` are absolute with forward
slashes so a consumer on any platform can read them.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .model import Review
from .paths import to_absolute

MANIFEST_VERSION = 1


def _iso_utc(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fwd(p: str | os.PathLike[str]) -> str:
    return os.path.abspath(str(p)).replace("\\", "/")


def build_manifest(review: Review, root: Path, now: datetime) -> dict:
    root = Path(root)
    root_str = _fwd(root)
    selections: list[dict] = []
    unselected: list[dict] = []
    gaps: list[dict] = []

    for slot in review.slots:
        status = slot.status()
        if status == "selected":
            c = slot.candidate(slot.selected)
            assert c is not None  # guaranteed by validation
            pack = review.packs.get(c.pack) if c.pack is not None else None
            selections.append(
                {
                    "slot": slot.id,
                    "category": slot.category,
                    "priority": slot.priority,
                    "candidate": c.id,
                    "path": c.path,
                    "absolute_path": f"{root_str}/{c.path}",
                    "exists": to_absolute(root, c.path).is_file(),
                    "pack_id": c.pack,
                    "pack": pack.name if pack else None,
                    "license": pack.license if pack else None,
                    "proposed_use": c.proposed_use,
                }
            )
        elif status == "gap":
            gaps.append({"slot": slot.id, "priority": slot.priority, "notes": slot.notes})
        else:
            unselected.append(
                {
                    "slot": slot.id,
                    "priority": slot.priority,
                    "status": status,
                    "candidates": len(slot.candidates),
                }
            )

    return {
        "manifest_version": MANIFEST_VERSION,
        "project": review.project,
        "generated": _iso_utc(now),
        "root": root_str,
        "selections": selections,
        "unselected": unselected,
        "gaps": gaps,
    }


def first_pass_unselected(review: Review) -> list[str]:
    """Ids of `first_pass` slots that are unselected or rejected (gaps are reported separately)."""
    return [s.id for s in review.slots if s.priority == "first_pass" and s.status() in ("unselected", "rejected")]
