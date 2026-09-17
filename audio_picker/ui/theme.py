"""Palette-derived colours that stay readable in light and dark themes.

Qt's `mid` role is a dark gray in dark themes, so dimmed text drawn with it
vanishes. These helpers blend the theme's own text and window colours instead.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def _palette(palette: QPalette | None) -> QPalette:
    return palette if palette is not None else QApplication.palette()


def blend(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend: t = 0 gives `a`, t = 1 gives `b`."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def is_dark(palette: QPalette | None = None) -> bool:
    return _palette(palette).color(QPalette.ColorRole.Window).lightness() < 128


def dim_color(palette: QPalette | None = None) -> QColor:
    """Secondary text: 60% of the way from the window colour to the text colour."""
    p = _palette(palette)
    return blend(p.color(QPalette.ColorRole.Window), p.color(QPalette.ColorRole.Text), 0.6)


def dim_css(palette: QPalette | None = None) -> str:
    return f"color: {dim_color(palette).name()};"


def error_color(palette: QPalette | None = None) -> QColor:
    return QColor("#ef7b6d") if is_dark(palette) else QColor("#c0392b")


def error_css(palette: QPalette | None = None) -> str:
    return f"color: {error_color(palette).name()};"


def _luminance(c: QColor) -> float:
    def channel(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(c.red()) + 0.7152 * channel(c.green()) + 0.0722 * channel(c.blue())


def contrast_ratio(a: QColor, b: QColor) -> float:
    """WCAG contrast ratio between two colours (1.0 to 21.0)."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
