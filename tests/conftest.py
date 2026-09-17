import os
import sys

# Both must be set before pytest-qt creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform ships no fonts; point it at the system fonts so
# screenshots and text metrics are realistic.
if sys.platform == "win32" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from audio_picker.player import ensure_media_backend  # noqa: E402

ensure_media_backend()
