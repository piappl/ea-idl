"""HTML utilities for processing note content from Enterprise Architect."""

import re
from markdownify import MarkdownConverter


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
