"""Player behaviour that needs no ears: initial state, no-ops, and the error path.

Audible behaviour (sound, seek, pause, loop per format) is the manual
acceptance in design section 15 and is exercised through the harness.
"""

import wave
from pathlib import Path

import pytest
from PySide6.QtMultimedia import QMediaDevices

from audio_picker.player import Player, PlayerState


@pytest.fixture
def player(qapp):
    p = Player()
    yield p
    p.stop()
    p.deleteLater()


def _write_silence_wav(path: Path, seconds: float = 0.5) -> Path:
    rate = 8000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def test_initial_state(player):
    assert player.state is PlayerState.STOPPED
    assert player.source is None
    assert player.position_ms == 0
    assert player.duration_ms == 0


def test_resume_and_seek_without_source_are_noops(player):
    player.resume()
    player.seek(1000)
    player.toggle_pause()
    assert player.state is PlayerState.STOPPED
    assert player.source is None


def test_missing_file_reports_error_and_clears_source(player, qtbot, tmp_path):
    missing = tmp_path / "nope.wav"
    with qtbot.waitSignal(player.error, timeout=5000) as blocker:
        player.play(missing)
    assert blocker.args[0].startswith("nope.wav: ")
    assert player.source is None
    assert player.state is PlayerState.STOPPED


@pytest.mark.skipif(QMediaDevices.defaultAudioOutput().isNull(), reason="no audio output device")
def test_play_pause_stop_transitions(player, qtbot, tmp_path):
    wav = _write_silence_wav(tmp_path / "silence.wav")
    seen = []
    player.state_changed.connect(seen.append)

    with qtbot.waitSignal(player.state_changed, timeout=5000):
        player.play(wav)
    assert player.source == wav
    assert player.state is PlayerState.PLAYING

    with qtbot.waitSignal(player.state_changed, timeout=5000):
        player.pause()
    assert player.state is PlayerState.PAUSED

    with qtbot.waitSignal(player.state_changed, timeout=5000):
        player.resume()
    assert player.state is PlayerState.PLAYING

    with qtbot.waitSignal(player.state_changed, timeout=5000):
        player.stop()
    assert player.state is PlayerState.STOPPED
    assert player.source == wav, "stop keeps the source so resume can replay it"
    assert seen == [
        PlayerState.PLAYING,
        PlayerState.PAUSED,
        PlayerState.PLAYING,
        PlayerState.STOPPED,
    ]
