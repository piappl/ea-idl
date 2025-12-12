"""Tests for HTML utilities."""

from eaidl.html_utils import strip_html, HTMLStripper


def test_strip_html_simple_text():
    """Test that plain text is unchanged."""
    text = "This is plain text."
    result = strip_html(text)
    assert result == "This is plain text."


def test_strip_html_bold_italic():
    """Test that formatting tags are removed."""
    text = "This is <b>bold</b>, <i>italic</i>, and <u>underline</u> text."
    result = strip_html(text)
    assert result == "This is bold, italic, and underline text."


def test_strip_html_nested_tags():
    """Test that nested tags are properly removed."""
    text = "Text with <b><i><u>all formatting</u></i></b> applied."
    result = strip_html(text)
    assert result == "Text with all formatting applied."


def test_strip_html_list_items():
    """Test that list items are converted to newlines."""
    text = "Items:\n<ul>\n\t<li>one</li>\n\t<li>two</li>\n</ul>"
    result = strip_html(text)
    assert "one" in result
    assert "two" in result
    # Should have newlines between items
    assert "\n" in result


def test_strip_html_paragraphs():
    """Test that paragraphs are converted to newlines."""
    text = "<p>First paragraph.</p><p>Second paragraph.</p>"
    result = strip_html(text)
    assert "First paragraph" in result
    assert "Second paragraph" in result
    # Should have separation between paragraphs
    assert "\n" in result


def test_strip_html_complex_formatted_note():
    """Test the actual formatted note from the database."""
    text = """This is formatted note.
We have bullets:
<ul>
\t<li>one </li>
\t<li>two</li>
</ul>
Enumeration
<ol>
\t<li>one</li>
\t<li>two</li>
</ol>


Ther is <b>bold, </b><i>italic, </i><u>underline </u><b><i><u>and all of them.</u></i></b>
<b><i><u>
</u></i></b>"""
    result = strip_html(text)

    # Check that content is preserved
    assert "This is formatted note" in result
    assert "We have bullets:" in result
    assert "one" in result
    assert "two" in result
    assert "Enumeration" in result
    assert "bold, italic, underline and all of them" in result

    # Check that tags are removed
    assert "<ul>" not in result
    assert "<li>" not in result
    assert "<b>" not in result
    assert "<i>" not in result
    assert "<u>" not in result

    # Check that excessive newlines are collapsed (no more than 2 in a row)
    assert "\n\n\n" not in result


def test_strip_html_empty_string():
    """Test that empty string returns empty string."""
    assert strip_html("") == ""


def test_strip_html_none():
    """Test that None returns None."""
    assert strip_html(None) is None


def test_strip_html_only_whitespace():
    """Test that whitespace-only content is stripped."""
    text = "   \n\t   "
    result = strip_html(text)
    assert result == ""


def test_strip_html_br_tags():
    """Test that br tags are converted to newlines."""
    text = "Line 1<br>Line 2<br/>Line 3"
    result = strip_html(text)
    assert "Line 1" in result
    assert "Line 2" in result
    assert "Line 3" in result
    assert "\n" in result


def test_htmlstripper_handle_data_skip_empty():
    """Test that HTMLStripper skips empty text nodes."""
    stripper = HTMLStripper()
    stripper.feed("<p>   </p><p>Text</p>")
    result = stripper.get_text()
    # Should only have "Text", not whitespace-only nodes
    assert result.strip() == "Text"


def test_strip_html_character_entities():
    """Test that HTML character entities are converted."""
    text = "Special chars: &amp; &lt; &gt; &quot;"
    result = strip_html(text)
    assert result == 'Special chars: & < > "'


def test_strip_html_preserves_content_order():
    """Test that content order is preserved."""
    text = "First <b>second</b> third <i>fourth</i> fifth"
    result = strip_html(text)
    assert result == "First second third fourth fifth"


def test_strip_html_multiple_consecutive_list_items():
    """Test that multiple list items don't create excessive blank lines."""
    text = "<ul><li>Item 1</li><li>Item 2</li><li>Item 3</li></ul>"
    result = strip_html(text)
    # Should not have more than one blank line between items
    assert "\n\n\n" not in result
