"""Tests for HTML utilities."""

from eaidl.html_utils import normalize_unicode, strip_html


def test_strip_html_simple_text():
    """Test that plain text is unchanged."""
    text = "This is plain text."
    result = strip_html(text)
    assert result == "This is plain text."


def test_strip_html_bold_italic():
    """Test that formatting tags are converted to markdown."""
    text = "This is <b>bold</b>, <i>italic</i>, and <u>underline</u> text."
    result = strip_html(text)
    assert result == "This is **bold**, *italic*, and underline text."


def test_strip_html_nested_tags():
    """Test that nested tags are properly converted to markdown."""
    text = "Text with <b><i><u>all formatting</u></i></b> applied."
    result = strip_html(text)
    assert result == "Text with ***all formatting*** applied."


def test_strip_html_list_items():
    """Test that list items are converted to markdown bullets."""
    text = "Items:\n<ul>\n\t<li>one</li>\n\t<li>two</li>\n</ul>"
    result = strip_html(text)
    assert "* one" in result
    assert "* two" in result
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
    assert "* one" in result  # Now has markdown bullet
    assert "* two" in result  # Now has markdown bullet
    assert "Enumeration" in result
    assert "1. one" in result  # Now has markdown numbering
    assert "2. two" in result  # Now has markdown numbering

    # Check that formatting is converted to markdown
    assert "**bold,**" in result
    assert "*italic,*" in result
    assert "***and all of them.***" in result

    # Check that HTML tags are not present
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
    text = "Line 1<br>Line 2<br>Line 3"
    result = strip_html(text)
    assert "Line 1" in result
    assert "Line 2" in result
    assert "Line 3" in result
    assert "\n" in result


def test_strip_html_whitespace_only_nodes():
    """Test that whitespace-only nodes are handled properly."""
    text = "<p>   </p><p>Text</p>"
    result = strip_html(text)
    # Should only have "Text", whitespace is trimmed
    assert result == "Text"


def test_strip_html_character_entities():
    """Test that HTML character entities are converted."""
    text = "Special chars: &amp; &lt; &gt; &quot;"
    result = strip_html(text)
    assert result == 'Special chars: & < > "'


def test_strip_html_preserves_content_order():
    """Test that content order is preserved with markdown formatting."""
    text = "First <b>second</b> third <i>fourth</i> fifth"
    result = strip_html(text)
    assert result == "First **second** third *fourth* fifth"


def test_strip_html_multiple_consecutive_list_items():
    """Test that multiple list items don't create excessive blank lines."""
    text = "<ul><li>Item 1</li><li>Item 2</li><li>Item 3</li></ul>"
    result = strip_html(text)
    # Should not have more than one blank line between items
    assert "\n\n\n" not in result
    # Should have markdown bullets
    assert "* Item 1" in result
    assert "* Item 2" in result
    assert "* Item 3" in result


def test_strip_html_script_style_removed():
    """Test that script and style tags are completely removed with their content."""
    text = "<p>Normal text</p><style>.foo{color:red}</style><p>More text</p><script>alert(1)</script><p>End</p>"
    result = strip_html(text)
    # Content should be preserved
    assert "Normal text" in result
    assert "More text" in result
    assert "End" in result
    # Script and style content should be completely removed
    assert "color:red" not in result
    assert "alert" not in result
    assert "<script>" not in result
    assert "<style>" not in result


def test_strip_html_unknown_tags():
    """Test that unknown/custom tags are stripped but content is preserved."""
    text = "<p>Text with <custom>unknown</custom> and <weird attr='val'>tags</weird></p>"
    result = strip_html(text)
    # Content should be preserved
    assert "Text with unknown and tags" in result
    # Tags should be stripped
    assert "<custom>" not in result
    assert "<weird>" not in result


def test_normalize_unicode_smart_quotes():
    """Test that smart quotes are converted to ASCII."""
    text = "Minimum, inclusive, value is '0'"
    result = normalize_unicode(text)
    assert result == "Minimum, inclusive, value is '0'"

    text = "Maximum, exclusive, value is '360'"
    result = normalize_unicode(text)
    assert result == "Maximum, exclusive, value is '360'"


def test_normalize_unicode_double_quotes():
    """Test that smart double quotes are converted to ASCII."""
    text = 'He said "hello" to everyone'
    result = normalize_unicode(text)
    assert result == 'He said "hello" to everyone'


def test_normalize_unicode_dashes():
    """Test that en-dash and em-dash are converted to ASCII."""
    # En dash (U+2013)
    text = "pages 10–20"
    result = normalize_unicode(text)
    assert result == "pages 10-20"

    # Em dash (U+2014)
    text = "word—another word"
    result = normalize_unicode(text)
    assert result == "word--another word"


def test_normalize_unicode_ellipsis():
    """Test that horizontal ellipsis is converted to three dots."""
    text = "To be continued…"
    result = normalize_unicode(text)
    assert result == "To be continued..."


def test_normalize_unicode_non_breaking_space():
    """Test that non-breaking space is converted to regular space."""
    text = "100\u00a0km"
    result = normalize_unicode(text)
    assert result == "100 km"


def test_normalize_unicode_empty_none():
    """Test that empty string and None are handled."""
    assert normalize_unicode("") == ""
    assert normalize_unicode(None) is None


def test_strip_html_normalizes_unicode():
    """Test that strip_html integrates Unicode normalization."""
    # Use actual Unicode smart quotes (U+2018 and U+2019)
    text = "<p>Minimum, inclusive, value is \u20180\u2019</p>"
    result = strip_html(text)
    assert "'" in result
    assert "\u2018" not in result
    assert "\u2019" not in result
