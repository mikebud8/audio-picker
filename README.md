# audio-picker

GUI for batch audio SFX picking for a game. Design: `docs/audio-picker-design.md`.

## Install and run

```
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m pytest
.venv\Scripts\audio-picker review.json --root path\to\audio\library
.venv\Scripts\python -m audio_picker review.json        # equivalent
```

Python 3.11 or newer; PySide6 6.11.2 or newer (the version that passed the codec check below).

## Status

All seven implementation steps of the design are in place: data model, paths,
library index, check report, CSV import, export manifest, command line and
the GUI. Run the tests with `.venv\Scripts\python -m pytest`.

## Commands

```
audio-picker REVIEW.json [--root DIR]                # open the GUI
audio-picker gui REVIEW.json [--root DIR]
audio-picker import-csv INPUT.csv -o REVIEW.json --root DIR --project NAME [--force]
audio-picker export REVIEW.json [--root DIR] [-o MANIFEST.json] [--strict]
audio-picker check REVIEW.json [--root DIR]
```

Exit codes: 0 success, 1 validation or file error (message on stderr),
2 usage error. `export --strict` exits 1 when a first-pass slot has no
selection or a selected file is missing; the manifest is still written.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `1` – `9` | Play candidate N. The key of the playing candidate stops it. |
| `Space` | Pause / resume; if nothing is loaded, play candidate 1. |
| `S` | Stop. |
| `L` | Toggle loop. |
| `Y` / `N` | Mark the active candidate yay / nay (again to clear). |
| `Enter` | Select the active candidate for the slot. |
| `Escape` | Leave a text field and return to the slot tree. |
| `Ctrl+Down` / `Ctrl+Up` | Next / previous slot in the filtered tree, wrapping. |
| `Ctrl+F` | Focus the slot search box. |
| `Ctrl+S` | Save now (edits autosave after half a second anyway). |
| `Ctrl+N`, `Ctrl+Shift+N`, `Ctrl+E` | Add slot, add candidate, edit slot. |
| `Ctrl+O` | Open another review. |

The *active* candidate is the one playing, else the last one played in this
slot, else candidate 1. It has a highlighted left border. Single-key shortcuts
are suppressed while a text field has focus.

The harness from the codec check still exists:

```
.venv\Scripts\python -m audio_picker.player FILE [FILE ...]
```

## Codec check

The wheel bundles Qt's FFmpeg multimedia backend. The app sets
`QT_MEDIA_BACKEND=ffmpeg` before creating the application unless the
variable is already set. Manual acceptance per design section 15: through the
harness, play one file of each format and confirm sound, seeking, pause and
resume, and looping.

| Environment | Value |
|---|---|
| Python | 3.14.6 (Windows 11) |
| PySide6 | 6.11.2 |
| Automated | `tests/test_player.py`: play, pause, resume, stop on a generated WAV; missing-file error path |

| Format | Sound | Seek | Pause/resume | Loop |
|---|---|---|---|---|
| WAV (24-bit PCM) | pass | pass | pass | pass |
| OGG Vorbis | pass | pass | pass | pass |
| MP3 | pass | pass | pass | pass |
| FLAC | no file available | | | |

Checked 2026-09-17 on the real library through the harness. Harmless
first-play noise on the terminal: FFmpeg probes Media Foundation video
encoders (`hevc_mf ... could not create MFT`) and prints stream info per file.

Hotkeys (number keys, Space, S, L) were exercised in the same session.
FLAC is kept in the supported suffix set but is unverified: no FLAC file was
available locally.
