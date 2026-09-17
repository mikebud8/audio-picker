"""Renders the main window and dialogs in light and dark themes to `screenshots/`.

The PNGs are proof artifacts for eyeballing layout and contrast; the
assertions check that each image was produced and is not blank, and that the
dimmed and error text colours keep a readable contrast in both themes.
"""

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPalette
from PySide6.QtWidgets import QApplication

from audio_picker.library import AudioLibrary
from audio_picker.model import load
from audio_picker.ui.dialogs import AddCandidateDialog, ShortcutsDialog, SlotEditorDialog
from audio_picker.ui.main_window import MainWindow
from audio_picker.ui.theme import contrast_ratio, dim_color, error_color
from tests.test_ui_smoke import FakeDialogs, FakePlayer

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "review.json"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "audio"
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "screenshots"
MIN_CONTRAST = 3.0


def dark_palette() -> QPalette:
    p = QPalette()
    window = QColor(45, 45, 45)
    base = QColor(30, 30, 30)
    text = QColor(228, 228, 228)
    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(52, 52, 52))
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, window)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(140, 140, 140))
    p.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Mid, QColor(70, 70, 70))
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(120, 120, 120))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(120, 120, 120))
    return p


@pytest.fixture(scope="module", autouse=True)
def screenshot_dir() -> Path:
    shutil.rmtree(SCREENSHOT_DIR, ignore_errors=True)
    SCREENSHOT_DIR.mkdir()
    return SCREENSHOT_DIR


@pytest.fixture(params=["light", "dark"])
def theme(request, qapp) -> str:
    old_style = qapp.style().objectName()
    old_palette = QPalette(qapp.palette())
    old_font = QFont(qapp.font())
    if "Segoe UI" in QFontDatabase.families():
        qapp.setFont(QFont("Segoe UI", 9))
    if request.param == "dark":
        qapp.setStyle("Fusion")
        qapp.setPalette(dark_palette())
    yield request.param
    qapp.setStyle(old_style)
    qapp.setPalette(old_palette)
    qapp.setFont(old_font)


def _save(widget, name: str) -> Path:
    QApplication.processEvents()
    out = SCREENSHOT_DIR / f"{name}.png"
    assert widget.grab().save(str(out)), f"could not write {out}"
    image = QImage(str(out))
    assert not image.isNull() and image.width() > 200 and image.height() > 100
    colours = {image.pixel(x, y) for x in range(0, image.width(), 37) for y in range(0, image.height(), 41)}
    assert len(colours) > 2, f"{name} looks blank"
    return out


@pytest.fixture
def window(qtbot, tmp_path, theme):
    review_file = tmp_path / "review.json"
    shutil.copy(EXAMPLE, review_file)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(review_file, FIXTURE_ROOT, player=FakePlayer(), dialogs=FakeDialogs(), settings=settings)
    w.resize(1280, 800)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


def test_main_window_screenshots(qtbot, window, theme):
    qtbot.keyClick(window.tree.view, Qt.Key.Key_2)  # a playing row and an active border
    _save(window, f"main_{theme}")
    window.tree.select_slot("horn_distant")
    _save(window, f"main_gap_{theme}")
    window.tree.status_filter.setCurrentText("Missing files")
    _save(window, f"main_no_match_{theme}")


def test_missing_files_screenshot(qtbot, tmp_path, theme):
    review_file = tmp_path / "review.json"
    shutil.copy(EXAMPLE, review_file)
    empty = tmp_path / "empty"
    empty.mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(review_file, empty, player=FakePlayer(), dialogs=FakeDialogs(), settings=settings)
    w.resize(1280, 800)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    _save(w, f"main_missing_files_{theme}")


def test_dialog_screenshots(qtbot, theme):
    review = load(EXAMPLE)
    add = AddCandidateDialog(review, AudioLibrary(FIXTURE_ROOT), FIXTURE_ROOT, FakePlayer())
    qtbot.addWidget(add)
    add.show()
    qtbot.waitExposed(add)
    add.results.setCurrentRow(1)
    _save(add, f"dialog_add_candidate_{theme}")

    edit = SlotEditorDialog(review, review.slot("ui_click"))
    qtbot.addWidget(edit)
    edit.show()
    qtbot.waitExposed(edit)
    edit.id.setText("")
    edit._try_accept()  # shows the inline validation problem
    _save(edit, f"dialog_edit_slot_{theme}")

    keys = ShortcutsDialog()
    qtbot.addWidget(keys)
    keys.show()
    qtbot.waitExposed(keys)
    _save(keys, f"dialog_shortcuts_{theme}")


@pytest.mark.parametrize("palette", [QPalette(), dark_palette()], ids=["light", "dark"])
def test_theme_colours_keep_contrast(qapp, palette):
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)
    for background in (window, base):
        assert contrast_ratio(dim_color(palette), background) >= MIN_CONTRAST
        assert contrast_ratio(error_color(palette), background) >= MIN_CONTRAST
