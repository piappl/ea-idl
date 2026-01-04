"""Tests for renderer factory - Renderer selection based on config."""

import pytest
from eaidl.config import Configuration
from eaidl.renderers.factory import get_renderer
from eaidl.renderers.mermaid_renderer import MermaidRenderer
from eaidl.renderers.plantuml_renderer import PlantUMLRenderer


class TestRendererFactory:
    """Test renderer factory functionality."""

    def test_get_mermaid_renderer(self, test_config):
        """Test that Mermaid renderer is returned when configured."""
        test_config.diagrams.renderer = "mermaid"
        renderer = get_renderer(test_config)

        assert isinstance(renderer, MermaidRenderer)

    def test_default_is_mermaid(self, test_config):
        """Test that default renderer is Mermaid."""
        # Don't set renderer explicitly - use default
        renderer = get_renderer(test_config)

        assert isinstance(renderer, MermaidRenderer)

    def test_get_plantuml_renderer(self, test_config):
        """Test that PlantUML renderer is returned when configured."""
        test_config.diagrams.renderer = "plantuml"
        test_config.diagrams.plantuml_server_url = "http://localhost:10005/"
        test_config.diagrams.plantuml_timeout = 30

        renderer = get_renderer(test_config)

        assert isinstance(renderer, PlantUMLRenderer)
        assert renderer.client.server_url == "http://localhost:10005"
        assert renderer.client.timeout == 30

    def test_unknown_renderer_raises_error(self, test_config):
        """Test that unknown renderer type raises error."""
        # This would fail Pydantic validation, but test the factory logic
        # by directly modifying the object after creation
        config = Configuration()
        # Bypass Pydantic validation for testing
        config.diagrams.__dict__["renderer"] = "unknown"

        with pytest.raises(ValueError, match="Unknown diagram renderer"):
            get_renderer(config)
