"""Tests for HTML documentation link generation utilities."""

from eaidl.link_utils import (
    get_relative_path,
    generate_class_link,
    generate_package_link,
    generate_diagram_link,
    generate_index_link,
)


class TestGetRelativePath:
    """Test basic relative path calculation between namespaces."""

    def test_sibling_namespaces(self):
        """Test path between sibling namespaces."""
        result = get_relative_path(["core", "data"], ["core", "types"])
        assert result == "../types"

    def test_nested_to_parent_sibling(self):
        """Test path from nested namespace to parent's sibling."""
        result = get_relative_path(["core", "data", "nested"], ["core", "types"])
        assert result == "../../types"

    def test_parent_to_child(self):
        """Test path from parent to child namespace."""
        result = get_relative_path(["core"], ["core", "data"])
        assert result == "data"

    def test_same_namespace(self):
        """Test path within same namespace."""
        result = get_relative_path(["core", "data"], ["core", "data"])
        assert result == "."

    def test_empty_namespaces(self):
        """Test path from root to root."""
        result = get_relative_path([], [])
        assert result == "."


class TestGenerateClassLink:
    """Test class link generation from different page locations."""

    def test_from_package_to_class_same_namespace(self):
        """Link from package page to class in same namespace."""
        # From packages/core/data/index.html
        # To classes/core/data/Store.html
        result = generate_class_link(["core", "data"], ["core", "data"], "Store")
        assert result == "../../../classes/core/data/Store.html"

    def test_from_package_to_class_different_namespace(self):
        """Link from package page to class in different namespace."""
        # From packages/core/data/index.html
        # To classes/core/types/Identifier.html
        result = generate_class_link(["core", "data"], ["core", "types"], "Identifier")
        assert result == "../../../classes/core/types/Identifier.html"

    def test_from_index_to_class(self):
        """Link from index page (root) to class."""
        # From index.html (root)
        # To classes/core/data/Store.html
        result = generate_class_link([], ["core", "data"], "Store")
        assert result == "classes/core/data/Store.html"

    def test_from_nested_package_to_class(self):
        """Link from deeply nested package to class."""
        # From packages/core/data/nested/deep/index.html
        # To classes/core/types/Identifier.html
        result = generate_class_link(["core", "data", "nested", "deep"], ["core", "types"], "Identifier")
        assert result == "../../../../../classes/core/types/Identifier.html"


class TestGeneratePackageLink:
    """Test package link generation."""

    def test_from_package_to_sibling_package(self):
        """Link from package to sibling package."""
        # From packages/core/data/index.html
        # To packages/core/message/index.html
        result = generate_package_link(["core", "data"], ["core", "message"])
        assert result == "../../../packages/core/message/index.html"

    def test_from_package_to_parent_package(self):
        """Link from package to parent package."""
        # From packages/core/data/index.html
        # To packages/core/index.html
        result = generate_package_link(["core", "data"], ["core"])
        assert result == "../../../packages/core/index.html"

    def test_from_index_to_package(self):
        """Link from index page (root) to package."""
        # From index.html (root)
        # To packages/core/data/index.html
        result = generate_package_link([], ["core", "data"])
        assert result == "packages/core/data/index.html"

    def test_from_package_to_nested_package(self):
        """Link from package to nested package."""
        # From packages/core/index.html
        # To packages/core/data/types/index.html
        result = generate_package_link(["core"], ["core", "data", "types"])
        assert result == "../../packages/core/data/types/index.html"


class TestGenerateDiagramLink:
    """Test diagram link generation."""

    def test_from_package_to_diagram(self):
        """Link from package page to diagram page in same namespace."""
        # From packages/core/data/index.html
        # To packages/core/data/diagram.html
        result = generate_diagram_link(["core", "data"], ["core", "data"])
        assert result == "../../../packages/core/data/diagram.html"

    def test_from_index_to_diagram(self):
        """Link from index page to diagram."""
        # From index.html (root)
        # To packages/core/data/diagram.html
        result = generate_diagram_link([], ["core", "data"])
        assert result == "packages/core/data/diagram.html"


class TestGenerateIndexLink:
    """Test index link generation."""

    def test_from_package_to_index(self):
        """Link from package page to index."""
        # From packages/core/data/index.html
        # To index.html (root)
        result = generate_index_link(["core", "data"])
        assert result == "../../../index.html"

    def test_from_nested_package_to_index(self):
        """Link from nested package to index."""
        # From packages/core/data/nested/index.html
        # To index.html (root)
        result = generate_index_link(["core", "data", "nested"])
        assert result == "../../../../index.html"

    def test_from_index_to_index(self):
        """Link from index to itself."""
        # From index.html (root)
        # To index.html (root)
        result = generate_index_link([])
        assert result == "index.html"


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_single_level_namespace(self):
        """Test with single-level namespace."""
        result = generate_package_link(["core"], ["data"])
        assert result == "../../packages/data/index.html"

    def test_empty_from_namespace_variations(self):
        """Test all link types from root (empty namespace)."""
        assert generate_class_link([], ["core"], "Store") == "classes/core/Store.html"
        assert generate_package_link([], ["core"]) == "packages/core/index.html"
        assert generate_diagram_link([], ["core"]) == "packages/core/diagram.html"
        assert generate_index_link([]) == "index.html"
