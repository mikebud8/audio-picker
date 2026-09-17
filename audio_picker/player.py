"""QMediaPlayer wrapper (design section 12) and the step-1 codec-check harness.

Harness:  python -m audio_picker.player FILE [FILE ...]

The wrapper knows only about file paths. Which *candidate* is being
auditioned is the UI's concern, because two candidates may share a file.
"""

from __future__ import annotations

import os
import sys
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

MEDIA_BACKEND_VAR = "QT_MEDIA_BACKEND"
DEFAULT_MEDIA_BACKEND = "ffmpeg"


def ensure_media_backend() -> str:
    """Select Qt's FFmpeg multimedia backend unless the caller already chose one.

    Must run before QApplication is created (design section 3): the Windows
    Media Foundation backend cannot decode OGG Vorbis.
    """
    return os.environ.setdefault(MEDIA_BACKEND_VAR, DEFAULT_MEDIA_BACKEND)


class PlayerState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


_QT_STATE = {
    QMediaPlayer.PlaybackState.StoppedState: PlayerState.STOPPED,
    QMediaPlayer.PlaybackState.PlayingState: PlayerState.PLAYING,
    QMediaPlayer.PlaybackState.PausedState: PlayerState.PAUSED,
}


class Player(QObject):
    """One QMediaPlayer plus one QAudioOutput, exposed through a small stable API."""

    state_changed = Signal(object)  # PlayerState
    position_changed = Signal(int, int)  # position_ms, duration_ms
    source_changed = Signal(object)  # Path | None
    seekable_changed = Signal(bool)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source: Path | None = None
        self._audio = QAudioOutput(self)
        self._media = QMediaPlayer(self)
        self._media.setAudioOutput(self._audio)
        self._media.playbackStateChanged.connect(self._on_playback_state)
        self._media.positionChanged.connect(self._on_position)
        self._media.durationChanged.connect(self._on_duration)
        self._media.seekableChanged.connect(self.seekable_changed)
        self._media.errorOccurred.connect(self._on_error)

    # -- commands ---------------------------------------------------------

    def play(self, path: Path) -> None:
        """Play `path` from position 0. The current source restarts from 0."""
        path = Path(path)
        if self._source != path:
            self._set_source(path)
        else:
            self._media.setPosition(0)
        self._media.play()

    def stop(self) -> None:
        """Stop and reset position to 0; the source is kept so resume() can replay it."""
        self._media.stop()

    def pause(self) -> None:
        if self.state is PlayerState.PLAYING:
            self._media.pause()

    def resume(self) -> None:
        """PAUSED -> PLAYING. From STOPPED with a source, play it from 0. No source: no-op."""
        if self._source is None:
            return
        self._media.play()

    def toggle_pause(self) -> None:
        if self.state is PlayerState.PLAYING:
            self.pause()
        else:
            self.resume()

    def seek(self, ms: int) -> None:
        """Set the position, clamped to [0, duration]. No-op while not seekable."""
        if not self.seekable:
            return
        self._media.setPosition(max(0, min(int(ms), self._media.duration())))

    def set_loop(self, on: bool) -> None:
        loops = QMediaPlayer.Loops.Infinite if on else QMediaPlayer.Loops.Once
        self._media.setLoops(loops)

    def set_volume(self, v: float) -> None:
        self._audio.setVolume(max(0.0, min(1.0, float(v))))

    # -- state ------------------------------------------------------------

    @property
    def state(self) -> PlayerState:
        return _QT_STATE[self._media.playbackState()]

    @property
    def source(self) -> Path | None:
        return self._source

    @property
    def seekable(self) -> bool:
        return self._media.isSeekable()

    @property
    def position_ms(self) -> int:
        return self._media.position()

    @property
    def duration_ms(self) -> int:
        return self._media.duration()

    # -- internals --------------------------------------------------------

    def _set_source(self, path: Path | None) -> None:
        self._source = path
        self._media.setSource(QUrl.fromLocalFile(str(path)) if path else QUrl())
        self.source_changed.emit(path)

    def _on_playback_state(self, qt_state: QMediaPlayer.PlaybackState) -> None:
        self.state_changed.emit(_QT_STATE[qt_state])

    def _on_position(self, ms: int) -> None:
        self.position_changed.emit(ms, self._media.duration())

    def _on_duration(self, ms: int) -> None:
        self.position_changed.emit(self._media.position(), ms)

    def _on_error(self, _code: QMediaPlayer.Error, text: str) -> None:
        name = self._source.name if self._source else "<no source>"
        self.error.emit(f"{name}: {text}")
        self._media.stop()
        self._set_source(None)


# ---------------------------------------------------------------------------
# Throwaway harness for the manual codec check (design section 18, step 1).
# ---------------------------------------------------------------------------


def _fmt_ms(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


def _harness_main(argv: list[str]) -> int:
    import PySide6
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QSlider,
        QVBoxLayout,
        QWidget,
    )

    backend = ensure_media_backend()
    app = QApplication(argv)

    files = [Path(a) for a in argv[1:]]
    if not files:
        print("usage: python -m audio_picker.player FILE [FILE ...]", file=sys.stderr)
        return 2
    for f in files:
        if not f.is_file():
            print(f"warning: not a file: {f}", file=sys.stderr)

    player = Player()

    class Harness(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Audio Picker: codec check")
            self.resize(720, 480)

            root = QVBoxLayout(self)
            root.addWidget(
                QLabel(f"Backend: {backend}   |   PySide6 {PySide6.__version__}   |   Python {sys.version.split()[0]}")
            )

            self.list = QListWidget()
            for i, f in enumerate(files, 1):
                item = QListWidgetItem(f"{i}  {f.name}" if i <= 9 else f"    {f.name}")
                item.setToolTip(str(f))
                item.setData(Qt.ItemDataRole.UserRole, str(f))
                self.list.addItem(item)
            self.list.setCurrentRow(0)
            self.list.itemActivated.connect(self._play_item)
            self.list.installEventFilter(self)
            root.addWidget(self.list, 1)

            transport = QHBoxLayout()
            self.play_btn = QPushButton("Play")
            self.play_btn.clicked.connect(self._play_or_pause)
            self.stop_btn = QPushButton("Stop")
            self.stop_btn.clicked.connect(player.stop)
            self.loop_cb = QCheckBox("Loop")
            self.loop_cb.toggled.connect(player.set_loop)
            self.volume = QSlider(Qt.Orientation.Horizontal)
            self.volume.setRange(0, 100)
            self.volume.setValue(80)
            self.volume.setFixedWidth(120)
            self.volume.valueChanged.connect(lambda v: player.set_volume(v / 100))
            player.set_volume(0.8)
            transport.addWidget(self.play_btn)
            transport.addWidget(self.stop_btn)
            transport.addWidget(self.loop_cb)
            transport.addStretch(1)
            transport.addWidget(QLabel("Volume"))
            transport.addWidget(self.volume)
            root.addLayout(transport)

            seek_row = QHBoxLayout()
            self.slider = QSlider(Qt.Orientation.Horizontal)
            self.slider.setEnabled(False)
            self.slider.sliderMoved.connect(player.seek)
            self.slider.sliderReleased.connect(lambda: player.seek(self.slider.value()))
            self.time = QLabel("0:00 / 0:00")
            seek_row.addWidget(self.slider, 1)
            seek_row.addWidget(self.time)
            root.addLayout(seek_row)

            self.status = QLabel("stopped")
            self.status.setWordWrap(True)
            root.addWidget(self.status)
            hint = QLabel(
                "Enter or double-click plays the highlighted file.  "
                "1-9 play by number.  Space pause/resume.  S stop.  L loop."
            )
            hint.setStyleSheet("color: gray")
            root.addWidget(hint)

            player.state_changed.connect(self._on_state)
            player.position_changed.connect(self._on_position)
            player.seekable_changed.connect(self._refresh_slider_enabled)
            player.source_changed.connect(self._refresh_slider_enabled)
            player.error.connect(self._on_error)

        # Keys the list view would otherwise swallow (Space selects, letters search).
        def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
            if obj is self.list and event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key == Qt.Key.Key_Space:
                    self._play_or_pause()
                    return True
                if key == Qt.Key.Key_S:
                    player.stop()
                    return True
                if key == Qt.Key.Key_L:
                    self.loop_cb.toggle()
                    return True
                if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
                    n = key - Qt.Key.Key_1
                    if n < len(files):
                        self.list.setCurrentRow(n)
                        self._play_path(files[n])
                    return True
            return super().eventFilter(obj, event)

        def _play_item(self, item: QListWidgetItem) -> None:
            self._play_path(Path(item.data(Qt.ItemDataRole.UserRole)))

        def _play_path(self, path: Path) -> None:
            self.status.setStyleSheet("")
            self.status.setText(f"loading {path.name}")
            player.play(path)

        def _play_or_pause(self) -> None:
            if player.state is PlayerState.PLAYING:
                player.pause()
            elif player.source is not None:
                player.resume()
            elif (item := self.list.currentItem()) is not None:
                self._play_item(item)

        def _on_state(self, state: PlayerState) -> None:
            self.play_btn.setText("Pause" if state is PlayerState.PLAYING else "Play")
            name = player.source.name if player.source else "(no source)"
            seekable = "yes" if player.seekable else "no"
            self.status.setText(f"{state.value}: {name}   seekable={seekable}")
            self._refresh_slider_enabled()

        def _on_position(self, ms: int, duration: int) -> None:
            if not self.slider.isSliderDown():
                self.slider.setRange(0, max(0, duration))
                self.slider.setValue(ms)
            self.time.setText(f"{_fmt_ms(ms)} / {_fmt_ms(duration)}")

        def _refresh_slider_enabled(self, *_args) -> None:
            self.slider.setEnabled(player.seekable and player.source is not None)

        def _on_error(self, text: str) -> None:
            print(f"error: {text}", file=sys.stderr)
            self.status.setStyleSheet("color: #c0392b")
            self.status.setText(f"error: {text}")

    window = Harness()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(_harness_main(sys.argv))
