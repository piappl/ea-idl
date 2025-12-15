"""HTML utilities for processing note content from Enterprise Architect."""

import re
from markdownify import MarkdownConverter
import markdown


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

    :param text: Text potentially containing HTML tags
    :return: Markdown formatted text
    """
    if not text:
        return text

    # Convert HTML to markdown
    converter = CleanMarkdownConverter()
    result = converter.convert(text)

    # Clean up excessive newlines (more than 2 in a row)
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Clean up whitespace
    result = result.strip()

    return result


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
