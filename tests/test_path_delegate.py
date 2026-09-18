"""Path markup for the library list (design section 11)."""

from audio_picker.ui.path_delegate import path_html


def test_pack_folder_is_bold_and_there_is_no_summary_span():
    html = path_html("packA/click.wav", "#000")
    assert "<b>packA</b>/click.wav" in html
    assert html.count("<span") == 1


def test_path_and_summary_are_escaped_and_the_summary_is_dimmed():
    html = path_html("a<b>&c.wav", "#000", "★4 <ui>", "#888")
    assert "a&lt;b&gt;&amp;c.wav" in html
    assert "★4 &lt;ui&gt;" in html
    assert "color: #888" in html


def test_a_loose_file_has_no_bold_component():
    assert "<b>" not in path_html("loose.wav", "#000")
