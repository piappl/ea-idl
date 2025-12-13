"""Tests for HTML documentation export functionality."""

import pytest
import shutil
from eaidl.config import Configuration
from eaidl.load import ModelParser
from eaidl.html_export import export_html
from eaidl.transforms import flatten_abstract_classes


@pytest.fixture
def test_config():
    """Load test configuration using SQLite test database."""
    return Configuration(
        database_url="sqlite+pysqlite:///tests/data/nafv4.qea",
        root_packages=["core"],
    )


@pytest.fixture
def test_output_dir(tmp_path):
    """Create temporary output directory for tests."""
    output_dir = tmp_path / "test_docs"
    output_dir.mkdir()
    yield output_dir
    # Cleanup
    if output_dir.exists():
        shutil.rmtree(output_dir)


class TestHTMLExport:
    """Test HTML documentation export."""

    def test_basic_export(self, test_config, test_output_dir):
        """Test that basic HTML export creates expected files."""
        parser = ModelParser(test_config)
        packages = parser.load()
        flatten_abstract_classes(packages)

        export_html(test_config, packages, test_output_dir)

        # Check basic structure exists
        assert (test_output_dir / "index.html").exists()
        assert (test_output_dir / "assets").exists()
        assert (test_output_dir / "assets" / "js" / "bootstrap.bundle.min.js").exists()
        assert (test_output_dir / "assets" / "js" / "mermaid.min.js").exists()
        assert (test_output_dir / "assets" / "js" / "fuse.min.js").exists()
        assert (test_output_dir / "search.json").exists()

    def test_package_pages_created(self, test_config, test_output_dir):
        """Test that package pages are created."""
        parser = ModelParser(test_config)
        packages = parser.load()
        flatten_abstract_classes(packages)

        export_html(test_config, packages, test_output_dir)

        # Check package pages
        assert (test_output_dir / "packages" / "core" / "index.html").exists()
        assert (test_output_dir / "packages" / "core" / "message" / "index.html").exists()
        assert (test_output_dir / "packages" / "core" / "data" / "index.html").exists()

    def test_class_pages_created(self, test_config, test_output_dir):
        """Test that class pages are created."""
        parser = ModelParser(test_config)
        packages = parser.load()
        flatten_abstract_classes(packages)

        export_html(test_config, packages, test_output_dir)

        # Check some class pages
        assert (test_output_dir / "classes" / "core" / "message" / "Message.html").exists()
        assert (test_output_dir / "classes" / "core" / "data" / "Store.html").exists()

    def test_diagram_pages_created(self, test_config, test_output_dir):
        """Test that diagram pages are created."""
        parser = ModelParser(test_config)
        packages = parser.load()
        flatten_abstract_classes(packages)

        export_html(test_config, packages, test_output_dir)

        # Check diagram pages
        assert (test_output_dir / "packages" / "core" / "message" / "diagram.html").exists()
        assert (test_output_dir / "packages" / "core" / "data" / "diagram.html").exists()

    def test_index_links_are_correct(self, test_config, test_output_dir):
        """Test that index page has correct links (no leading ../)."""
        parser = ModelParser(test_config)
        packages = parser.load()
        flatten_abstract_classes(packages)

        export_html(test_config, packages, test_output_dir)

        index_content = (test_output_dir / "index.html").read_text()

        # Links from index should be packages/... not ../packages/...
        assert 'href="packages/core/index.html"' in index_content
        assert 'href="../packages/' not in index_content

    def test_package_links_are_correct(self, test_config, test_output_dir):
        """Test that package page links are correct."""
        parser = ModelParser(test_config)
        packages = parser.load()
        flatten_abstract_classes(packages)

        export_html(test_config, packages, test_output_dir)

        pkg_content = (test_output_dir / "packages" / "core" / "message" / "index.html").read_text()

        # Links from package pages should use ../../../
        assert 'href="../../../classes/core/message/' in pkg_content
        assert 'href="../../../index.html"' in pkg_content

    def test_mermaid_diagrams_present(self, test_config, test_output_dir):
        """Test that mermaid diagrams are generated."""
        parser = ModelParser(test_config)
        packages = parser.load()
        flatten_abstract_classes(packages)

        export_html(test_config, packages, test_output_dir)

        diagram_content = (test_output_dir / "packages" / "core" / "message" / "diagram.html").read_text()

        # Check for mermaid syntax
        assert "classDiagram" in diagram_content
        assert "class Message" in diagram_content or "class DataMessage" in diagram_content

        # Check for click handlers
        assert "click" in diagram_content
        assert "href" in diagram_content

    def test_search_index_generated(self, test_config, test_output_dir):
        """Test that search index is generated with content."""
        parser = ModelParser(test_config)
        packages = parser.load()
        flatten_abstract_classes(packages)

        export_html(test_config, packages, test_output_dir)

        import json

        search_data = json.loads((test_output_dir / "search.json").read_text())

        # Should have search entries
        assert len(search_data) > 0

        # Check structure of entries
        first_entry = search_data[0]
        assert "name" in first_entry
        assert "type" in first_entry
        assert "namespace" in first_entry
        assert "url" in first_entry
