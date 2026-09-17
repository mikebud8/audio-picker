import os

# Both must be set before pytest-qt creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from audio_picker.player import ensure_media_backend  # noqa: E402

ensure_media_backend()
