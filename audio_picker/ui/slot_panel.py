"""Right-hand panel: slot header, candidate rows, add button (design section 13.3)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..model import Review, Slot
from .candidate_row import CandidateRow
from .theme import dim_css

PRIORITY_LABELS = {"first_pass": "first pass", "later": "later", "optional": "optional"}


class SlotPanel(QWidget):
    play_clicked = Signal(str)
    decision_clicked = Signal(str, str)
    select_clicked = Signal(str)
    notes_edited = Signal(str, str)
    remove_clicked = Signal(str)
    edit_slot_clicked = Signal()
    clear_selection_clicked = Signal()
    add_candidate_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.slot: Slot | None = None
        self._review: Review | None = None
        self._missing: set[str] = set()
        self._active: str | None = None
        self._playing: str | None = None
        self.rows: list[CandidateRow] = []
        self.radio_group = QButtonGroup(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 0)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        self.id_label = QLabel()
        self.id_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        self.id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta_label = QLabel()
        self.meta_label.setStyleSheet(dim_css())
        self.function_label = QLabel()
        self.function_label.setWordWrap(True)
        self.slot_notes = QLabel()
        self.slot_notes.setWordWrap(True)
        self.slot_notes.setStyleSheet(dim_css())
        title_col.addWidget(self.id_label)
        title_col.addWidget(self.meta_label)
        title_col.addWidget(self.function_label)
        title_col.addWidget(self.slot_notes)
        header.addLayout(title_col, 1)
        buttons_col = QVBoxLayout()
        self.edit_button = QPushButton("Edit…")
        self.edit_button.setToolTip("Edit id, category, priority, function and notes (Ctrl+E)")
        self.edit_button.clicked.connect(self.edit_slot_clicked)
        self.clear_selection = QPushButton("clear selection")
        self.clear_selection.setFlat(True)
        self.clear_selection.setToolTip("Set this slot back to no selected candidate")
        self.clear_selection.clicked.connect(self.clear_selection_clicked)
        buttons_col.addWidget(self.edit_button)
        buttons_col.addWidget(self.clear_selection)
        buttons_col.addStretch(1)
        header.addLayout(buttons_col)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._container = QWidget()
        self._rows_layout = QVBoxLayout(self._container)
        self._rows_layout.setContentsMargins(0, 4, 0, 4)
        self._rows_layout.setSpacing(6)
        self.gap_notes = QPlainTextEdit()
        self.gap_notes.setReadOnly(True)
        self.gap_notes.setPlaceholderText("This slot has no candidates yet.")
        self.gap_notes.setMaximumHeight(140)
        self._rows_layout.addWidget(self.gap_notes)
        self.empty_label = QLabel("No slot selected. Adjust the filters or add a slot (Ctrl+N).")
        self.empty_label.setStyleSheet(dim_css())
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rows_layout.addWidget(self.empty_label)
        self.add_button = QPushButton("Add candidate…")
        self.add_button.setToolTip("Search the library or browse for a file (Ctrl+Shift+N)")
        self.add_button.clicked.connect(self.add_candidate_clicked)
        self._rows_layout.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._rows_layout.addStretch(1)
        self.scroll.setWidget(self._container)
        layout.addWidget(self.scroll, 1)

        self.show_slot(None, None, set())

    # -- population ------------------------------------------------------------

    def show_slot(self, slot: Slot | None, review: Review | None, missing: set[str]) -> None:
        """Rebuild the rows for `slot`. Resets the active candidate."""
        self.slot = slot
        self._review = review
        self._missing = set(missing)
        self._active = None
        self._playing = None
        for row in self.rows:
            self.radio_group.removeButton(row.radio)
            self._rows_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.rows = []

        has_slot = slot is not None
        self.id_label.setVisible(has_slot)
        self.meta_label.setVisible(has_slot)
        self.function_label.setVisible(has_slot)
        self.slot_notes.setVisible(has_slot)
        self.edit_button.setVisible(has_slot)
        self.clear_selection.setVisible(has_slot)
        self.add_button.setVisible(has_slot)
        self.empty_label.setVisible(not has_slot)
        if slot is None:
            self.gap_notes.setVisible(False)
            return

        for i, candidate in enumerate(slot.candidates, 1):
            pack = (
                review.packs.get(candidate.pack).name
                if review and candidate.pack in (review.packs if review else {})
                else None
            )
            row = CandidateRow(i, candidate, pack, self.radio_group)
            row.play_clicked.connect(self.play_clicked)
            row.decision_clicked.connect(self.decision_clicked)
            row.select_clicked.connect(self.select_clicked)
            row.notes_edited.connect(self.notes_edited)
            row.remove_clicked.connect(self.remove_clicked)
            self._rows_layout.insertWidget(self._rows_layout.indexOf(self.add_button), row)
            self.rows.append(row)
        self.gap_notes.setVisible(not slot.candidates)
        self.refresh()
        self._update_active()
        self.scroll.verticalScrollBar().setValue(0)

    def refresh(self) -> None:
        """Re-sync header and rows from the model without rebuilding widgets."""
        slot = self.slot
        if slot is None:
            return
        self.id_label.setText(slot.id)
        self.meta_label.setText(f"{slot.category} · {PRIORITY_LABELS.get(slot.priority, slot.priority)}")
        self.function_label.setText(slot.function)
        self.slot_notes.setText(slot.notes)
        self.slot_notes.setVisible(bool(slot.notes) and bool(slot.candidates))
        self.clear_selection.setEnabled(slot.selected is not None)
        if not slot.candidates and self.gap_notes.toPlainText() != slot.notes:
            self.gap_notes.setPlainText(slot.notes)
        for row in self.rows:
            candidate = slot.candidate(row.cid)
            if candidate is not None:
                row.sync(candidate, selected=slot.selected == row.cid, missing=row.cid in self._missing)

    def set_missing(self, missing: set[str]) -> None:
        self._missing = set(missing)
        self.refresh()

    # -- playback state --------------------------------------------------------

    def row_for(self, cid: str) -> CandidateRow | None:
        return next((r for r in self.rows if r.cid == cid), None)

    def set_playing(self, cid: str | None) -> None:
        self._playing = cid
        if cid is not None:
            self._active = cid
        for row in self.rows:
            row.set_playing(row.cid == cid)
        self._update_active()

    def set_active(self, cid: str) -> None:
        self._active = cid
        self._update_active()

    def active_candidate_id(self) -> str | None:
        """Playing, else last played in this slot, else candidate 1."""
        if self._playing is not None:
            return self._playing
        if self._active is not None and self.row_for(self._active) is not None:
            return self._active
        return self.rows[0].cid if self.rows else None

    def _update_active(self) -> None:
        active = self.active_candidate_id()
        for row in self.rows:
            row.set_active(row.cid == active)
