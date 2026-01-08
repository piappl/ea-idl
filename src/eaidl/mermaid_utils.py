"""
Mermaid diagram utilities for safe name handling.

This module provides utilities for generating Mermaid diagrams with robust
handling of special characters in names, notes, and labels.
"""

import re
import html


def sanitize_id(name: str, for_plantuml: bool = False) -> str:
    """
    Generate a safe diagram identifier from a name.

    For Mermaid (default): Removes all non-alphanumeric characters except underscores.
    For PlantUML: Only escapes quotes and newlines.

    Examples (Mermaid):
        "MUV_#1" -> "MUV_1"
        "Data<T>" -> "DataT"
        "my-class" -> "my_class"
        "Class::Name" -> "Class_Name"

    Examples (PlantUML):
        'My"Class' -> 'My\\"Class'
        'Line\nBreak' -> 'Line Break'

    :param name: Original name
    :param for_plantuml: If True, use PlantUML sanitization; otherwise use Mermaid
    :return: Safe identifier
    """
    if for_plantuml:
        # PlantUML only needs quote escaping and newline removal
        return name.replace('"', '\\"').replace("\n", " ")

    # Mermaid sanitization (default)
    # Replace common separators with underscore
    safe = name.replace("::", "_")
    safe = safe.replace("-", "_")
    safe = safe.replace(" ", "_")

    # Remove all non-alphanumeric characters except underscore
    safe = re.sub(r"[^a-zA-Z0-9_]", "", safe)

    # Ensure it doesn't start with a number (prepend underscore if needed)
    if safe and safe[0].isdigit():
        safe = "_" + safe

    # Fallback if name becomes empty
    if not safe:
        safe = "UnknownClass"

    return safe


def escape_label(text: str) -> str:
    """
    Escape text for use in Mermaid labels/notes.

    Handles:
    - Double quotes (escaped or replaced)
    - Newlines (converted to spaces)
    - HTML entities (decoded)
    - Special characters that break Mermaid syntax

    :param text: Original text
    :return: Escaped text safe for Mermaid labels
    """
    if not text:
        return ""

    # Decode HTML entities first (e.g., &lt; -> <, &gt; -> >)
    text = html.unescape(text)

    # Replace newlines with spaces
    text = text.replace("\n", " ").replace("\r", " ")

    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)

    # Escape double quotes by replacing with single quotes
    # (Mermaid labels use double quotes, so we can't escape them easily)
    text = text.replace('"', "'")

    # Remove or escape other problematic characters
    # Backticks can break code blocks
    text = text.replace("`", "'")

    # Trim whitespace
    text = text.strip()

    return text


def get_class_label(name: str) -> str:
    """
    Generate Mermaid class declaration with safe ID and display label.

    If the name contains special characters, uses Mermaid's label syntax:
        class SafeID["Display Name"]

    Otherwise, uses simple syntax:
        class SimpleName

    :param name: Original class name
    :return: Mermaid class identifier or "ID[Label]" syntax
    """
    safe_id = sanitize_id(name)

    # If sanitization changed the name, use label syntax
    if safe_id != name:
        escaped_name = escape_label(name)
        return f'{safe_id}["{escaped_name}"]'
    else:
        return safe_id


def get_participant_declaration(name: str) -> str:
    """
    Generate Mermaid sequence diagram participant declaration.

    Uses the "participant SafeID as DisplayName" syntax when needed.

    :param name: Original participant name
    :return: Mermaid participant declaration
    """
    safe_id = sanitize_id(name)

    # If sanitization changed the name, use "as" syntax
    if safe_id != name:
        escaped_name = escape_label(name)
        return f'participant {safe_id} as "{escaped_name}"'
    else:
        return f"participant {safe_id}"


def format_note_text(text: str, max_length: int = 100) -> str:
    """
    Format text for Mermaid note.

    Escapes special characters and optionally truncates long text.

    :param text: Original note text
    :param max_length: Maximum length (0 = no limit)
    :return: Formatted note text
    """
    formatted = escape_label(text)

    if max_length > 0 and len(formatted) > max_length:
        formatted = formatted[: max_length - 3] + "..."

    return formatted
