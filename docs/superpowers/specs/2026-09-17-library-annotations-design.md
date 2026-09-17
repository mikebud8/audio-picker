# Library annotations design

Date: 2026-09-17. Status: approved for planning.

Extends `docs/audio-picker-design.md`. Section numbers there are referenced
as "design 13.7" and so on.

## 1. Purpose

Give the tool a sense of organisation over the audio library beyond folder
structure, without editing, renaming or moving any file on disk. Each audio
file can carry a quality rating, a set of tags and a note. The data is
library-wide, not per project, so it stays useful when the same packs are
reused for a new game.

The review loop (slots, candidates, decisions, autosave, export) is not
changed. The feature is additive: a reusable editor widget hosted in three
places, and a sidecar data file.

## 2. Non-goals (phase one)

- Bulk operations: multi-select, apply tag to selection, apply tag to a
  folder. Phase two.
- Tag or rating filters in the Add Candidate search. Phase three.
- Keyboard shortcuts for rating or tagging.
- External change detection on the sidecar file.
- Content hashing to survive renames. Keys are paths; orphans are kept, not
  repaired.
- Any change to the review file format.

## 3. Data (`annotations.py`)

Pure Python, no Qt import, alongside `model.py`.

### 3.1 Sidecar file

One file per audio root: `<root>/audio-picker-library.json`.

```json
{
  "version": 1,
  "tags": ["click", "hit", "loopable", "metallic", "ui", "whoosh"],
  "files": {
    "kenney-ui-audio/Audio/click_001.ogg": {
      "rating": 4,
      "tags": ["click", "ui"],
      "note": "Clean, very short. Pair with click_002 for release."
    }
  }
}
```

- `version`: integer, 1.
- `tags`: the vocabulary, sorted, used for autocomplete. It is the union of
  every tag in use plus any tag ever committed, so a tag survives removal from
  its last file.
- `files`: keyed by relative forward-slash path, the same form as
  `Candidate.path` (design 6), so a candidate path and an annotation key
  compare by string equality. Written sorted by key.
- `rating`: integer 1 to 5, or absent. Absent means unrated. 1 means junk.
  The rating is recording quality, not preference.
- `tags`: sorted list of normalised tags. Normalisation: strip, lowercase,
  internal whitespace collapsed to `-`. Empty after normalisation is
  rejected. Duplicates on one file collapse.
- `note`: string, may contain newlines. Absent and `""` are equivalent.
- An entry with no rating, no tags and an empty note is dropped on save.
- Written with two-space indent, LF line endings, trailing newline, through
  `<file>.tmp` and `os.replace`, as `model.save` does.

### 3.2 Loading

- Missing file: empty store, not an error.
- Malformed file (bad JSON, wrong version, unknown top-level keys, key that is
  absolute or contains `..`, rating outside 1 to 5, tag that does not
  normalise to itself): raise `AnnotationsError` naming the problem. The
  caller decides what to do; the GUI behaviour is in section 6.
- Keys whose file no longer exists under the root are orphans. They load
  normally and are never removed automatically.

### 3.3 In-memory API

```python
@dataclass
class Annotation:
    rating: int | None = None
    tags: list[str] = field(default_factory=list)
    note: str = ""

class LibraryAnnotations:
    def __init__(self, root: Path) -> None          # loads or starts empty
    path: Path                                     # the sidecar path
    dirty: bool
    read_only: bool                                # true after a failed load
    def get(self, rel: str) -> Annotation          # copy; empty if unknown
    def set_rating(self, rel: str, rating: int | None) -> None
    def add_tag(self, rel: str, tag: str) -> str    # returns normalised tag
    def remove_tag(self, rel: str, tag: str) -> None
    def set_note(self, rel: str, note: str) -> None
    def vocabulary(self) -> list[str]
    def files_with(self, tag: str) -> list[str]
    def min_rating(self, n: int) -> list[str]
    def annotated(self) -> list[str]               # every key, sorted
    def save(self) -> None                         # atomic; clears dirty
    def reload(self) -> None                       # re-read from disk

def normalise_tag(raw: str) -> str                 # raises ValueError if empty
```

Every mutator sets `dirty` and adds new tags to the vocabulary. Mutators
never write to disk; the hub (section 3.5) owns the save timer.

One `LibraryAnnotations` instance exists per root per process. It is
created where `AudioLibrary` is created today (`MainWindow.__init__` and the
root-switch path in "open another review") and wrapped in one hub that every
host shares, so all three views edit the same object.

### 3.5 Hub (`ui/annotation_hub.py`)

`AnnotationHub(QObject)` is the one Qt object between the pure store and its
hosts. It holds `store`, owns the 500 ms single-shot save timer, and has
three signals:

- `changed(str)`: a host wrote the given path to the store. Hosts call
  `notify_changed(rel)` after every write; the hub restarts the timer and
  emits. Every other host re-reads what it shows for that path, and the
  viewer re-applies its filters.
- `reloaded()`: the store was replaced (`set_store`) or re-read from disk
  (`reload`), or the library index changed. Hosts re-read everything.
- `save_failed(str)`: a save raised `OSError`; the owning window shows the
  message.

`flush() -> bool` stops the timer and saves if dirty; false means the file
is still unsaved. `reload() -> str` is the rescan hook: it re-reads the store
unless it is dirty, always emits `reloaded`, and returns a status fragment.

The window that created the hub owns it: the review window when launched
with a review, the library viewer when launched standalone. Other hosts
only call `notify_changed` and subscribe.

### 3.4 Search

`AudioLibrary.search(query, annotations=None)` gains an optional store. A
whitespace-separated term beginning with `#` matches files carrying that tag
(exact, after normalisation); other terms match the path as before. Every
term must match. With no store, `#` terms match nothing.

## 4. Annotation editor (`ui/annotation_editor.py`)

`AnnotationEditor(QWidget)`. Takes a `LibraryAnnotations` store. Knows
nothing about reviews, slots or the player. Sized to sit in a column about
260 px wide.

Layout, top to bottom:

- **Path line.** Relative path, elided in the middle, pack folder in bold
  using the same HTML style as `_PathDelegate` in `dialogs.py`. Tooltip is
  the full relative path. With no current path it reads "No file" and every
  control below is disabled.
- **Rating.** Five star buttons in a row. Click star N sets rating N.
  Clicking the star that is currently the rating clears it. A muted
  "unrated" label shows when none is set. Row tooltip: "Recording quality,
  not preference".
- **Tags.** A wrapping flow of chips, each with a remove cross. Below it a
  `QLineEdit` with a `QCompleter` over `vocabulary()`, case-insensitive,
  contains-match. Enter or a typed comma commits the text through
  `normalise_tag` and clears the field; an empty or duplicate tag is a
  no-op. Escape clears the field and returns focus to the host.
- **Note.** A `QPlainTextEdit`, four lines minimum, fills remaining height.
  Escape returns focus to the host.

Behaviour:

- `set_path(rel: str | None)` loads that file's annotation. It never emits
  `changed`.
- Every control change writes straight through to the store, then emits
  `changed(str)` with the path. There is no OK or Apply.
- `refresh()` re-reads the current path from the store, for hosts that
  changed it elsewhere.
- No single-key shortcuts. Rating is mouse only, so the review window's `1`
  to `9`, `Y`, `N`, `S`, `L` and Space keep their meaning. The tag field and
  the note are ordinary text fields, so the main window's rule of
  suppressing single keys while a text field has focus already covers them.

## 5. Hosts

### 5.1 Review window dock

A `QDockWidget` titled "Library notes", object name `libraryNotesDock`,
allowed on the right and bottom dock areas, default right, closable and
movable. Its editor follows the active candidate: on every change of the
panel's active candidate and on every slot change, `set_path` is called with
that candidate's `path`, or `None` when the slot has no candidates.

`SlotPanel` gains a signal `active_changed(object)` carrying `str | None`,
emitted from `_update_active` when the computed active id differs from the
last emitted one; the main window connects it to the dock. That is the only
change to an existing widget.

Dock state (visible, area, floating geometry) is saved with
`QMainWindow.saveState` under `window/state` in `QSettings` alongside the
existing geometry. First run: hidden, so the existing layout is unchanged
until the user turns it on. View menu gains "Library notes" bound to the
dock's `toggleViewAction()`.

Nothing else in the main window changes: no new keys, no change to playback,
decisions or review autosave.

### 5.2 Add Candidate dialog

`AddCandidateDialog` takes the hub as an extra argument. The layout becomes
a horizontal split: the existing column on the left, an `AnnotationEditor`
on the right over a muted hint "Notes are saved to the library even if you
cancel". Default size 920 by 480. The editor's path follows
`currentItemChanged` on the results list and `Browse…` when the chosen file
is under the root. Every edit calls `hub.notify_changed`, so the owning
window's timer saves while the dialog is still open; cancelling the
candidate never discards library notes. Search remains path-only plus
`#tag` terms from section 3.4, which come for free; the combo filters are
phase three.

### 5.3 Standalone library viewer (`ui/library_window.py`)

`LibraryWindow(QMainWindow)`, constructed with `root`, `library`, `hub`,
`player`, `settings`, and `owns_hub` and `owns_player` flags.

Opened two ways:

- `audio-picker library --root DIR`. No review file. Creates its own
  `AudioLibrary`, `LibraryAnnotations`, hub and `Player`; owns both.
- File menu, "Library viewer…" in the review window. Receives the review's
  root, library, hub and player; owns neither. The review window stops
  playback before showing it. Only one instance at a time; a second request
  raises the existing window.

Layout:

- Left: search `QLineEdit` (placeholder "Search paths, #tag for tags"), a
  tag combo ("Any tag" plus the vocabulary) and a min-rating combo ("Any",
  "1+" to "5"), then a `QListWidget` using `_PathDelegate`, moved to a shared
  `ui/path_delegate.py` so the dialog and the viewer import the same class.
  Each row shows the path, then in muted text the star count as `★4` and
  the tags joined by spaces. Rows for orphans (annotated but missing on
  disk) are appended greyed with tooltip "Missing on disk" when the search
  box is empty and no combo filter is set.
- Right: `AnnotationEditor`.
- Bottom: `TransportBar(player, settings)`.

Behaviour:

- Filters combine with AND: search terms, tag combo, min rating.
- The current row drives the editor. On every hub `changed`, from this
  window or any other host, the viewer recomputes the row list: if it
  differs from what is shown (a tag removed while filtering on it, a rating
  lowered below the threshold, an orphan cleared), the list is rebuilt
  keeping the current row where it still exists; otherwise only that row's
  summary is repainted. The tag combo is refreshed if the vocabulary grew.
  On hub `reloaded` the list, the tag combo and the editor are rebuilt from
  the current store and library index.
- Double-click or Space on a row plays it through the player; Space while
  that row is playing pauses and resumes; `S` stops. Enter is not bound.
  Single keys are suppressed while a text field has focus, using the same
  rule as the main window.
- Window geometry saved under `library_window/geometry`.
- Close: if it owns the hub, flush; on failure the unsaved-changes dialog
  from section 6 offers try again, discard and close, or cancel. Stops the
  player if it owns it.

Playback when opened from the review window shares the review's `Player`.
Both transport bars reflect the one player. During implementation, verify
that a library play does not disturb the review's playing-candidate
highlight (`_playing_cid` is `None` while the library plays, so
`_on_player_state` should treat it as nothing highlighted). If it does, the
viewer gets its own `Player` and each window stops the other's on play.

## 6. Persistence and errors

- **Save timer.** The hub owns a 500 ms single-shot timer, restarted by
  every `notify_changed`. The review window owns the hub when launched with
  a review; the library window owns it standalone.
- **Flush points.** Before the review window opens another review, when the
  standalone viewer closes, and on quit. `Ctrl+S` in the review window
  flushes the review and the sidecar. `MainWindow.flush()` returns true
  only when both files are saved.
- **Blocking on failure.** Quitting, closing the standalone viewer and
  opening another review first flush. If anything is still unsaved, one
  modal dialog names the files and offers "Try again", "Discard and
  <action>", and "Cancel" (default). Try again flushes once more and asks
  again on failure. This replaces the review's yes/no "Quit without
  saving?" question and closes the existing gap where opening another
  review after a failed review save silently dropped the changes.
- **One writer.** One store per process, so the three hosts never race.
  External change detection is not built for the sidecar in phase one.
  Known gap: a hand edit to the sidecar while the app is open is overwritten
  by the next save.
- **Rescan.** "Rescan library" rebuilds the path index and calls
  `hub.reload()`, which re-reads the sidecar if the store is not dirty so a
  deliberate hand edit is picked up, then emits `reloaded` either way so
  the dock and an open viewer refresh. If dirty, the status bar says the
  sidecar was not reloaded.
- **Save failure.** Modal error, dirty flag kept, same as the review.
- **Malformed sidecar at load.** The error is shown once in a dialog. The
  store starts empty in memory with `read_only` true. Every editor is
  disabled while the store is read-only, so nothing can be edited or lost,
  and a persistent status bar message reads "Library notes not loaded: fix
  audio-picker-library.json and rescan". Rescan retries the load and clears
  `read_only` on success, which re-enables the editors.
- **Root switch.** Opening another review with a different root settles
  unsaved changes as above, closes an open viewer, then replaces the
  library and the store together through `hub.set_store`, which re-points
  the dock.

## 7. Command line

`audio-picker library --root DIR` opens the standalone viewer. `--root` is
required. A missing or non-directory root exits 1 with a message on stderr,
matching `resolve_root` errors. Exit codes as in design 7.

## 8. Testing

- `tests/test_annotations.py`, no Qt: empty store from a missing file;
  round-trip of a fixture is byte-identical; `normalise_tag` cases (case,
  whitespace, empty raises); duplicate tags collapse; empty entries dropped
  on save; vocabulary survives tag removal; each malformed case raises
  `AnnotationsError`; atomic write leaves no `.tmp`; `files_with`,
  `min_rating`, `annotated`; `reload` picks up a disk change.
- `tests/test_library.py`: `#tag` term with and without a store; mixed path
  and tag terms.
- `tests/test_annotation_hub.py`: `notify_changed` emits and autosaves;
  `flush` reports failure through `save_failed`; `reload` refuses a dirty
  store but still emits `reloaded`; `set_store` stops the timer and emits.
- `tests/test_ui_smoke.py`: editor star click, tag commit and note edit
  write through and emit `changed`; clearing a rating by re-click; dock
  follows the active candidate across slot changes; dialog editor follows
  the highlighted result and its edits autosave while open; standalone
  window opens on the fixture root, filters by tag and by rating, plays a
  row, lists an orphan greyed, and drops a row whose tag or rating no longer
  matches the filter; an owned hub flushes on close and a failed flush asks
  try again / discard / cancel; a malformed sidecar disables every editor
  until rescan succeeds.
- `tests/test_screenshots.py`: review window with the dock open, the
  widened dialog, and the standalone viewer, light and dark.
- `tests/test_cli.py`: `library --root DIR` dispatch; missing root exits 1.
- `tests/fixtures/audio/` gains an `audio-picker-library.json` fixture with
  one rated, tagged file and one orphan.

## 9. Phasing

- **Phase one.** Everything above.
- **Phase two.** Multi-select in the standalone list; "Add tag to selection"
  and "Remove tag from selection"; pack folder rows with "Apply tag to
  folder". No data format change.
- **Phase three.** Tag combo and min-rating combo in the Add Candidate
  dialog, sharing the filter code with the viewer. No data format change.

## 10. Risks

- Dock save/restore with `saveState` interacts with the existing geometry
  restore; restore geometry first, then state, and test both a first run and
  a saved run.
- Chip flow layout has no stock Qt widget; a small `FlowLayout` from the Qt
  examples is needed. Keep it in `annotation_editor.py`.
- Sharing one `Player` between two windows is the one place this touches the
  review's playback. The fallback is stated in 5.3.
