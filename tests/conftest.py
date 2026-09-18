import os
import sys
from pathlib import Path

import pytest

# Both must be set before pytest-qt creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform ships no fonts; point it at the system fonts so
# screenshots and text metrics are realistic.
if sys.platform == "win32" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from audio_picker.player import ensure_media_backend  # noqa: E402

ensure_media_backend()

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"


def _fixture_tree() -> list[str]:
    return sorted(str(p.relative_to(FIXTURE_ROOT)) for p in FIXTURE_ROOT.rglob("*"))


@pytest.fixture(scope="session", autouse=True)
def _fixture_root_stays_pristine():
    """A window opened on the checked-in audio fixture would write its sidecar into the repo.

    Tests that dirty an annotation store must use a copy (the `tmp_root` fixture), so fail
    loudly rather than leaving an untracked file behind and breaking later runs.
    """
    before = _fixture_tree()
    yield
    after = _fixture_tree()
    added = [p for p in after if p not in before]
    removed = [p for p in before if p not in after]
    assert not added and not removed, (
        f"the test suite changed {FIXTURE_ROOT}: added {added}, removed {removed}. "
        "Use the tmp_root fixture for any window whose library store gets dirty."
    )
