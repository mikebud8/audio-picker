"""The one Qt object between the pure annotations store and its hosts (spec section 3.5).

Hosts call `notify_changed` after every write and subscribe to `changed`
and `reloaded`. The hub owns the debounced save; the window that created
the hub shows `save_failed`.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from ..annotations import AnnotationsError, LibraryAnnotations

AUTOSAVE_MS = 500


class AnnotationHub(QObject):
    changed = Signal(str)  # a host wrote this relative path to the store
    reloaded = Signal()  # store replaced or re-read, or the library index changed: re-read everything
    save_failed = Signal(str)  # message for the owning window to show

    def __init__(self, store: LibraryAnnotations, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTOSAVE_MS)
        self._timer.timeout.connect(self._autosave)

    def notify_changed(self, rel: str) -> None:
        """Call after every write to the store."""
        self._timer.start()
        self.changed.emit(rel)

    def set_store(self, store: LibraryAnnotations) -> None:
        """Swap in the store for another root. The old one must already be settled or discarded."""
        self._timer.stop()
        self.store = store
        self.reloaded.emit()

    def reload(self) -> str:
        """Rescan hook: re-read the sidecar unless dirty; always emit `reloaded`. Returns a status fragment."""
        if self.store.dirty:
            text = "library notes not reloaded (unsaved edits)"
        else:
            try:
                self.store.reload()
            except AnnotationsError:
                pass  # recorded in store.load_error; the store is empty and read_only
            text = "library notes not loaded" if self.store.read_only else "library notes reloaded"
        self.reloaded.emit()
        return text

    def _autosave(self) -> None:
        if self.store.dirty:
            self.save()

    def save(self) -> bool:
        """Write if dirty. False means the sidecar is still unsaved and `save_failed` was emitted."""
        if not self.store.dirty or self.store.read_only:
            return True
        try:
            self.store.save()
        except OSError as e:
            self._timer.stop()
            self.save_failed.emit(f"Could not write library notes to {self.store.path}:\n{e}")
            return False
        return True

    def flush(self) -> bool:
        self._timer.stop()
        return self.save()
