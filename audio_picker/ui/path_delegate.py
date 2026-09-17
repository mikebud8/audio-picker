"""List delegate for relative library paths: pack folder bold, optional muted summary."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPalette, QTextDocument
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .theme import dim_color

PATH_ROLE = Qt.ItemDataRole.UserRole
SUMMARY_ROLE = Qt.ItemDataRole.UserRole + 1


def path_html(rel: str, color: str, summary: str = "", dim: str = "") -> str:
    folder, sep, rest = rel.partition("/")
    body = f"<b>{escape(folder)}</b>/{escape(rest)}" if sep else escape(rel)
    html = f'<span style="color: {color}">{body}</span>'
    if summary:
        html += f'<span style="color: {dim}">&nbsp;&nbsp;{escape(summary)}</span>'
    return html


class PathDelegate(QStyledItemDelegate):
    """Draws `PATH_ROLE` with its first component bold and `SUMMARY_ROLE` dimmed after it."""

    def _document(self, option: QStyleOptionViewItem, index, selected: bool = False) -> QTextDocument:
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(2)
        rel = index.data(PATH_ROLE) or index.data() or ""
        summary = index.data(SUMMARY_ROLE) or ""
        color = option.palette.color(role).name()
        dim = color if selected else dim_color(option.palette).name()
        doc.setHtml(path_html(rel, color, summary, dim))
        return doc

    def paint(self, painter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        doc = self._document(opt, index, selected=bool(opt.state & QStyle.StateFlag.State_Selected))
        painter.save()
        painter.translate(opt.rect.left(), opt.rect.top() + (opt.rect.height() - doc.size().height()) / 2)
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        doc = self._document(option, index)
        return QSize(int(doc.idealWidth()), int(doc.size().height()))
