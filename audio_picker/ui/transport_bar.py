"""Now-playing, position, loop and volume (design section 13.5)."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from ..player import PlayerState


def fmt_ms(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


class TransportBar(QWidget):
    play_pause_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, player, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self._player = player
        self._settings = settings

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        self.play_pause = QPushButton("Play")
        self.play_pause.setToolTip("Pause / resume (Space)")
        self.play_pause.clicked.connect(self.play_pause_clicked)
        self.stop = QPushButton("Stop")
        self.stop.setToolTip("Stop (S)")
        self.stop.clicked.connect(self.stop_clicked)
        self.now_playing = QLabel("Nothing playing")
        self.now_playing.setMinimumWidth(160)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.setToolTip("Position")
        self.slider.sliderMoved.connect(self._player.seek)
        self.slider.sliderReleased.connect(lambda: self._player.seek(self.slider.value()))
        self.time = QLabel("0:00 / 0:00")
        self.loop = QCheckBox("Loop")
        self.loop.setToolTip("Repeat the track while auditioning (L)")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(100)
        self.volume.setToolTip("Volume")

        layout.addWidget(self.play_pause)
        layout.addWidget(self.stop)
        layout.addWidget(self.now_playing)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.time)
        layout.addSpacing(8)
        layout.addWidget(self.loop)
        layout.addWidget(QLabel("Vol"))
        layout.addWidget(self.volume)

        loop = settings.value("transport/loop", False, type=bool)
        volume = settings.value("transport/volume", 80, type=int)
        self.loop.setChecked(loop)
        self.volume.setValue(volume)
        self._player.set_loop(loop)
        self._player.set_volume(volume / 100)
        self.loop.toggled.connect(self._on_loop)
        self.volume.valueChanged.connect(self._on_volume)

        # Bound methods, never lambdas: the player can outlive this bar (the review and library
        # windows share one), and Qt only drops a slot with its receiver when it is a bound method.
        player.state_changed.connect(self._on_state)
        player.position_changed.connect(self._on_position)
        player.seekable_changed.connect(self._on_source_or_seekable)
        player.source_changed.connect(self._on_source_or_seekable)

    def set_now_playing(self, cid: str | None, name: str | None) -> None:
        self.now_playing.setText(f"{cid}  {name}" if cid else "Nothing playing")
        self.now_playing.setToolTip(name or "")

    def _on_loop(self, on: bool) -> None:
        self._player.set_loop(on)
        self._settings.setValue("transport/loop", on)

    def _on_volume(self, value: int) -> None:
        self._player.set_volume(value / 100)
        self._settings.setValue("transport/volume", value)

    def _on_state(self, state: PlayerState) -> None:
        self.play_pause.setText("Pause" if state is PlayerState.PLAYING else "Play")
        if state is PlayerState.STOPPED:
            self.slider.setValue(0)
            self.time.setText(f"0:00 / {fmt_ms(self._player.duration_ms)}")
        self._refresh_slider()

    def _on_position(self, ms: int, duration: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setRange(0, max(0, duration))
            self.slider.setValue(ms)
        self.time.setText(f"{fmt_ms(ms)} / {fmt_ms(duration)}")

    def _on_source_or_seekable(self, _value) -> None:
        self._refresh_slider()

    def _refresh_slider(self) -> None:
        has_source = self._player.source is not None
        self.slider.setEnabled(bool(self._player.seekable) and has_source)
