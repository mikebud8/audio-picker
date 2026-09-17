"""Root resolution and relative/absolute conversion (design section 6).

Candidate paths are stored relative to the audio root with forward slashes.
Comparison is lexical on normalised absolute paths; symlinks are not resolved.
This is the one module allowed to rewrite path separators.
"""

from __future__ import annotations

import os
from pathlib import Path

from .model import ReviewError


def _normalised(p: str | os.PathLike[str]) -> str:
    # Backslashes are accepted as separators on every platform because the
    # CSV import (section 8) feeds Windows-style paths through here.
    return os.path.normpath(os.path.abspath(str(p).replace("\\", "/")))


def resolve_root(
    review_path: str | os.PathLike[str],
    review_root: str | None,
    cli_root: str | os.PathLike[str] | None,
) -> Path:
    """CLI `--root` wins; otherwise `review.root` resolved against the review file's directory.

    Raises ReviewError unless the result is an existing directory.
    """
    if cli_root is not None:
        candidate = Path(cli_root)
    else:
        if review_root is None:
            raise ReviewError("no audio root: the review has no root and --root was not given")
        candidate = Path(review_path).parent / review_root
    root = Path(_normalised(candidate))
    if not root.is_dir():
        raise ReviewError(f"audio root is not a directory: {root}")
    return root


def to_relative(root: str | os.PathLike[str], absolute: str | os.PathLike[str]) -> str | None:
    """Forward-slash path of `absolute` relative to `root`, or None if it is not under root."""
    r = _normalised(root)
    a = _normalised(absolute)
    r_cmp = os.path.normcase(r)
    a_cmp = os.path.normcase(a)
    if a_cmp == r_cmp:
        return ""
    prefix = r_cmp.rstrip(os.sep) + os.sep
    if not a_cmp.startswith(prefix):
        return None
    return a[len(prefix) :].replace(os.sep, "/")


def to_absolute(root: str | os.PathLike[str], rel: str) -> Path:
    return Path(root) / rel
