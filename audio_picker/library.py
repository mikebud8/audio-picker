"""Audio library index (design section 11).

Walks the root once and keeps a sorted list of relative forward-slash paths
with an audio suffix. Skips hidden directories, dot-prefixed files (macOS
`._*` resource forks) and `__MACOSX` folders, which zip extraction leaves
beside real packs. `search` accepts `#tag` terms when given a
`LibraryAnnotations` store.
"""

from __future__ import annotations

import os
from pathlib import Path

from .model import AUDIO_SUFFIXES

_SKIP_DIRS = {"__MACOSX"}


class AudioLibrary:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._paths: list[str] = []
        self.refresh()

    @property
    def paths(self) -> list[str]:
        return list(self._paths)

    def __len__(self) -> int:
        return len(self._paths)

    def refresh(self) -> None:
        """Rescan the root. A missing root yields an empty library."""
        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS)
            rel_dir = os.path.relpath(dirpath, self.root)
            prefix = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
            for name in filenames:
                if name.startswith("."):
                    continue
                if os.path.splitext(name)[1].lower() in AUDIO_SUFFIXES:
                    found.append(prefix + name)
        self._paths = sorted(found)

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

    @staticmethod
    def pack_folder(rel_path: str) -> str:
        """First path component, or "" for a file directly under the root."""
        head, sep, _tail = rel_path.partition("/")
        return head if sep else ""
