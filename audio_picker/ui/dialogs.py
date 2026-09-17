"""Dialogs (design section 13.7) behind one factory so tests can substitute fakes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPalette, QRegularExpressionValidator, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..library import AudioLibrary
from ..model import ID_RE, PRIORITIES, ROLES, Review, Slot
from ..paths import to_absolute, to_relative
from .theme import error_css

SHORTCUTS = [
    ("1 – 9", "Play candidate N; the key of the playing candidate stops it"),
    ("Space", "Pause / resume; if nothing is loaded, play candidate 1"),
    ("S", "Stop"),
    ("L", "Toggle loop"),
    ("Y / N", "Mark the active candidate yay / nay (again to clear)"),
    ("Enter", "Select the active candidate for the slot"),
    ("Escape", "Leave a text field and return to the slot tree"),
    ("Ctrl+Down / Ctrl+Up", "Next / previous slot (wraps)"),
    ("Ctrl+F", "Focus the slot search box"),
    ("Ctrl+S", "Save now"),
    ("Ctrl+N", "Add slot"),
    ("Ctrl+Shift+N", "Add candidate"),
    ("Ctrl+E", "Edit slot"),
    ("Ctrl+O", "Open another review"),
]


@dataclass
class AddCandidateResult:
    path: str  # relative, forward slashes
    role: str
    why: str


@dataclass
class SlotEdit:
    id: str
    category: str
    function: str
    priority: str
    notes: str


class _PathDelegate(QStyledItemDelegate):
    """Draws a relative path with its first component (the pack folder) in bold."""

    @staticmethod
    def _html(rel: str, color: str) -> str:
        folder, sep, rest = rel.partition("/")
        body = f"<b>{folder}</b>/{rest}" if sep else rel
        return f'<span style="color: {color}">{body}</span>'

    def _document(self, option: QStyleOptionViewItem, index, selected: bool = False) -> QTextDocument:
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(2)
        rel = index.data(Qt.ItemDataRole.UserRole) or index.data() or ""
        doc.setHtml(self._html(rel, option.palette.color(role).name()))
        return doc

    def paint(self, painter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QStyle()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        doc = self._document(opt, index, selected=bool(opt.state & QStyle.StateFlag.State_Selected))
        painter.save()
        painter.translate(opt.rect.left(), opt.rect.top() + (opt.rect.height() - doc.size().height()) / 2)
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        doc = self._document(option, index)
        return QSize(int(doc.idealWidth()), int(doc.size().height()))


class AddCandidateDialog(QDialog):
    def __init__(self, review: Review, library: AudioLibrary, root: Path, player, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add candidate")
        self.resize(640, 480)
        self._review = review
        self._library = library
        self._root = root
        self._player = player
        self._chosen: str | None = None

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the audio library (every word must match)")
        self.search.textChanged.connect(self._refresh_results)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.setItemDelegate(_PathDelegate(self.results))
        self.results.currentItemChanged.connect(self._on_current_result)
        self.results.itemDoubleClicked.connect(lambda _i: self._preview())
        layout.addWidget(self.results, 1)

        row = QHBoxLayout()
        self.preview = QPushButton("Preview")
        self.preview.setEnabled(False)
        self.preview.clicked.connect(self._preview)
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self._browse)
        self.chosen_label = QLabel("No file chosen")
        self.chosen_label.setWordWrap(True)
        row.addWidget(self.preview)
        row.addWidget(self.browse)
        row.addWidget(self.chosen_label, 1)
        layout.addLayout(row)

        form = QFormLayout()
        self.role = QComboBox()
        self.role.addItems(ROLES)
        self.role.setCurrentText("alternative")
        self.why = QLineEdit()
        self.why.setPlaceholderText("Why is this file a candidate?")
        form.addRow("Role", self.role)
        form.addRow("Why", self.why)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self.buttons)

        self._refresh_results("")
        self.search.setFocus()

    def _refresh_results(self, query: str) -> None:
        self.results.clear()
        for rel in self._library.search(query):
            item = QListWidgetItem(rel)
            folder = AudioLibrary.pack_folder(rel)
            pack = next((p.name for p in self._review.packs.values() if p.folder == folder), None)
            item.setToolTip(f"Pack: {pack}" if pack else "No pack matches this folder")
            item.setData(Qt.ItemDataRole.UserRole, rel)
            self.results.addItem(item)

    def _on_current_result(self, current: QListWidgetItem | None, _previous) -> None:
        if current is not None:
            self._set_chosen(current.data(Qt.ItemDataRole.UserRole))

    def _set_chosen(self, rel: str | None, note: str = "") -> None:
        self._chosen = rel
        self.chosen_label.setText(rel or note or "No file chosen")
        self.preview.setEnabled(rel is not None)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(rel is not None)

    def _preview(self) -> None:
        if self._chosen:
            self._player.play(to_absolute(self._root, self._chosen))

    def _browse(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Choose an audio file", str(self._root), "Audio (*.wav *.ogg *.mp3 *.flac);;All files (*)"
        )
        if not name:
            return
        rel = to_relative(self._root, name)
        if not rel:
            self._set_chosen(None, f"Not under the audio root: {name}")
            return
        self._set_chosen(rel)

    def result_value(self) -> AddCandidateResult | None:
        if self._chosen is None:
            return None
        return AddCandidateResult(self._chosen, self.role.currentText(), self.why.text())


class SlotEditorDialog(QDialog):
    def __init__(self, review: Review, slot: Slot | None, parent=None) -> None:
        super().__init__(parent)
        self._review = review
        self._slot = slot
        self.setWindowTitle("Edit slot" if slot else "Add slot")
        self.resize(480, 360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.id = QLineEdit(slot.id if slot else "")
        self.id.setValidator(QRegularExpressionValidator(r"[a-z][a-z0-9_]*"))
        self.id.setPlaceholderText("snake_case, e.g. ui_click")
        self.id.setEnabled(slot is None)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(review.categories)
        self.category.setCurrentText(slot.category if slot else (review.categories[0] if review.categories else ""))
        self.function = QLineEdit(slot.function if slot else "")
        self.function.setPlaceholderText("What the sound does in the game, one sentence")
        self.priority = QComboBox()
        self.priority.addItems(PRIORITIES)
        self.priority.setCurrentText(slot.priority if slot else "first_pass")
        self.notes = QPlainTextEdit(slot.notes if slot else "")
        form.addRow("Id", self.id)
        form.addRow("Category", self.category)
        form.addRow("Function", self.function)
        form.addRow("Priority", self.priority)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)

        self.problem = QLabel("")
        self.problem.setStyleSheet(error_css())
        layout.addWidget(self.problem)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._try_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        (self.function if slot else self.id).setFocus()

    def _try_accept(self) -> None:
        sid = self.id.text().strip()
        if not ID_RE.match(sid):
            self.problem.setText("Id must be snake_case: a lower-case letter, then letters, digits or _.")
            return
        if self._slot is None and self._review.slot(sid) is not None:
            self.problem.setText(f"A slot named {sid!r} already exists.")
            return
        if not self.category.currentText().strip():
            self.problem.setText("Category is required.")
            return
        self.accept()

    def result_value(self) -> SlotEdit:
        return SlotEdit(
            id=self.id.text().strip(),
            category=self.category.currentText().strip(),
            function=self.function.text().strip(),
            priority=self.priority.currentText(),
            notes=self.notes.toPlainText(),
        )


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        layout = QVBoxLayout(self)
        rows = "".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in SHORTCUTS)
        label = QLabel(
            f"<table cellpadding='4'>{rows}</table>"
            "<p>Single-key shortcuts are off while a text field has focus; press Escape to leave it.</p>"
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda _b: self.accept())
        layout.addWidget(buttons)


class Dialogs:
    """Real dialogs. Every method blocks; tests replace the whole object."""

    def confirm(self, parent: QWidget | None, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            parent,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def error(self, parent: QWidget | None, title: str, text: str) -> None:
        QMessageBox.critical(parent, title, text)

    def conflict(self, parent: QWidget | None, path: Path) -> str:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("File changed on disk")
        box.setText(f"{path.name} was changed by another program since it was last loaded or saved.")
        box.setInformativeText("Your unsaved changes have not been written.")
        reload = box.addButton("Reload from disk (discard my unsaved changes)", QMessageBox.ButtonRole.DestructiveRole)
        overwrite = box.addButton("Overwrite the file with my changes", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reload:
            return "reload"
        if clicked is overwrite:
            return "overwrite"
        return "cancel"

    def quit_without_saving(self, parent: QWidget | None) -> bool:
        return self.confirm(parent, "Quit", "The review could not be saved. Quit without saving?")

    def export_path(self, parent: QWidget | None, start: Path) -> Path | None:
        name, _ = QFileDialog.getSaveFileName(parent, "Export manifest", str(start), "JSON (*.json)")
        return Path(name) if name else None

    def open_review_path(self, parent: QWidget | None, start: Path) -> Path | None:
        name, _ = QFileDialog.getOpenFileName(parent, "Open review", str(start), "Review (*.json)")
        return Path(name) if name else None

    def add_candidate(
        self, parent, review: Review, library: AudioLibrary, root: Path, player
    ) -> AddCandidateResult | None:
        dialog = AddCandidateDialog(review, library, root, player, parent)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return dialog.result_value() if accepted else None
        finally:
            player.stop()  # a preview never outlives the dialog

    def edit_slot(self, parent, review: Review, slot: Slot | None) -> SlotEdit | None:
        dialog = SlotEditorDialog(review, slot, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.result_value()
        return None

    def shortcuts(self, parent: QWidget | None) -> None:
        ShortcutsDialog(parent).exec()
