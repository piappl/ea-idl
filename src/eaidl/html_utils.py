"""HTML utilities for processing note content from Enterprise Architect.

This module provides utilities for bidirectional HTML processing:
- strip_html(): EA HTML → Markdown (for export to DOCX)
- convert_to_ea_html(): Modern HTML → EA HTML (for import from DOCX)
- format_notes_for_html(): EA HTML → Display HTML (for documentation)
- normalize_unicode(): Normalize smart quotes and other Unicode to ASCII
"""

import re
from typing import Dict
from markdownify import MarkdownConverter
import markdown
from bs4 import BeautifulSoup


# Common Unicode character replacements (smart quotes, dashes, etc.)
UNICODE_REPLACEMENTS = {
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote (apostrophe)
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u2013": "-",  # en dash
    "\u2014": "--",  # em dash
    "\u2026": "...",  # horizontal ellipsis
    "\u00a0": " ",  # non-breaking space
}


def normalize_unicode(text: str) -> str:
    """Normalize common Unicode characters to ASCII equivalents.

    Converts smart quotes, dashes, and other typographic characters
    that word processors insert to their plain ASCII equivalents.

    :param text: Text potentially containing Unicode characters
    :return: Text with normalized ASCII characters
    """
    if not text:
        return text
    for unicode_char, replacement in UNICODE_REPLACEMENTS.items():
        text = text.replace(unicode_char, replacement)
    return text


class CleanMarkdownConverter(MarkdownConverter):
    """Custom markdown converter that completely removes script/style tags."""

    def convert_script(self, el, text, **kwargs):
        """Completely ignore script tags and their content."""
        return ""

    def convert_style(self, el, text, **kwargs):
        """Completely ignore style tags and their content."""
        return ""


def strip_html(text: str) -> str:
    """Convert HTML to markdown, stripping unsupported tags.

    Converts EA note HTML to clean markdown format:
    - Lists (<ul>, <ol>) become markdown lists
    - Bold/italic (<b>, <i>) become **bold** and *italic*
    - Unknown tags are stripped (content preserved)
    - Script/style tags are completely removed
    - Smart quotes and other Unicode normalized to ASCII

    :param text: Text potentially containing HTML tags
    :return: Markdown formatted text
    """
    if not text:
        return text

    # Convert HTML to markdown
    converter = CleanMarkdownConverter()
    result = converter.convert(text)

    # Normalize Unicode characters (smart quotes, dashes, etc.)
    result = normalize_unicode(result)

    # Clean up excessive newlines (more than 2 in a row)
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Clean up whitespace
    result = result.strip()

    return result


def _replace_tags(soup: BeautifulSoup, tag_mapping: Dict[str, str]) -> None:
    """
    Replace HTML tags in BeautifulSoup object according to mapping.

    Helper to consolidate tag replacement logic.

    :param soup: BeautifulSoup object to modify
    :param tag_mapping: Dictionary mapping old tag names to new tag names
    """
    for old_tag, new_tag in tag_mapping.items():
        for tag in soup.find_all(old_tag):
            tag.name = new_tag


def convert_to_ea_html(html: str) -> str:
    """
    Convert modern HTML5 tags to EA-compatible HTML format.

    EA uses older HTML tags and expects specific formatting:
    - <b> instead of <strong>
    - <i> instead of <em>
    - No wrapper <html><body> tags
    - Minimal <p> tags (EA adds its own paragraph handling)

    :param html: HTML string with modern tags
    :return: EA-compatible HTML string
    """
    if not html:
        return html

    soup = BeautifulSoup(html, "html.parser")

    # Replace modern HTML5 tags with EA-compatible tags
    _replace_tags(soup, {"strong": "b", "em": "i"})

    # Get the HTML string
    result = str(soup)

    # BeautifulSoup might add wrapper tags, remove them
    # Remove <html><body> wrappers if present
    result = re.sub(r"^<html><body>|</body></html>$", "", result)

    # EA doesn't need wrapper <p> tags for simple content
    # Only unwrap single top-level <p> tags
    if result.startswith("<p>") and result.endswith("</p>") and result.count("<p>") == 1:
        result = result[3:-4]

    return result.strip()


def format_notes_for_html(text: str) -> str:
    """
    Convert EA note HTML to formatted HTML for display.

    This function:
    1. Converts EA's HTML notes to markdown (stripping unsafe tags)
    2. Fixes common markdown formatting issues
    3. Converts the markdown back to safe HTML for display

    :param text: Text potentially containing HTML tags (from EA notes)
    :return: Clean HTML formatted text ready for display
    """
    if not text:
        return text

    # First convert HTML to markdown (strips unsafe content)
    markdown_text = strip_html(text)

    # Unescape escaped markdown characters (markdownify escapes them to preserve literal text)
    # We want to treat them as markdown syntax instead
    markdown_text = markdown_text.replace("\\*", "*").replace("\\_", "_")

    # Fix common issues from EA HTML -> Markdown conversion
    # Ensure proper spacing before lists (both * and numbered)
    lines = markdown_text.split("\n")
    fixed_lines = []
    prev_was_list = False
    prev_was_blank = False

    for line in lines:
        stripped = line.strip()
        is_blank = not stripped

        # Check if this is a list item
        is_list = stripped.startswith("* ") or (stripped and stripped[0].isdigit() and ". " in stripped[:4])

        # Add blank line before list start
        if is_list and not prev_was_list and fixed_lines and fixed_lines[-1].strip():
            fixed_lines.append("")

        # Preserve existing blank lines as paragraph breaks
        # But don't add multiple consecutive blank lines
        if is_blank and not prev_was_blank and fixed_lines:
            fixed_lines.append("")
        elif not is_blank:
            fixed_lines.append(line)

        prev_was_list = is_list
        prev_was_blank = is_blank

    markdown_text = "\n".join(fixed_lines)

    # Then convert markdown to HTML for display
    # Using 'extra' extension for tables, fenced code, etc.
    # nl2br converts single newlines to <br> tags for better paragraph handling
    html_output = markdown.markdown(markdown_text, extensions=["extra", "sane_lists", "nl2br"])

    return html_output
