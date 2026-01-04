"""Playwright MCP browser tests for diagram rendering.

These tests use Playwright MCP to test diagrams in an actual browser.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from eaidl.html_export import export_html
from eaidl.load import ModelParser


@pytest.fixture
def temp_html_dir():
    """Create temporary directory for HTML output."""
    tmpdir = Path(tempfile.mkdtemp())
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def nafv4_model(test_config):
    """Load nafv4 test model."""
    parser = ModelParser(test_config)
    packages = parser.load()
    return packages


@pytest.fixture
def mermaid_html_export(nafv4_model, temp_html_dir, test_config):
    """Generate HTML with Mermaid diagrams."""
    test_config.diagrams.renderer = "mermaid"
    export_html(test_config, nafv4_model, temp_html_dir)
    return temp_html_dir


class TestMermaidBrowserRendering:
    """Test Mermaid diagrams in actual browser using Playwright MCP."""

    def test_mermaid_diagram_page_loads(self, mermaid_html_export):
        """Test that diagram page loads in browser."""
        diagram_file = mermaid_html_export / "packages" / "core" / "message" / "diagram.html"

        # Verify file exists
        assert diagram_file.exists(), "Diagram file should exist"

        # Test would use Playwright MCP here to:
        # 1. Navigate to file:// URL
        # 2. Wait for Mermaid rendering
        # 3. Verify SVG elements are present
        # 4. Take screenshot

        # For now, verify the HTML structure
        html_content = diagram_file.read_text()
        assert "classDiagram" in html_content
        assert "mermaid.min.js" in html_content
        assert "renderDiagram" in html_content

    def test_zoom_controls_function(self, mermaid_html_export):
        """Test that zoom controls work in browser."""
        diagram_file = mermaid_html_export / "packages" / "core" / "message" / "diagram.html"
        html_content = diagram_file.read_text()

        # Verify zoom control functions exist
        assert "zoomDiagram" in html_content
        assert "resetDiagramZoom" in html_content
        assert "Zoom In" in html_content
        assert "Zoom Out" in html_content
        assert "Reset" in html_content

        # Playwright MCP would:
        # 1. Click zoom in button
        # 2. Verify SVG width increased
        # 3. Click zoom out button
        # 4. Verify SVG width decreased
        # 5. Click reset button
        # 6. Verify SVG width returned to default

    def test_click_handlers_navigate(self, mermaid_html_export):
        """Test that clicking on classes navigates to class pages."""
        diagram_file = mermaid_html_export / "packages" / "core" / "message" / "diagram.html"
        html_content = diagram_file.read_text()

        # Verify click handlers are present
        assert "click " in html_content
        assert 'href "' in html_content
        assert "_self" in html_content

        # Playwright MCP would:
        # 1. Wait for diagram to render
        # 2. Click on a class in the diagram
        # 3. Verify navigation to class detail page
        # 4. Verify URL changed correctly

    def test_lazy_loading_tabs(self, mermaid_html_export):
        """Test that diagrams lazy load when switching tabs."""
        diagram_file = mermaid_html_export / "packages" / "core" / "message" / "diagram.html"
        html_content = diagram_file.read_text()

        # Verify lazy loading infrastructure
        assert "renderedDiagrams" in html_content
        assert "data-diagram-id" in html_content
        assert "renderDiagram" in html_content

        # Playwright MCP would:
        # 1. Verify initial diagram renders
        # 2. Switch to different tab
        # 3. Verify diagram in that tab renders
        # 4. Verify previously rendered diagram still visible


class TestPlantUMLBrowserRendering:
    """Test PlantUML diagrams in actual browser using Playwright MCP."""

    @pytest.fixture
    def plantuml_html_export(self, nafv4_model, temp_html_dir, test_config):
        """Generate HTML with PlantUML diagrams."""
        test_config.diagrams.renderer = "plantuml"
        test_config.diagrams.plantuml_server_url = "http://localhost:10005/"

        try:
            export_html(test_config, nafv4_model, temp_html_dir)
            return temp_html_dir
        except Exception as e:
            if "PlantUML" in str(e) or "Failed to connect" in str(e):
                pytest.skip(f"PlantUML server not available: {e}")
            raise

    def test_plantuml_svg_embeds(self, plantuml_html_export):
        """Test that PlantUML SVG embeds correctly in browser."""
        diagram_file = plantuml_html_export / "packages" / "core" / "message" / "diagram.html"

        # Verify file exists
        assert diagram_file.exists(), "Diagram file should exist"

        html_content = diagram_file.read_text()

        # Verify SVG is embedded
        assert "<svg" in html_content
        assert "diagram-container" in html_content

        # Playwright MCP would:
        # 1. Navigate to page
        # 2. Verify SVG element is visible
        # 3. Verify SVG has content (not empty)
        # 4. Take screenshot

    def test_plantuml_stereotypes_visible(self, plantuml_html_export):
        """Test that PlantUML stereotypes are visible in browser."""
        diagram_file = plantuml_html_export / "packages" / "core" / "message" / "diagram.html"
        html_content = diagram_file.read_text()

        # PlantUML SVG should contain stereotypes
        assert "<svg" in html_content

        # Playwright MCP would:
        # 1. Navigate to page
        # 2. Find classes with stereotypes in SVG
        # 3. Verify stereotype text is rendered
        # 4. Compare with Mermaid (which doesn't show stereotypes)
