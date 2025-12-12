"""HTML utilities for processing note content from Enterprise Architect."""

from html.parser import HTMLParser
import re


class HTMLStripper(HTMLParser):
    """Simple HTML to text converter that strips tags and converts basic formatting."""

    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
        self.in_list_item = False

    def handle_data(self, data):
        """Handle text data between tags."""
        if data.strip():  # Only add non-empty text
            self.text.append(data)

    def handle_starttag(self, tag, attrs):
        """Handle opening tags."""
        if tag in ["li"]:
            # Mark that we're in a list item
            self.in_list_item = True
            # Add newline before list item if there's already content
            if self.text:
                self.text.append("\n")
        elif tag in ["p", "br"]:
            # Add newline for paragraphs and breaks
            if self.text:
                self.text.append("\n")

    def handle_endtag(self, tag):
        """Handle closing tags."""
        if tag in ["li"]:
            # End of list item
            self.in_list_item = False
        elif tag in ["p"]:
            # Add newline after paragraph
            if self.text:
                self.text.append("\n")

    def get_text(self):
        """Get the cleaned text."""
        return "".join(self.text)


def strip_html(text: str) -> str:
    """Remove HTML tags from text and convert basic formatting to plain text.

    :param text: Text potentially containing HTML tags
    :return: Plain text with HTML removed
    """
    if not text:
        return text

    stripper = HTMLStripper()
    stripper.feed(text)
    result = stripper.get_text()

    # Clean up excessive newlines (more than 2 in a row)
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Clean up whitespace
    result = result.strip()

    return result
