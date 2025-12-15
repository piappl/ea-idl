"""
Mermaid debugging utilities.

This module provides utilities for debugging Mermaid diagrams,
including generating shareable Mermaid Live Editor links.
"""

import base64
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)


def get_mermaid_live_link(diagram_code: str, auto_sync: bool = True) -> str:
    """
    Generate a Mermaid Live Editor link for debugging.

    Creates a shareable URL that opens the diagram in https://mermaid.live
    for interactive editing and validation.

    :param diagram_code: Mermaid diagram code
    :param auto_sync: Enable auto-sync in the editor (default: True)
    :return: Mermaid Live Editor URL
    """
    # Mermaid Live Editor uses a state object encoded in the URL
    state = {
        "code": diagram_code,
        "mermaid": {"theme": "default"},
        "autoSync": auto_sync,
        "updateDiagram": True,
    }

    # Convert to JSON and encode as base64
    state_json = json.dumps(state)
    state_base64 = base64.b64encode(state_json.encode("utf-8")).decode("utf-8")

    # URL encode for safety (though Mermaid Live handles it)
    # Actually, Mermaid Live uses pako (zlib) compression, but we can use the simpler
    # /edit endpoint with base64 state
    # Format: https://mermaid.live/edit#base64:STATE

    return f"https://mermaid.live/edit#base64:{state_base64}"


def get_mermaid_live_link_simple(diagram_code: str) -> str:
    """
    Generate a simple Mermaid Live Editor link using the view endpoint.

    This uses a simpler URL format that's more compatible across browsers.

    :param diagram_code: Mermaid diagram code
    :return: Mermaid Live Editor URL
    """
    # Simple format: just base64 encode the diagram code
    encoded = base64.b64encode(diagram_code.encode("utf-8")).decode("utf-8")
    return f"https://mermaid.live/view#base64:{encoded}"


def print_debug_link(diagram_code: str, label: Optional[str] = None):
    """
    Print a Mermaid Live Editor link for debugging.

    Convenience function that generates and prints a clickable link
    for quick debugging in terminal.

    :param diagram_code: Mermaid diagram code
    :param label: Optional label to identify this diagram
    """
    link = get_mermaid_live_link(diagram_code)

    if label:
        print(f"\n🔍 Mermaid Debug Link ({label}):")
    else:
        print("\n🔍 Mermaid Debug Link:")

    print(f"   {link}")
    print()


def save_diagram_with_link(diagram_code: str, output_file: str):
    """
    Save diagram to file with embedded debug link.

    Saves the diagram code to a file and adds a comment with the
    Mermaid Live Editor link at the top.

    :param diagram_code: Mermaid diagram code
    :param output_file: Output file path
    """
    link = get_mermaid_live_link(diagram_code)

    with open(output_file, "w") as f:
        f.write(f"# Mermaid Live Editor: {link}\n")
        f.write("#\n")
        f.write(diagram_code)

    log.info(f"Saved diagram to {output_file} with debug link")


# Example usage as a command-line utility
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m eaidl.mermaid_debug <diagram_file>")
        print()
        print("Generates a Mermaid Live Editor link from a diagram file.")
        print()
        print("Example:")
        print("  python -m eaidl.mermaid_debug diagram.mmd")
        sys.exit(1)

    diagram_file = sys.argv[1]

    with open(diagram_file, "r") as f:
        diagram_code = f.read()

    print_debug_link(diagram_code, label=diagram_file)
