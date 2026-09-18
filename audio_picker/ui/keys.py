"""Keyboard rules shared by the windows (design 13.6)."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit


def text_field_focused() -> bool:
    """True while a text-entry widget has focus, when single-key shortcuts must stay quiet."""
    w = QApplication.focusWidget()
    if isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
        return True
    return isinstance(w, QComboBox) and w.isEditable()
