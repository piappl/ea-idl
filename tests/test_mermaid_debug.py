"""Tests for Mermaid debugging utilities."""

import base64
import json
from eaidl.mermaid_debug import get_mermaid_live_link, get_mermaid_live_link_simple


class TestMermaidDebug:
    """Tests for Mermaid debugging utilities."""

    def test_get_mermaid_live_link(self):
        """Test generation of Mermaid Live Editor link."""
        diagram = """classDiagram
class Foo
class Bar
Foo --> Bar
"""
        link = get_mermaid_live_link(diagram)

        # Should start with Mermaid Live Editor URL
        assert link.startswith("https://mermaid.live/edit#base64:")

        # Extract and decode the state
        base64_state = link.split("#base64:")[1]
        state_json = base64.b64decode(base64_state).decode("utf-8")
        state = json.loads(state_json)

        # Verify state structure
        assert "code" in state
        assert state["code"] == diagram
        assert "mermaid" in state
        assert state["autoSync"] is True

    def test_get_mermaid_live_link_simple(self):
        """Test generation of simple Mermaid Live Editor link."""
        diagram = """classDiagram
class Foo
"""
        link = get_mermaid_live_link_simple(diagram)

        # Should start with Mermaid Live Editor view URL
        assert link.startswith("https://mermaid.live/view#base64:")

        # Extract and decode the diagram
        base64_diagram = link.split("#base64:")[1]
        decoded = base64.b64decode(base64_diagram).decode("utf-8")

        assert decoded == diagram

    def test_links_are_different_for_different_diagrams(self):
        """Test that different diagrams generate different links."""
        diagram1 = "classDiagram\nclass Foo"
        diagram2 = "classDiagram\nclass Bar"

        link1 = get_mermaid_live_link(diagram1)
        link2 = get_mermaid_live_link(diagram2)

        assert link1 != link2

    def test_link_with_special_characters(self):
        """Test link generation with special characters in diagram."""
        diagram = """classDiagram
class Foo {
    +name string
    +email? string
}
Foo --> Bar : "has a"
"""
        link = get_mermaid_live_link(diagram)

        # Should still be valid URL format
        assert link.startswith("https://mermaid.live/edit#base64:")

        # Decode and verify
        base64_state = link.split("#base64:")[1]
        state_json = base64.b64decode(base64_state).decode("utf-8")
        state = json.loads(state_json)

        assert state["code"] == diagram
