"""Create the QApplication, apply the media backend, open the main window."""

from __future__ import annotations

import sys
from pathlib import Path

from ..model import ReviewError
from ..player import Player, ensure_media_backend


def run(review_path: Path, root: Path) -> int:
    ensure_media_backend()
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("audio-picker")
    app.setApplicationName("audio-picker")
    player = Player()
    try:
        window = MainWindow(Path(review_path), Path(root), player=player)
    except ReviewError as e:
        QMessageBox.critical(None, "Cannot open review", str(e))
        return 1
    window.show()
    return app.exec()
