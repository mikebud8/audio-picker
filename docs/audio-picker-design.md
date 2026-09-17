# Audio Picker — design spec

Date: 2026-09-17
Status: approved design, awaiting implementation
Target: a new standalone repository (suggested name `audio-picker`). This file
was drafted inside the `one-more-turn` repo only because that is where the
first data set lives; move it to the new repo as `docs/design.md`.

## 1. Purpose

A small desktop tool for choosing sound assets for a game. Given a review file
that lists *slots* (a sound the game needs, such as `ui_click`) and one or more
*candidate* audio files per slot, the tool lets a person:

- listen to every candidate for a slot, quickly, with the keyboard;
- record a yay/nay opinion and notes per candidate;
- pick the selected candidate for the slot;
- add and remove candidates, and add, edit and remove slots;
- import an existing spreadsheet-style CSV into the review format;
- export a manifest of the selected files with their license provenance, so a
  project-specific copy/convert step can consume it.

It is project-agnostic. The review file lives in each game project; the tool
lives in its own repo and is pointed at the file from the command line.

## 2. Non-goals (first version)

- Copying, converting or renaming audio into a project's asset tree. The export
  manifest is the hand-off point; the copy step is a separate script per project.
- Waveform display, trimming, loop-point editing, gain normalisation.
- Undo/redo. The review file is text under version control; git is the undo.
- Multi-user or concurrent editing.
- Any web server, browser UI, or Godot dependency.

## 3. Stack and environment

- Python 3.11 or newer (developed on 3.14; nothing 3.14-specific is required).
- PySide6 6.7 or newer; the lower bound in `pyproject.toml` is set to the
  version that passes the step-1 codec check, and the README records the
  exact Python and PySide6 versions that passed. The wheel bundles Qt's
  FFmpeg multimedia backend, which decodes WAV, OGG Vorbis, MP3 and FLAC on
  Windows, macOS and Linux. The app sets `QT_MEDIA_BACKEND=ffmpeg` in the
  environment before creating `QApplication` unless the variable is already
  set, so playback does not silently fall back to Windows Media Foundation
  (which lacks Vorbis).
- Dev dependencies: `pytest`, `pytest-qt`.
- No other runtime dependencies. Standard library covers CSV, JSON, paths.

Install and run:

```
pip install -e .[dev]
audio-picker review.json --root path/to/audio/library
python -m audio_picker review.json        # equivalent
```

## 4. Repository layout

```
audio-picker/
  README.md
  pyproject.toml              # package audio_picker; console script audio-picker = audio_picker.cli:main
  docs/design.md              # this file
  audio_picker/
    __init__.py               # __version__
    __main__.py               # from .cli import main; main()
    cli.py                    # argparse subcommands, dispatch
    model.py                  # dataclasses, load/save, validation, id allocation
    paths.py                  # root resolution, relative/absolute conversion, slash normalisation
    library.py                # audio file index under root
    csv_import.py             # CSV -> Review
    export.py                 # Review -> manifest
    check.py                  # validation report used by `check` and by the GUI on load
    player.py                 # QMediaPlayer wrapper
    ui/
      __init__.py
      app.py                  # create QApplication, apply env, open MainWindow
      main_window.py          # window, menus, splitter, autosave, shortcuts
      slot_tree.py            # left-hand grouped list + filters
      slot_panel.py           # right-hand slot header + candidate rows + transport
      candidate_row.py        # one candidate widget
      transport_bar.py        # now-playing, position, loop, volume
      dialogs.py              # AddCandidateDialog, SlotEditorDialog, confirmations
  tests/
    fixtures/                 # small CSV, small review.json, three tiny audio files (wav/ogg/mp3)
    test_model.py
    test_paths.py
    test_library.py
    test_csv_import.py
    test_export.py
    test_check.py
    test_ui_smoke.py          # pytest-qt, player mocked
  examples/
    review.json               # a five-slot example using tests/fixtures audio
```

Everything outside `ui/` and `player.py` must import nothing from Qt, so the
data layer is testable and reusable without a display.

## 5. Review file format (schema version 1)

A single JSON document, UTF-8, two-space indent, keys written in the order
listed below, trailing newline. `save` always rewrites the whole file in this
canonical form so diffs stay readable.

### 5.1 Top level

| Key | Type | Required | Meaning |
|---|---|---|---|
| `version` | int | yes | Always `1` for this schema. Loader refuses other values. |
| `project` | string | yes | Display name, e.g. `"one-more-turn"`. |
| `root` | string | yes | Audio library directory. Relative paths are resolved against the directory containing the JSON file. Forward slashes. May be absolute. |
| `categories` | list of string | yes | Display order for categories in the GUI. Slots whose category is not listed sort after these, alphabetically. |
| `packs` | object: pack id → Pack | yes | May be empty. |
| `slots` | list of Slot | yes | May be empty. Order in the file is authored order and is preserved. |

### 5.2 Pack

| Key | Type | Required | Meaning |
|---|---|---|---|
| `name` | string | yes | Human name, e.g. `"Epic Asian"`. |
| `folder` | string | yes | Top-level folder under `root` that holds this pack, e.g. `"epicasianaudiobundle"`. Used to infer the pack for newly added candidates. Must be unique across packs. |
| `license` | string | yes | Free-text provenance, e.g. `"Paid; Tao & Sound EULA.txt and purchase invoice"`. |

Pack ids are snake_case ASCII (`^[a-z][a-z0-9_]*$`).

### 5.3 Slot

| Key | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | snake_case (`^[a-z][a-z0-9_]*$`), unique across slots. This is the name game code will use. |
| `category` | string | yes | Free text grouping, e.g. `"UI"`. |
| `function` | string | yes | What the sound does in the game, one sentence. |
| `priority` | string | yes | One of `"first_pass"`, `"later"`, `"optional"`. |
| `notes` | string | yes | Slot-level free text. May be empty. |
| `selected` | string or null | yes | Candidate id chosen for this slot, or `null`. Must reference a candidate in this slot's list. |
| `candidates` | list of Candidate | yes | May be empty. An empty list means the slot is a *gap*. |

### 5.4 Candidate

| Key | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Unique across the whole file. Pattern `^[A-Z]+[0-9]+$`, e.g. `"A002"`. |
| `path` | string | yes | Audio file path relative to `root`, forward slashes. Must be non-empty, must not be absolute (no drive letter, no leading `/`), and must contain no `.` or `..` components. Existence is not checked on load; missing files are reported by `check` and flagged in the GUI. |
| `pack` | string or null | yes | Pack id, or `null` if unknown. Must exist in `packs` when non-null. |
| `role` | string | yes | One of `"first"`, `"alternative"`, `"variation"`, `"reference"`. Informational. |
| `why` | string | yes | Why this file is a candidate. May be empty. |
| `listen_for` | string | yes | What to pay attention to when auditioning. May be empty. |
| `proposed_use` | string | yes | How it would be used if chosen. May be empty. |
| `decision` | string | yes | One of `"unreviewed"`, `"yay"`, `"nay"`. |
| `notes` | string | yes | Reviewer notes. May be empty. |

### 5.5 Example

```json
{
  "version": 1,
  "project": "one-more-turn",
  "root": "../../vendor/audio",
  "categories": ["Music", "UI", "Movement", "Battle", "Outcomes", "Resources", "Loop", "World tells", "Ambience", "Unfilled"],
  "packs": {
    "epic_asian": {
      "name": "Epic Asian",
      "folder": "epicasianaudiobundle",
      "license": "Paid; Tao & Sound EULA.txt and purchase invoice"
    }
  },
  "slots": [
    {
      "id": "exploration_loop",
      "category": "Music",
      "function": "Quiet overworld planning and travel",
      "priority": "first_pass",
      "notes": "",
      "selected": null,
      "candidates": [
        {
          "id": "A002",
          "path": "epicasianaudiobundle/Epic Asian Audio Bundle/WAV/Music/JAP/01.2 Spirit (travel - cinematic) JAP.wav",
          "pack": "epic_asian",
          "role": "first",
          "why": "Japanese travel/cinematic label directly matches overworld exploration.",
          "listen_for": "Can it stay interesting without tiring during long decisions?",
          "proposed_use": "Loop; quiet background; confirm seamless edit",
          "decision": "unreviewed",
          "notes": ""
        }
      ]
    },
    {
      "id": "horn_distant",
      "category": "Unfilled",
      "function": "Authored detection tell",
      "priority": "later",
      "notes": "No clearly named horn or conch sample found. Keep this slot open instead of relabelling a gong.\n\nLeave silent until a candidate is approved.",
      "selected": null,
      "candidates": []
    }
  ]
}
```

### 5.6 Validation (load-time, hard errors)

`model.load(path)` raises `ReviewError` with a message naming the offending
slot/candidate for any of: wrong `version`; missing required key; wrong type;
enum value outside the allowed set; duplicate slot id; duplicate candidate id;
`selected` not present in that slot's candidates; candidate `pack` not in
`packs`; duplicate pack `folder`; slot or pack id failing the pattern;
candidate `path` empty, absolute, or containing `.`/`..` components; a
`selected` candidate whose `decision` is `nay`. Unknown extra keys are an
error too (this keeps the format honest; bump `version` to add fields).

Missing audio files are *not* a load error. They are reported by `check` and
shown in the GUI.

### 5.7 Derived status

Not stored; computed everywhere it is displayed. Exactly one applies, tested
in this order:

- `gap` — `candidates` is empty.
- `selected` — `selected` is not null.
- `rejected` — every candidate has `decision == "nay"`. These slots need
  fresh candidates, so they are called out separately.
- `unselected` — otherwise (at least one candidate is not `nay`, none chosen).

### 5.8 Selection and rejection rules

- Setting a candidate's decision to `nay` while it is the slot's `selected`
  candidate clears `selected`.
- A `nay` candidate cannot be selected. In the GUI its Selected radio is
  disabled with the tooltip "Marked Nay; change the rating to select".
- Selecting a candidate whose decision is `unreviewed` sets it to `yay` in the
  same mutation. Selecting an already-`yay` candidate leaves it alone.
- Selection never changes any other candidate's decision.

## 6. Path handling (`paths.py`)

- `resolve_root(review_path, review.root, cli_root) -> Path`: CLI `--root` wins
  when given; otherwise `review.root` resolved against `review_path.parent`.
  The result must be an existing directory or the command fails with a clear
  message before any window opens.
- `to_relative(root, absolute) -> str | None`: returns a forward-slash path
  relative to `root`, or `None` if the file is not under `root`.
- `to_absolute(root, rel) -> Path`.
- Candidate `path` values are always stored with forward slashes. On Windows,
  `Path` handles them; nothing in the code should string-replace separators
  except `to_relative`.
- Symlinks are not resolved; comparison is lexical on normalised absolute paths.

## 7. Command line (`cli.py`)

`argparse` with subcommands. A bare positional file (no subcommand) opens the
GUI, so the common case is `audio-picker review.json`.

```
audio-picker REVIEW.json [--root DIR]
audio-picker gui REVIEW.json [--root DIR]
audio-picker import-csv INPUT.csv -o REVIEW.json --root DIR --project NAME [--force]
audio-picker export REVIEW.json [--root DIR] [-o MANIFEST.json] [--strict]
audio-picker check REVIEW.json [--root DIR]
```

Exit codes: 0 success; 1 validation or file error (message on stderr);
2 argparse usage error. `export --strict` returns 1 if any `first_pass` slot
has no selection. `check` returns 1 if any hard error or missing file is found.

`import-csv` refuses to overwrite an existing output unless `--force`. Its
`root` field in the written JSON is `--root` made relative to the output file's
directory when both share a drive/anchor, otherwise absolute.

## 8. CSV import (`csv_import.py`)

Purpose: one-off migration of the spreadsheet format used by `one-more-turn`.
It is not a general CSV loader; the column names below are required exactly
(after stripping a UTF-8 BOM from the first header).

Required columns:
`ID, Decision (Yay/Nay), Your notes, Priority, Category, Game function, Slot, Choice, Candidate, Why this candidate, Listen for, Proposed use after approval, Pack, License provenance, Source path, Assessment`

Mapping, one CSV row → one candidate (or a gap slot):

| CSV column | Destination | Rule |
|---|---|---|
| `Slot` | `slot.id` | Groups rows. First row for a slot creates it; later rows append candidates. |
| `Category` | `slot.category` | From the first row of the slot. Warn if later rows differ. |
| `Game function` | `slot.function` | Same. |
| `Priority` | `slot.priority` | `First pass`→`first_pass`, `Later`→`later`, `Optional`→`optional`, `Gap`→`later` (gap-ness is carried by the empty candidate list). Anything else is an error. |
| `Choice` | `candidate.role` | `First choice`→`first`; `Alternative`→`alternative`; `Variation`→`variation`; `Existing selection; review reference`→`reference`; `No direct candidate`→ this row is a gap row (see below). Anything else is an error. |
| `ID` | `candidate.id` | Must match `^[A-Z]+[0-9]+$`, unique. |
| `Source path` | `candidate.path` | Made relative to `--root` with forward slashes. Error (not warning) if the path is empty on a non-gap row, is not under `--root` after normalisation, or would contain `..` after normalisation. The error names the row id and the offending path so the CSV can be fixed and re-run. |
| `Candidate` | (validation only) | Must equal the basename of `Source path`; warn if not. Not stored. |
| `Pack` + `License provenance` | `packs[...]` | Pack id = slugified name: lower-case, non-alphanumerics collapsed to `_`, and prefixed with `pack_` if the result would start with a digit (`Epic Asian`→`epic_asian`, `100 CC0`→`pack_100_cc0`). `folder` = first path component of the relative source path. If two rows for the same pack name disagree on license or folder, warn and keep the first. If two *different* pack names slugify to the same id, error: the importer never merges provenance silently. |
| `Decision (Yay/Nay)` | `candidate.decision` | Case-insensitive `yay`/`nay`; blank → `unreviewed`; anything else error. |
| `Your notes` | `candidate.notes` | Verbatim. |
| `Why this candidate` | `candidate.why` | Verbatim. |
| `Listen for` | `candidate.listen_for` | Verbatim. Per candidate on purpose: the source data differs between candidates of the same slot. |
| `Proposed use after approval` | `candidate.proposed_use` | Verbatim. |
| `Assessment` | dropped | Uniform boilerplate in the source data. |

Gap rows (`Choice == "No direct candidate"`): create the slot with no
candidates. `slot.notes` = `Why this candidate` and, if non-empty,
`Proposed use after approval` joined by a blank line. Nothing else from the
row is kept, including `ID`. Because `next_candidate_id` only looks at
existing candidates, a gap row's id (such as `A067`) may later be handed to a
new candidate; that is acceptable.

`categories` in the output = distinct categories in first-appearance order.
`slots` = first-appearance order. `selected` is `null` for every slot; the
CSV has no selection column.

Warnings go to stderr, prefixed `warning:`, one per line, and never stop the
import. Errors abort with no file written.

## 9. Export manifest (`export.py`)

`export` writes JSON (stdout when `-o` is omitted):

```json
{
  "manifest_version": 1,
  "project": "one-more-turn",
  "generated": "2026-09-17T18:04:11Z",
  "root": "D:/Projects/one-more-turn/vendor/audio",
  "selections": [
    {
      "slot": "exploration_loop",
      "category": "Music",
      "priority": "first_pass",
      "candidate": "A002",
      "path": "epicasianaudiobundle/.../01.2 Spirit (travel - cinematic) JAP.wav",
      "absolute_path": "D:/Projects/one-more-turn/vendor/audio/epicasianaudiobundle/.../01.2 Spirit (travel - cinematic) JAP.wav",
      "exists": true,
      "pack_id": "epic_asian",
      "pack": "Epic Asian",
      "license": "Paid; Tao & Sound EULA.txt and purchase invoice",
      "proposed_use": "Loop; quiet background; confirm seamless edit"
    }
  ],
  "unselected": [ { "slot": "tension_loop", "priority": "first_pass", "status": "unselected", "candidates": 2 } ],
  "gaps": [ { "slot": "horn_distant", "priority": "later", "notes": "..." } ]
}
```

`selections` are in slot file order. `root` and `absolute_path` are absolute
with forward slashes. `pack_id`, `pack` and `license` are `null` when the
candidate has no pack. `unselected` includes both `unselected` and `rejected`
slots, distinguished by `status`. Nothing is copied.

`--strict` exits 1 when the check report (section 10) contains any finding
with code `first_pass_unselected` or `selected_missing`. The manifest is still
written so the caller can see what failed.

## 10. Check (`check.py`)

`check_review(review, root) -> CheckReport`. The report is a list of
`Finding(code, severity, slot, candidate, message)` records, so callers branch
on `code`, never on message text. Codes:

| Code | Severity | Meaning |
|---|---|---|
| `missing_file` | error | Candidate path does not exist under root. |
| `selected_missing` | error | The slot's selected candidate is a `missing_file`. Emitted in addition to `missing_file`. |
| `unmatched_pack_folder` | warning | Candidate's first path component matches no pack `folder`. |
| `pack_mismatch` | warning | Candidate's `pack` is set but its folder belongs to a different pack. |
| `unused_pack` | warning | Pack referenced by no candidate. |
| `first_pass_unselected` | warning | `first_pass` slot whose status is `unselected` or `rejected`. |
| `first_pass_gap` | warning | `first_pass` slot with no candidates. |

`check` exits 1 if any finding has severity `error`. The CLI prints one line
per finding as `<severity> <code> <slot>[/<candidate>]: <message>`. The GUI
runs the same function on open and after every library rescan, shows counts
in the status bar ("2 missing files, 12 first-pass slots unselected") and uses
`missing_file` findings to mark rows and tree glyphs.

## 11. Library index (`library.py`)

`AudioLibrary(root)` walks `root` once at startup and holds a sorted list of
relative paths whose suffix is in `{.wav, .ogg, .mp3, .flac}` (case-insensitive).
Hidden directories (leading `.`) are skipped.

- `search(query) -> list[str]`: case-insensitive; the query is split on
  whitespace and every term must appear as a substring of the relative path.
  Results capped at 500, sorted by path.
- `pack_folder(rel_path) -> str`: first path component.
- `refresh()`: rescan (menu action, for when files are added while the tool is open).

The scan runs on the main thread before the window shows. For a library of a
few tens of thousands of files this is well under a second; no threading in v1.

## 12. Player (`player.py`)

`Player(QObject)` wraps one `QMediaPlayer` + `QAudioOutput`. It knows only
about file paths; which *candidate* is being auditioned is the UI's concern
(section 13.6), because two candidates may point at the same file.

State is the enum `PlayerState = {STOPPED, PLAYING, PAUSED}`, a direct map of
`QMediaPlayer.PlaybackState`.

- `play(path: Path)`: sets the source and plays from position 0. Calling it
  with the current source restarts from 0.
- `stop()`: to `STOPPED`, position reset to 0, source kept so `resume` can
  replay it.
- `pause()` / `resume()` / `toggle_pause()`: `PLAYING`↔`PAUSED`. `resume` in
  `STOPPED` with a source loaded plays it from 0; with no source it is a no-op.
- `seek(ms: int)`: `setPosition`, clamped to `[0, duration]`. No-op when the
  source is not seekable.
- `seekable -> bool` (Qt's `seekable` property) and signal `seekable_changed(bool)`.
  The transport disables its slider while false.
- `set_loop(bool)`: `QMediaPlayer.Loops.Infinite` / `Once`; Qt applies it live
  to the current track.
- `set_volume(float 0..1)`.
- `state -> PlayerState`, `source -> Path | None`, `position_ms`, `duration_ms`.
- Signals: `state_changed(PlayerState)`, `position_changed(ms, duration_ms)`,
  `source_changed(Path | None)`, `seekable_changed(bool)`, `error(text)`.

End of track with loop off: Qt reaches `EndOfMedia` and `StoppedState`; the
wrapper emits `state_changed(STOPPED)` and leaves the source loaded, so Space
replays it. With loop on, the track restarts and no state change is emitted.

Errors: `QMediaPlayer.errorOccurred` is forwarded as `error("<file name>:
<Qt error string>")`, the wrapper calls `stop()` and clears the source
(`source_changed(None)`), and nothing raises. The UI shows the text in the
status bar and, for the row that was playing, in the row's tooltip until the
next play attempt.

Ownership: there is exactly one `Player`, created by `MainWindow` and passed
to the panel and to `AddCandidateDialog`. Whoever calls `play` last wins;
there is no queue.

The UI depends on the `Player` interface only, so tests substitute a fake.

## 13. GUI

### 13.1 Main window

`QMainWindow`, title `"<project> — <review file name> — Audio Picker"` with a
leading `•` while unsaved changes exist (they exist for at most the autosave
delay). A `QSplitter`: slot tree on the left (about 30%), slot panel on the
right. Status bar shows the last message (autosave time, player errors, check
summary). Window geometry and the last opened file are remembered with
`QSettings("audio-picker", "audio-picker")`.

Menu bar:

- File: Open… (Ctrl+O), Save now (Ctrl+S), Export manifest… (runs `export`
  to a chosen file), Rescan library, Quit.
- Slot: Add slot… (Ctrl+N), Edit slot… (Ctrl+E), Remove slot, Next slot
  (Ctrl+Down), Previous slot (Ctrl+Up).
- Candidate: Add candidate… (Ctrl+Shift+N), Remove candidate.
- Help: Keyboard shortcuts (a dialog listing section 13.6).

### 13.2 Slot tree (`slot_tree.py`)

`QTreeView` on a `QStandardItemModel` with one top-level item per category (in
`categories` order, then any unlisted ones alphabetically), and one child per
slot in file order. Child text: `slot id`, with two decorations: a status glyph
in a fixed-width prefix (`○` unselected, `●` selected, `⊘` rejected, `△` gap;
`✕` overrides any of these when the slot has a `missing_file` finding) and the
priority as a dimmed suffix (`first pass`, `later`, `optional`). Categories
are expanded by default.

Above the tree, a toolbar: a search `QLineEdit` (matches slot id, function and
category, substring, case-insensitive), a priority `QComboBox` (All /
First pass / Later / Optional) and a status `QComboBox` (All / Unselected /
Selected / Rejected / Gaps / Missing files). Filtering hides non-matching
slots and any category left empty. Category rows are not selectable.

Changing the current slot, by any means (mouse click, keyboard navigation in
the tree, `Ctrl+Up`/`Ctrl+Down`, or a filter change that removes the current
slot), first flushes pending edits (13.8), then calls `player.stop()`, then
rebuilds the panel for the new slot.

The tree re-reads status glyphs after any model change (a single
`refresh_slot(slot_id)` call keeps it cheap).

### 13.3 Slot panel (`slot_panel.py`)

Top: slot header, read-only labels for `id`, category, priority, function, and
notes, with an "Edit…" button that opens `SlotEditorDialog` and a small "clear
selection" link that sets `selected` back to `null`. Read-only here
deliberately: inline editing of the header competes with the single-key
shortcuts.

Middle: a `QScrollArea` holding one `CandidateRow` per candidate in file order,
numbered 1..n. Below the rows, an "Add candidate…" button. For a gap slot the
area shows the slot notes and the add button only.

Bottom: `TransportBar`.

### 13.4 Candidate row (`candidate_row.py`)

Layout (one row, wraps to a second line for the text fields):

```
[3] Eastern Koto Intensity 1.wav       Eastern Music · alternative     ▶ Play   Yay  Nay   ◉ Selected   Remove
    why: Koto-led title and lower-intensity variant …
    listen for: Instrumentation, intensity and repeat fatigue …
    proposed use: Loop after seam review; choose instead of A002
    notes: [ QPlainTextEdit, two lines tall, grows ]
```

- The number is the shortcut key. Rows beyond 9 have no key.
- File name is the basename; the full relative path is the tooltip. If the file
  is missing the name is red, the tooltip says so, and Play is disabled.
- Play toggles to Stop while this row's candidate is the one playing (matched
  by candidate id, not file path). The playing row gets a subtle highlighted
  background.
- Yay and Nay are two checkable `QPushButton`s that are *not* in an exclusive
  group. The model owns the state: a click calls `mutate` with the new
  decision (`yay` if Yay was clicked and the decision was not already `yay`,
  else `unreviewed`; likewise for Nay), and the row then re-syncs both
  buttons' checked state from the model. This gives click-to-clear, which an
  exclusive `QButtonGroup` cannot do (Qt disallows unchecking the checked
  button in an exclusive group). Marking `nay` on the selected candidate
  clears `selected` (5.8) and the row's radio updates accordingly.
- Selected is a `QRadioButton`; the radios of a slot share one group. Picking
  one runs the selection mutation in 5.8. The radio is disabled while the
  candidate is `nay`.
- Notes: every `textChanged` calls `mutate` immediately, so the model is never
  behind the editor. Only the disk write is debounced (13.8). A mutation that
  originates from a row never rebuilds the panel; the row re-syncs its own
  widgets and the tree refreshes the slot's glyph. Editor focus, cursor and
  scroll position are therefore untouched.
- Remove asks for confirmation ("Remove A003 from exploration_loop?"). If it
  was selected, `selected` becomes `null`. If it was playing, playback stops.

### 13.5 Transport bar (`transport_bar.py`)

`▶/⏸`, `■`, now-playing candidate id and file name, position `QSlider`,
elapsed / total time, Loop `QCheckBox`, Volume `QSlider`. Loop and volume
persist in `QSettings`. Loop is a global auditioning preference, not per
candidate.

The slider calls `player.seek(ms)` on `sliderMoved` and on click; it is
disabled while `player.seekable` is false and while state is `STOPPED` with no
source. While the user drags, `position_changed` updates are not applied to
the slider (guard with `isSliderDown()`), so it does not fight the hand. `▶/⏸`
maps to `toggle_pause` (or `resume` from `STOPPED`); `■` maps to `stop`.

### 13.6 Keyboard

Shortcuts are `QAction`s on the main window with `Qt.WindowShortcut` context,
and are suppressed while a text field has focus except the Ctrl combinations.
Press Escape in a text field to return focus to the slot tree.

| Key | Action |
|---|---|
| `1`–`9` | Play candidate N. Pressing the key of the playing candidate stops it. |
| `Space` | Pause / resume; if nothing loaded, play candidate 1. |
| `S` | Stop. |
| `L` | Toggle loop. |
| `Y` / `N` | Mark the *active* candidate yay / nay (toggle off if already set). |
| `Enter` | Select the active candidate for the slot (5.8). If it is `nay`, nothing changes and the status bar says why. |
| `Ctrl+Down` / `Ctrl+Up` | Next / previous slot in the filtered tree, wrapping. Stops playback. |
| `Ctrl+F` | Focus the slot search box. |
| `Ctrl+S` | Save now. |
| `Ctrl+N`, `Ctrl+Shift+N`, `Ctrl+E` | Add slot, add candidate, edit slot. |

The *active* candidate is tracked by the panel as a candidate id (never a file
path, since candidates may share files): it is the one playing, else the last
one played in this slot, else candidate 1. It resets on every slot change.
The active row shows a thin left border so `Y`/`N`/`Enter` have an obvious
target. Pressing a number key sets the active id first, then calls
`player.play(path)`.

### 13.7 Dialogs (`dialogs.py`)

**AddCandidateDialog.** A search box over `AudioLibrary.search`, a results
`QListView` showing the relative path with the pack folder bold, a "Preview"
button (uses the shared `Player`), a "Browse…" button opening a native
`QFileDialog` rooted at `root` (a file outside root is rejected with a message),
a role combo (default `alternative`) and a `why` line edit. OK adds the
candidate with the next free id (`A` + max existing number + 1, zero-padded to
three digits, e.g. `A070`), `pack` inferred by matching the first path
component against pack folders (`null` if none), `decision` `unreviewed`, and
the other text fields empty. If the pack is `null` the status bar says so;
packs are added by editing the JSON for now (see section 17). Opening the
dialog stops whatever the panel was playing; closing it by OK or Cancel calls
`player.stop()` so a preview never outlives the dialog.

**SlotEditorDialog.** Used for both add and edit: id (`QLineEdit`, validated
snake_case and unique, disabled when editing an existing slot), category
(editable combo seeded from `categories`; a new value is appended to
`categories`), function, priority combo, notes. OK applies; Cancel discards.

**Remove confirmations.** `QMessageBox.question`, default button No.

### 13.8 Autosave and file safety

**Model first, disk later.** Every mutation goes through
`MainWindow.mutate(fn, *, slot_id, rebuild_panel=False)`. It applies `fn` to
the `Review` synchronously, refreshes the tree glyph for `slot_id`, rebuilds
the panel only when `rebuild_panel` is true (add/remove candidate, slot edit,
slot change), marks dirty and restarts a 500 ms single-shot save timer. The
model is therefore always current; the only thing that lags is the file.

**Flush points.** `flush()` cancels the timer and saves immediately if dirty.
It is called before: opening another review, exporting a manifest, running
the CSV importer from the GUI (not offered in v1, listed for completeness),
changing the current slot, and quitting. `Ctrl+S` is `flush()`. Because
notes commit on every keystroke, a flush never leaves editor text unsaved.

**Atomic write.** `model.save` writes `<file>.tmp` in the same directory and
`os.replace`s it over the original. After a successful write the window
records the file's new size and mtime and a SHA-256 of the bytes written.

**External change detection.** Before every write (timer or flush), the
window compares the file's current size and mtime with the recorded ones; on
mismatch it hashes the file and compares to the recorded hash. If the file
really changed since the last load/save (someone edited packs in a text
editor, or a git checkout happened), the write is *not* performed and a
modal dialog offers: "Reload from disk (discard my unsaved changes)",
"Overwrite the file with my changes", "Cancel". Reload re-runs `load`; a
`ReviewError` there keeps the in-memory model and reports the error. The
dialog appears at most once per detected change; Cancel keeps dirty set and
the timer stopped until the next mutation or flush. This is conflict
*detection*, not merging.

**Failures.** A save failure (permissions, disk) shows a modal error and keeps
the dirty flag; quitting with a failed or cancelled save asks for
confirmation ("Quit without saving?").

If `load` raises `ReviewError`, the GUI shows the message in a dialog and exits
with code 1. It never "repairs" a file.

## 14. Module interfaces

```python
# model.py
@dataclass class Pack: name: str; folder: str; license: str
@dataclass class Candidate: id: str; path: str; pack: str | None; role: str; why: str;
                            listen_for: str; proposed_use: str; decision: str; notes: str
@dataclass class Slot: id: str; category: str; function: str; priority: str; notes: str;
                       selected: str | None; candidates: list[Candidate]
    def status(self) -> Literal["gap", "selected", "rejected", "unselected"]
    def candidate(self, cid: str) -> Candidate | None
    def set_decision(self, cid: str, decision: str) -> None   # applies 5.8 (nay clears selected)
    def select(self, cid: str) -> None                        # applies 5.8 (refuses nay, promotes unreviewed to yay)
@dataclass class Review: version: int; project: str; root: str; categories: list[str];
                         packs: dict[str, Pack]; slots: list[Slot]
    def slot(self, sid: str) -> Slot | None
    def next_candidate_id(self, prefix: str = "A") -> str
    def all_candidate_ids(self) -> set[str]
class ReviewError(Exception): ...
def load(path: Path) -> Review            # raises ReviewError
def save(review: Review, path: Path) -> None   # atomic, canonical order
def to_dict(review: Review) -> dict       # canonical key order
def from_dict(data: dict) -> Review       # full validation
PRIORITIES = ("first_pass", "later", "optional")
ROLES = ("first", "alternative", "variation", "reference")
DECISIONS = ("unreviewed", "yay", "nay")
AUDIO_SUFFIXES = {".wav", ".ogg", ".mp3", ".flac"}

# csv_import.py
def import_csv(csv_path: Path, root: Path, project: str, warn: Callable[[str], None]) -> Review

# export.py
def build_manifest(review: Review, root: Path, now: datetime) -> dict
def first_pass_unselected(review: Review) -> list[str]

# check.py
@dataclass class Finding: code: str; severity: Literal["error", "warning"]; slot: str;
                          candidate: str | None; message: str
@dataclass class CheckReport:
    findings: list[Finding]
    def has(self, *codes: str) -> bool
    def errors(self) -> list[Finding]

def check_review(review: Review, root: Path) -> CheckReport

# player.py (Qt)
class PlayerState(Enum): STOPPED, PLAYING, PAUSED
class Player(QObject):
    def play(self, path: Path) -> None
    def stop(self) -> None
    def pause(self) -> None
    def resume(self) -> None
    def toggle_pause(self) -> None
    def seek(self, ms: int) -> None
    def set_loop(self, on: bool) -> None
    def set_volume(self, v: float) -> None
    state: PlayerState; source: Path | None; seekable: bool; position_ms: int; duration_ms: int
    state_changed: Signal(PlayerState); position_changed: Signal(int, int)
    source_changed: Signal(object); seekable_changed: Signal(bool); error: Signal(str)

# library.py
class AudioLibrary:
    def __init__(self, root: Path) -> None
    def refresh(self) -> None
    def search(self, query: str, limit: int = 500) -> list[str]
    @staticmethod def pack_folder(rel_path: str) -> str
```

## 15. Testing

Pure-Python layers are tested with `pytest` and no Qt import:

- `test_model.py`: round-trip `load`/`save` of `examples/review.json` is
  byte-identical; every validation rule in 5.6 has a failing fixture
  (including absolute, empty and `..` paths, and a selected `nay` candidate);
  all four `status()` values; the 5.8 rules via `set_decision`/`select`;
  `next_candidate_id` with gaps in numbering and with ids of different widths.
- `test_paths.py`: root resolution precedence; `to_relative` outside root
  returns `None`; `..` after normalisation is rejected; forward slashes on
  Windows-style input.
- `test_csv_import.py`: the fixture CSV (a 12-row cut of the real one
  including a two-candidate slot and a gap row) imports to an expected JSON;
  each warning case produces its warning; each error case raises: outside-root
  path, empty path on a non-gap row, unknown priority/choice/decision, and two
  pack names that slugify to one id.
- `test_export.py`: manifest content for a review with a selection, an
  unselected first-pass slot, a rejected slot and a gap; `--strict` fails on
  `first_pass_unselected` and on `selected_missing`.
- `test_check.py`: one test per finding code in section 10; `check` exit code
  is driven by severity, not message text.
- `test_library.py`: index built from `tests/fixtures/audio`; multi-term search;
  suffix filter; hidden directory skipped.

UI smoke test with `pytest-qt` (`test_ui_smoke.py`), `Player` replaced by a
fake recording calls: window opens on the example file; selecting a slot renders
the right number of rows; pressing `2` plays the second candidate's absolute
path; `Y` sets its decision; `Enter` selects it; the autosave timer fires and
the file on disk reflects the change; `Ctrl+Down` moves to the next slot and
the fake player records a `stop`; a mouse click on another slot also records
a `stop`; typing `y` into a focused notes field does not change any decision.

Pending-edit safety tests (same file): type into notes and, with no wait,
(a) press `Ctrl+S`, (b) trigger Export, (c) click another slot, (d) close the
window; in each case the file on disk contains the typed text. Also: typing
into notes does not move the editor's cursor or reset the panel's scroll
position (assert on `textCursor().position()` and the scroll bar value).

Yay/Nay tests: click Yay twice and the decision returns to `unreviewed`; click
Yay then Nay and it is `nay` with only Nay checked; mark the selected
candidate Nay and `selected` becomes `null` and its radio is disabled.

External-change tests: after load, rewrite the file on disk with different
bytes, mutate, let the timer fire, and assert the file is untouched and the
conflict dialog was requested (dialog factory mocked); choose Reload and the
model matches the disk; choose Overwrite and the disk matches the model.

Manual acceptance, implementation step 1 (section 18): through the bare
`Player` harness, play one `.wav`, one `.ogg`, one `.mp3` and one `.flac` from
the real library on this Windows machine and confirm sound, seeking, pause and
resume, and looping. Record the Python and PySide6 versions that passed in the
README. This is the only external risk in the project (section 16) and it is
retired before any other code is written.

## 16. Risks

- **Codec backend.** If the FFmpeg backend is somehow unavailable, OGG will not
  play on Windows. Mitigation is the `QT_MEDIA_BACKEND` default plus the
  step-1 check on all four formats. Fallback if it ever fails: decode with
  `soundfile` into a `QAudioSink`. Not built unless needed.
- **Manual JSON edits colliding with autosave.** Packs are edited by hand in
  v1, so a text editor and the GUI may hold the same file. The size/mtime/hash
  check before every write (13.8) turns a silent overwrite into a choice.
  Editors that write in place without changing size within the same second
  are caught by the hash; the timestamp/size check only avoids hashing on the
  common path.
- **Large libraries.** The synchronous scan and the 500-result cap keep the add
  dialog responsive; if a library exceeds roughly 100k files, move the scan to a
  `QThread`. Not expected.
- **Single-key shortcuts vs. text fields.** Handled by focus-aware suppression
  and Escape to leave a field; the smoke test covers it.

## 17. Deferred to a later version

- Editing packs in the GUI (add pack, set license). Today: edit the JSON.
- Waveform display and loop-seam preview (A/B at a chosen offset).
- Copy/convert step driven by the manifest.
- Multiple candidate id prefixes per review.

## 18. Implementation order

1. **Codec check.** `pyproject.toml`, package skeleton, `player.py`, and a
   throwaway harness (`python -m audio_picker.player FILE...`) that opens a
   minimal window with play/pause/stop/seek/loop controls. Run the manual
   acceptance from section 15 on WAV, OGG, MP3 and FLAC from the real
   library. Record the passing Python and PySide6 versions in the README and
   pin PySide6's lower bound to the version that passed. If any format fails,
   stop and decide (drop the format from `AUDIO_SUFFIXES`, or build the
   `soundfile` fallback) before continuing.
2. `model.py` with load/save/validation and tests, `examples/review.json`.
3. `paths.py`, `library.py`, `check.py`, tests.
4. `csv_import.py` with the fixture and tests; run it against the real
   `one-more-turn` CSV and commit the resulting `docs/audio/audio-review.json`
   in that repo (root `../../vendor/audio`).
5. `export.py` and `cli.py` with all subcommands; tests.
6. `ui/`: main window with tree and panel read-only; then transport and
   shortcuts; then yay/nay/select/notes mutations with autosave, flush points
   and external-change detection; then dialogs.
7. `test_ui_smoke.py`, README with the commands from section 3 and the shortcut
   table from 13.6.

## Appendix A. Facts about the first data set

Recorded so the importer can be tested against reality:

- `docs/audio/audio-candidate-review.csv` in `one-more-turn`: 69 rows, 54
  slots, 16 columns, UTF-8 with BOM.
- Candidates per slot: 1 or 2. Three rows are gap rows (`A067`–`A069`,
  priority `Gap`, category `Unfilled`, empty path).
- Every source path is absolute under `D:\Projects\one-more-turn\vendor\audio\`
  with backslashes. Suffixes: 39 wav, 18 ogg, 9 mp3.
- Eight packs, each with exactly one license string and one top-level folder.
- `Listen for` and `Proposed use after approval` differ between candidates of
  the same slot in most two-candidate slots, which is why they are candidate
  fields.
- `Assessment` has two values only, both boilerplate.
- No decisions recorded; the `Decision` column is empty throughout.
