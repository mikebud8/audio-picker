"""One-off migration of the one-more-turn spreadsheet CSV (design section 8).

Not a general CSV loader: the column names in COLUMNS are required exactly.
Warnings go through the `warn` callback and never stop the import; errors
raise ReviewError and nothing is written.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from pathlib import Path

from .model import (
    CANDIDATE_ID_RE,
    ID_RE,
    SCHEMA_VERSION,
    Candidate,
    Pack,
    Review,
    ReviewError,
    Slot,
    from_dict,
    to_dict,
)
from .paths import to_relative

COLUMNS = (
    "ID",
    "Decision (Yay/Nay)",
    "Your notes",
    "Priority",
    "Category",
    "Game function",
    "Slot",
    "Choice",
    "Candidate",
    "Why this candidate",
    "Listen for",
    "Proposed use after approval",
    "Pack",
    "License provenance",
    "Source path",
    "Assessment",
)

PRIORITY_MAP = {"First pass": "first_pass", "Later": "later", "Optional": "optional", "Gap": "later"}
CHOICE_MAP = {
    "First choice": "first",
    "Alternative": "alternative",
    "Variation": "variation",
    "Existing selection; review reference": "reference",
}
GAP_CHOICE = "No direct candidate"


def slugify_pack(name: str) -> str:
    """Lower-case, non-alphanumerics collapsed to `_`, `pack_` prefix if it would start with a digit."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if slug and slug[0].isdigit():
        slug = "pack_" + slug
    return slug


def _decision(raw: str, where: str) -> str:
    d = raw.strip().lower()
    if d == "":
        return "unreviewed"
    if d in ("yay", "nay"):
        return d
    raise ReviewError(f"{where}: unknown decision {raw!r} (expected Yay, Nay or blank)")


def import_csv(
    csv_path: Path,
    root: Path,
    project: str,
    warn: Callable[[str], None],
) -> Review:
    csv_path = Path(csv_path)
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        missing = [c for c in COLUMNS if c not in fields]
        if missing:
            raise ReviewError(f"{csv_path.name}: missing required column(s): {', '.join(missing)}")
        rows = list(reader)

    slots: dict[str, Slot] = {}
    categories: list[str] = []
    packs: dict[str, Pack] = {}
    pack_names: dict[str, str] = {}
    seen_ids: set[str] = set()

    for row in rows:
        rid = row["ID"].strip()
        sid = row["Slot"].strip()
        where = f"row {rid!r}"

        priority = PRIORITY_MAP.get(row["Priority"].strip())
        if priority is None:
            raise ReviewError(f"{where}: unknown priority {row['Priority']!r}")
        choice = row["Choice"].strip()
        is_gap = choice == GAP_CHOICE
        if not is_gap and choice not in CHOICE_MAP:
            raise ReviewError(f"{where}: unknown choice {choice!r}")
        if not ID_RE.match(sid):
            raise ReviewError(f"{where}: slot id {sid!r} must match {ID_RE.pattern}")
        decision = _decision(row["Decision (Yay/Nay)"], where)

        category = row["Category"].strip()
        function = row["Game function"].strip()
        slot = slots.get(sid)
        if slot is None:
            slot = Slot(sid, category, function, priority, "", None, [])
            slots[sid] = slot
            if category not in categories:
                categories.append(category)
        else:
            if slot.category != category:
                warn(f"{where}: Category {category!r} differs from slot {sid!r} ({slot.category!r}); keeping the first")
            if slot.function != function:
                warn(f"{where}: Game function differs from slot {sid!r}; keeping the first")

        if is_gap:
            notes = row["Why this candidate"]
            if row["Proposed use after approval"]:
                notes += "\n\n" + row["Proposed use after approval"]
            slot.notes = notes
            continue

        if not CANDIDATE_ID_RE.match(rid):
            raise ReviewError(f"{where}: candidate id must match {CANDIDATE_ID_RE.pattern}")
        if rid in seen_ids:
            raise ReviewError(f"{where}: duplicate candidate id")

        src = row["Source path"].strip()
        if not src:
            raise ReviewError(f"{where}: Source path is empty on a non-gap row")
        rel = to_relative(root, src)
        if not rel:
            raise ReviewError(f"{where}: Source path {src!r} is not under root {root}")
        basename = rel.rsplit("/", 1)[-1]
        if row["Candidate"] and row["Candidate"] != basename:
            warn(f"{where}: Candidate {row['Candidate']!r} is not the file name {basename!r}")

        pack_id: str | None = None
        pack_name = row["Pack"].strip()
        if pack_name:
            pack_id = slugify_pack(pack_name)
            folder = rel.partition("/")[0]
            license_ = row["License provenance"].strip()
            existing = packs.get(pack_id)
            if existing is None:
                packs[pack_id] = Pack(pack_name, folder, license_)
                pack_names[pack_id] = pack_name
            else:
                if pack_names[pack_id] != pack_name:
                    raise ReviewError(
                        f"{where}: pack names {pack_names[pack_id]!r} and {pack_name!r} both slugify to {pack_id!r}"
                    )
                if existing.license != license_:
                    warn(f"{where}: pack {pack_name!r} license differs; keeping the first")
                if existing.folder != folder:
                    warn(
                        f"{where}: pack {pack_name!r} folder {folder!r} differs from {existing.folder!r}; "
                        "keeping the first"
                    )

        slot.candidates.append(
            Candidate(
                id=rid,
                path=rel,
                pack=pack_id,
                role=CHOICE_MAP[choice],
                why=row["Why this candidate"],
                listen_for=row["Listen for"],
                proposed_use=row["Proposed use after approval"],
                decision=decision,
                notes=row["Your notes"],
            )
        )
        seen_ids.add(rid)

    review = Review(
        version=SCHEMA_VERSION,
        project=project,
        root=str(Path(root)).replace("\\", "/"),
        categories=categories,
        packs=packs,
        slots=list(slots.values()),
    )
    # Run the full section 5.6 validation so an importer bug can never write a bad file.
    return from_dict(to_dict(review))
