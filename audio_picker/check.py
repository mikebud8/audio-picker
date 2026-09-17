"""Validation report (design section 10) shared by the `check` command and the GUI.

Findings carry a stable `code` so callers branch on it, never on message text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .library import AudioLibrary
from .model import Review
from .paths import to_absolute

Severity = Literal["error", "warning"]


@dataclass
class Finding:
    code: str
    severity: Severity
    slot: str
    candidate: str | None
    message: str


@dataclass
class CheckReport:
    findings: list[Finding] = field(default_factory=list)

    def has(self, *codes: str) -> bool:
        return any(f.code in codes for f in self.findings)

    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]


def check_review(review: Review, root: Path) -> CheckReport:
    """Run every check in section 10. Findings are in slot file order, packs last."""
    root = Path(root)
    folder_to_pack = {p.folder: pid for pid, p in review.packs.items()}
    used_packs: set[str] = set()
    findings: list[Finding] = []

    for slot in review.slots:
        for c in slot.candidates:
            if c.pack is not None:
                used_packs.add(c.pack)
            if not to_absolute(root, c.path).is_file():
                findings.append(Finding("missing_file", "error", slot.id, c.id, f"file not found: {c.path}"))
                if slot.selected == c.id:
                    findings.append(
                        Finding(
                            "selected_missing",
                            "error",
                            slot.id,
                            c.id,
                            f"selected candidate file not found: {c.path}",
                        )
                    )
            folder = AudioLibrary.pack_folder(c.path)
            owner = folder_to_pack.get(folder)
            if owner is None:
                findings.append(
                    Finding(
                        "unmatched_pack_folder",
                        "warning",
                        slot.id,
                        c.id,
                        f"folder {folder!r} matches no pack",
                    )
                )
            elif c.pack is not None and c.pack != owner:
                findings.append(
                    Finding(
                        "pack_mismatch",
                        "warning",
                        slot.id,
                        c.id,
                        f"pack is {c.pack!r} but folder {folder!r} belongs to {owner!r}",
                    )
                )

        if slot.priority == "first_pass":
            status = slot.status()
            if status == "gap":
                findings.append(
                    Finding("first_pass_gap", "warning", slot.id, None, "first-pass slot has no candidates")
                )
            elif status in ("unselected", "rejected"):
                findings.append(
                    Finding(
                        "first_pass_unselected",
                        "warning",
                        slot.id,
                        None,
                        f"first-pass slot is {status}",
                    )
                )

    for pid in review.packs:
        if pid not in used_packs:
            findings.append(Finding("unused_pack", "warning", "", None, f"pack {pid!r} is referenced by no candidate"))

    return CheckReport(findings)
