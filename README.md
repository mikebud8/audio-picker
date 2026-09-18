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
the GUI, plus the library annotations feature (rating, tags and notes) on
top. Run the tests with `.venv\Scripts\python -m pytest`; the suite covers the
model, the command line, the GUI, the library annotations and the screenshots.

The test run also writes screenshots of the main window and dialogs in light
and dark themes, and of the Library notes dock, the widened Add Candidate
dialog and the standalone library viewer, to `screenshots/` (git-ignored) for
eyeballing layout and contrast. `ruff check` and `ruff format --check` keep
the code tidy.

## Commands

```
audio-picker REVIEW.json [--root DIR]                # open the GUI
audio-picker gui REVIEW.json [--root DIR]
audio-picker import-csv INPUT.csv -o REVIEW.json --root DIR --project NAME [--force]
audio-picker export REVIEW.json [--root DIR] [-o MANIFEST.json] [--strict]
audio-picker check REVIEW.json [--root DIR]
audio-picker library --root DIR                      # browse, rate and tag the library without a review
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
| `Escape` | Leave a text field (clears a half-typed tag) and return to the slot tree. |
| `Ctrl+Down` / `Ctrl+Up` | Next / previous slot in the filtered tree, wrapping. |
| `Ctrl+F` | Focus the slot search box. |
| `Ctrl+S` | Save now (edits autosave after half a second anyway). |
| `Ctrl+N`, `Ctrl+Shift+N`, `Ctrl+E` | Add slot, add candidate, edit slot. |
| `Ctrl+O` | Open another review. |

The *active* candidate is the one playing, else the last one played in this
slot, else candidate 1. It has a highlighted left border. Single-key shortcuts
are suppressed while a text field has focus.

The standalone library viewer (`File, Library viewer…` or
`audio-picker library --root DIR`) has its own, shorter set:

| Key | Action |
|---|---|
| `Space` | Pause / resume; if nothing is loaded, play the current row. |
| `S` | Stop. |
| `L` | Toggle loop. |
| `Ctrl+F` | Focus the search box. |
| `Ctrl+S` | Save now. |
| `F5` | Rescan the library. |
| `Ctrl+W` | Close the viewer. |
| `Escape` | Leave a text field (clears a half-typed tag) and return to the file list. |

The harness from the codec check still exists:

```
.venv\Scripts\python -m audio_picker.player FILE [FILE ...]
```

## Library notes

Any file in the library can carry a quality rating (1 to 5 stars, meaning
how clean the recording is, not whether you like it), a set of tags and a
note. They are stored in `audio-picker-library.json` in the audio root, so
they belong to the library, not to one review, and survive reuse of the same
packs in another project. The audio files and folders are never touched.

Three places edit the same data:

- **View, Library notes** in the review window shows a dock that follows the
  active candidate.
- The **Add candidate** dialog shows the same editor for the highlighted
  result, and `#tag` in its search box matches a tag. Notes made there are
  kept even if you cancel adding the candidate.
- **File, Library viewer** (or `audio-picker library --root DIR`) opens a
  standalone browser with a tag filter, a minimum-rating filter, `#tag`
  search, playback with Space and `S`, and `F5` to rescan. When no search or
  filter is active, annotated files that no longer exist on disk are listed
  greyed at the end. Their annotations stay in the sidecar until you clear
  them from the viewer.

A tag is trimmed, lowercased and its internal spaces become hyphens, so
"Foot Step" becomes `foot-step`. Enter or a comma commits the tag field, and
it autocompletes from every tag already used anywhere in the library. A
file whose rating, tags and note are all cleared drops out of the sidecar
entirely, which is plain JSON you can commit alongside the packs.

Edits autosave after half a second and on `Ctrl+S`. Quitting or opening
another review first saves both the review and the library notes; if either
cannot be written you are asked to try again, discard, or cancel. If the
sidecar is malformed the app shows the error and keeps a warning in the
status bar, library notes become read-only (every editor is disabled), and
Rescan library (F5 in the viewer) retries the load. Rescan also reloads a
hand-edited sidecar when nothing is unsaved.

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
