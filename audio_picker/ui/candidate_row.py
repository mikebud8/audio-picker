"""One candidate widget (design section 13.4)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from ..model import Candidate
from .theme import dim_css, error_css

_ROW_STYLE = """
CandidateRow { border: 1px solid palette(mid); border-left: 3px solid transparent; border-radius: 4px; }
CandidateRow[active="true"] { border-left: 3px solid palette(highlight); }
CandidateRow[playing="true"] { background: palette(alternate-base); }
"""


class _GrowingNotes(QPlainTextEdit):
    """Two lines tall by default; grows with its content up to a cap."""

    MIN_LINES = 2
    MAX_LINES = 10

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("notes")
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.document().documentLayout().documentSizeChanged.connect(lambda _s: self._fit())
        self._fit()

    def _fit(self) -> None:
        lines = max(self.MIN_LINES, min(self.MAX_LINES, int(self.document().size().height()) or 1))
        fm = self.fontMetrics()
        margins = self.contentsMargins()
        height = (
            lines * fm.lineSpacing() + int(self.document().documentMargin()) * 2 + margins.top() + margins.bottom() + 4
        )
        self.setFixedHeight(height)


class CandidateRow(QFrame):
    play_clicked = Signal(str)  # cid
    decision_clicked = Signal(str, str)  # cid, "yay" | "nay"
    select_clicked = Signal(str)
    notes_edited = Signal(str, str)  # cid, text
    remove_clicked = Signal(str)

    def __init__(
        self, number: int, candidate: Candidate, pack_name: str | None, radio_group: QButtonGroup, parent=None
    ) -> None:
        super().__init__(parent)
        self.cid = candidate.id
        self.number = number
        self.missing = False
        self.is_playing = False
        self.is_active = False
        self._group = radio_group
        self.setObjectName("CandidateRow")
        self.setStyleSheet(_ROW_STYLE)
        self.setProperty("active", False)
        self.setProperty("playing", False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        top = QHBoxLayout()
        self.key = QLabel(str(number) if number <= 9 else "")
        self.key.setFixedWidth(18)
        self.key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key.setStyleSheet("font-weight: bold; " + dim_css())
        self.key.setToolTip(f"Press {number} to play" if number <= 9 else "No shortcut key beyond 9")
        self.name = QLabel()
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta = QLabel()
        self.meta.setStyleSheet(dim_css())
        self.play = QPushButton("Play")
        self.play.setToolTip("Play this candidate")
        self.play.clicked.connect(lambda: self.play_clicked.emit(self.cid))
        self.yay = QPushButton("Yay")
        self.yay.setCheckable(True)
        self.yay.setToolTip("Mark as a good fit (click again to clear)")
        self.yay.clicked.connect(lambda: self.decision_clicked.emit(self.cid, "yay"))
        self.nay = QPushButton("Nay")
        self.nay.setCheckable(True)
        self.nay.setToolTip("Reject this candidate (click again to clear)")
        self.nay.clicked.connect(lambda: self.decision_clicked.emit(self.cid, "nay"))
        self.radio = QRadioButton("Selected")
        self._group.addButton(self.radio)
        self.radio.clicked.connect(lambda: self.select_clicked.emit(self.cid))
        self.remove = QPushButton("Remove")
        self.remove.setFlat(True)
        self.remove.clicked.connect(lambda: self.remove_clicked.emit(self.cid))
        top.addWidget(self.key)
        top.addWidget(self.name, 1)
        top.addWidget(self.meta)
        top.addSpacing(12)
        top.addWidget(self.play)
        top.addWidget(self.yay)
        top.addWidget(self.nay)
        top.addWidget(self.radio)
        top.addWidget(self.remove)
        outer.addLayout(top)

        self.details = QGridLayout()
        self.details.setContentsMargins(26, 0, 0, 0)
        self.details.setHorizontalSpacing(8)
        self.details.setVerticalSpacing(2)
        self._detail_labels: dict[str, tuple[QLabel, QLabel]] = {}
        for i, (key, title) in enumerate(
            (("why", "why"), ("listen_for", "listen for"), ("proposed_use", "proposed use"))
        ):
            k = QLabel(f"{title}:")
            k.setStyleSheet(dim_css())
            k.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
            v = QLabel()
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.details.addWidget(k, i, 0)
            self.details.addWidget(v, i, 1)
            self._detail_labels[key] = (k, v)
        notes_key = QLabel("notes:")
        notes_key.setStyleSheet(dim_css())
        notes_key.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self.notes = _GrowingNotes()
        self.notes.setAccessibleName(f"Notes for {self.cid}")
        self.notes.textChanged.connect(lambda: self.notes_edited.emit(self.cid, self.notes.toPlainText()))
        self.details.addWidget(notes_key, 3, 0)
        self.details.addWidget(self.notes, 3, 1)
        self.details.setColumnStretch(1, 1)
        outer.addLayout(self.details)

        self._pack_name = pack_name
        self.sync(candidate, selected=False, missing=False)

    # -- model -> widgets ----------------------------------------------------

    def sync(self, candidate: Candidate, *, selected: bool, missing: bool) -> None:
        basename = candidate.path.rsplit("/", 1)[-1]
        self.name.setText(basename)
        self.missing = missing
        if missing:
            self.name.setStyleSheet(error_css())
            self.name.setToolTip(f"Missing file: {candidate.path}")
        else:
            self.name.setStyleSheet("")
            self.name.setToolTip(candidate.path)
        self.play.setEnabled(not missing)
        pack = self._pack_name or "no pack"
        self.meta.setText(f"{pack} · {candidate.role}")

        for key, (k, v) in self._detail_labels.items():
            text = getattr(candidate, key)
            v.setText(text)
            k.setVisible(bool(text))
            v.setVisible(bool(text))

        for button, value in ((self.yay, "yay"), (self.nay, "nay")):
            checked = candidate.decision == value
            if button.isChecked() != checked:
                button.blockSignals(True)
                button.setChecked(checked)
                button.blockSignals(False)

        is_nay = candidate.decision == "nay"
        self.radio.setEnabled(not is_nay)
        self.radio.setToolTip(
            "Marked Nay; change the rating to select" if is_nay else "Pick this candidate for the slot"
        )
        if self.radio.isChecked() != selected:
            self._group.setExclusive(False)
            self.radio.setChecked(selected)
            self._group.setExclusive(True)

        if self.notes.toPlainText() != candidate.notes:
            self.notes.blockSignals(True)
            self.notes.setPlainText(candidate.notes)
            self.notes.blockSignals(False)

    def set_playing(self, playing: bool) -> None:
        self.is_playing = playing
        self.play.setText("Stop" if playing else "Play")
        self.play.setToolTip("Stop" if playing else "Play this candidate")
        self._set_style_property("playing", playing)

    def set_active(self, active: bool) -> None:
        self.is_active = active
        self._set_style_property("active", active)

    def set_error_tooltip(self, text: str) -> None:
        self.play.setToolTip(text)

    def _set_style_property(self, name: str, value: bool) -> None:
        if self.property(name) == value:
            return
        self.setProperty(name, value)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
