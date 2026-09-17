"""Left-hand grouped slot list with filters (design section 13.2)."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPalette, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..model import Review, Slot

GLYPHS = {"unselected": "○", "selected": "●", "rejected": "⊘", "gap": "△"}
MISSING_GLYPH = "✕"
PRIORITY_LABELS = {"first_pass": "first pass", "later": "later", "optional": "optional"}
PRIORITY_FILTERS = [("All", None), ("First pass", "first_pass"), ("Later", "later"), ("Optional", "optional")]
STATUS_FILTERS = [
    ("All", None),
    ("Unselected", "unselected"),
    ("Selected", "selected"),
    ("Rejected", "rejected"),
    ("Gaps", "gap"),
    ("Missing files", "missing"),
]
SLOT_ROLE = Qt.ItemDataRole.UserRole + 1


class SlotTree(QWidget):
    current_slot_changed = Signal(str)  # slot id, or "" when nothing is current

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._review: Review | None = None
        self._missing: set[str] = set()
        self._items: dict[str, tuple[QStandardItem, QStandardItem]] = {}
        self._current: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 4, 8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search slots (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Matches slot id, function and category")
        self.search.textChanged.connect(lambda _t: self.rebuild())
        layout.addWidget(self.search)

        filters = QHBoxLayout()
        self.priority_filter = QComboBox()
        for label, _v in PRIORITY_FILTERS:
            self.priority_filter.addItem(label)
        self.priority_filter.setToolTip("Priority")
        self.status_filter = QComboBox()
        for label, _v in STATUS_FILTERS:
            self.status_filter.addItem(label)
        self.status_filter.setToolTip("Status")
        self.priority_filter.currentIndexChanged.connect(lambda _i: self.rebuild())
        self.status_filter.currentIndexChanged.connect(lambda _i: self.rebuild())
        filters.addWidget(self.priority_filter, 1)
        filters.addWidget(self.status_filter, 1)
        layout.addLayout(filters)

        self.model = QStandardItemModel(0, 2, self)
        self.view = QTreeView()
        self.view.setModel(self.model)
        self.view.setHeaderHidden(True)
        self.view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.view.setUniformRowHeights(True)
        self.view.setExpandsOnDoubleClick(False)
        self.view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.view.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.view.header().setStretchLastSection(False)
        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        layout.addWidget(self.view, 1)

    # -- data ------------------------------------------------------------------

    def set_review(self, review: Review, missing: set[str]) -> None:
        self._review = review
        self._missing = set(missing)
        self.rebuild()

    def set_missing(self, missing: set[str]) -> None:
        self._missing = set(missing)
        for sid in self._items:
            self.refresh_slot(sid)

    def refresh_slot(self, slot_id: str) -> None:
        pair = self._items.get(slot_id)
        if pair is None or self._review is None:
            return
        slot = self._review.slot(slot_id)
        if slot is not None:
            pair[0].setText(f"{self.glyph_for(slot_id)} {slot.id}")
            pair[1].setText(PRIORITY_LABELS.get(slot.priority, slot.priority))

    def glyph_for(self, slot_id: str) -> str:
        if slot_id in self._missing:
            return MISSING_GLYPH
        slot = self._review.slot(slot_id) if self._review else None
        return GLYPHS[slot.status()] if slot else ""

    def _matches(self, slot: Slot) -> bool:
        query = self.search.text().strip().lower()
        if query and not any(query in field.lower() for field in (slot.id, slot.function, slot.category)):
            return False
        priority = PRIORITY_FILTERS[self.priority_filter.currentIndex()][1]
        if priority and slot.priority != priority:
            return False
        status = STATUS_FILTERS[self.status_filter.currentIndex()][1]
        if status == "missing":
            return slot.id in self._missing
        if status and slot.status() != status:
            return False
        return True

    def rebuild(self) -> None:
        previous = self._current
        self._items = {}
        self.model.removeRows(0, self.model.rowCount())
        if self._review is None:
            return
        review = self._review
        listed = list(review.categories)
        extras = sorted({s.category for s in review.slots} - set(listed))
        dim = QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText) or QColor("gray"))
        for category in listed + extras:
            slots = [s for s in review.slots if s.category == category and self._matches(s)]
            if not slots:
                continue
            cat_item = QStandardItem(category)
            cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = cat_item.font()
            font.setBold(True)
            cat_item.setFont(font)
            cat_pad = QStandardItem("")
            cat_pad.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for slot in slots:
                name = QStandardItem(f"{self.glyph_for(slot.id)} {slot.id}")
                name.setData(slot.id, SLOT_ROLE)
                name.setToolTip(slot.function)
                prio = QStandardItem(PRIORITY_LABELS.get(slot.priority, slot.priority))
                prio.setForeground(dim)
                prio.setData(slot.id, SLOT_ROLE)
                for item in (name, prio):
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                cat_item.appendRow([name, prio])
                self._items[slot.id] = (name, prio)
            self.model.appendRow([cat_item, cat_pad])
        self.view.expandAll()

        visible = self.slot_ids()
        if previous in visible:
            self.select_slot(previous)
        elif visible:
            self.select_slot(visible[0])
        else:
            self._current = None
            self.current_slot_changed.emit("")

    # -- navigation --------------------------------------------------------------

    def slot_ids(self) -> list[str]:
        """Visible slot ids in display order."""
        ids: list[str] = []
        for r in range(self.model.rowCount()):
            cat = self.model.item(r, 0)
            for c in range(cat.rowCount()):
                ids.append(cat.child(c, 0).data(SLOT_ROLE))
        return ids

    def current_slot_id(self) -> str | None:
        return self._current

    def index_for_slot(self, slot_id: str) -> QModelIndex:
        pair = self._items.get(slot_id)
        return pair[0].index() if pair else QModelIndex()

    def select_slot(self, slot_id: str) -> None:
        index = self.index_for_slot(slot_id)
        if index.isValid():
            self.view.setCurrentIndex(index)
            self.view.scrollTo(index)

    def next_slot(self) -> None:
        self._step(1)

    def previous_slot(self) -> None:
        self._step(-1)

    def _step(self, delta: int) -> None:
        ids = self.slot_ids()
        if not ids:
            return
        if self._current in ids:
            i = (ids.index(self._current) + delta) % len(ids)
        else:
            i = 0
        self.select_slot(ids[i])

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        slot_id = current.data(SLOT_ROLE) if current.isValid() else None
        if not slot_id:
            return  # a category row: keep the previous slot current
        if slot_id != self._current:
            self._current = slot_id
            self.current_slot_changed.emit(slot_id)
