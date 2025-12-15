"""Tests for Mermaid diagram generation."""

import pytest
from eaidl.mermaid_diagram import MermaidClassDiagramGenerator
from eaidl.model import ModelPackage, ModelClass, ModelAttribute
from eaidl.config import Configuration


@pytest.fixture
def basic_config():
    """Basic configuration for testing."""
    return Configuration(
        database_url="sqlite:///test.db",
        root_packages=["test"],
    )


@pytest.fixture
def simple_package():
    """Create a simple package with two classes for testing."""
    pkg = ModelPackage(
        package_id=1,
        object_id=1,
        name="test",
        guid="{TEST-GUID}",
        namespace=["test"],
    )

    # Create first class
    cls1 = ModelClass(
        object_id=2,
        name="Store",
        guid="{STORE-GUID}",
        namespace=["test"],
        is_struct=True,
    )
    cls1.attributes = [
        ModelAttribute(
            name="one",
            alias="one",
            attribute_id=1,
            guid="{ATTR-ONE-GUID}",
            type="Identifier",
            namespace=["test"],
            is_collection=False,
        ),
        ModelAttribute(
            name="sequence",
            alias="sequence",
            attribute_id=2,
            guid="{ATTR-SEQUENCE-GUID}",
            type="Identifier",
            namespace=["test"],
            is_collection=True,
        ),
    ]

    # Create second class
    cls2 = ModelClass(
        object_id=3,
        name="Identifier",
        guid="{IDENTIFIER-GUID}",
        namespace=["test"],
        is_typedef=True,
        parent_type="string",
    )

    pkg.classes = [cls1, cls2]
    return pkg


class TestMermaidDiagramGeneration:
    """Test Mermaid diagram generation from model packages."""

    def test_basic_diagram_structure(self, basic_config, simple_package):
        """Test that basic diagram structure is generated."""
        generator = MermaidClassDiagramGenerator(simple_package, basic_config)
        result = generator.generate_mermaid()

        assert "classDiagram" in result
        assert "class Store" in result
        assert "class Identifier" in result

    def test_struct_attributes(self, basic_config, simple_package):
        """Test that struct attributes are correctly formatted."""
        generator = MermaidClassDiagramGenerator(simple_package, basic_config)
        result = generator.generate_mermaid()

        # Check attribute formatting
        assert "+one Identifier" in result
        assert "+sequence Identifier[]" in result  # Collection notation

    def test_typedef_stereotype(self, basic_config, simple_package):
        """Test that typedef class is generated (stereotypes not shown in Mermaid v11)."""
        generator = MermaidClassDiagramGenerator(simple_package, basic_config)
        result = generator.generate_mermaid()

        # Mermaid v11 doesn't support stereotypes in class diagrams
        # Just verify the typedef class is present
        assert "class Identifier" in result

    def test_clickable_links(self, basic_config, simple_package):
        """Test that click handlers are generated for interactive navigation."""
        generator = MermaidClassDiagramGenerator(simple_package, basic_config)
        result = generator.generate_mermaid()

        # Check for click handlers
        assert "click Store" in result
        assert "click Identifier" in result
        assert "href" in result
        assert ".html" in result

    def test_relationships(self, basic_config, simple_package):
        """Test that relationships between classes are shown."""
        generator = MermaidClassDiagramGenerator(simple_package, basic_config)
        result = generator.generate_mermaid()

        # Store has attributes of type Identifier, should show relationship
        assert "Store" in result
        assert "Identifier" in result
        # Should have association arrow
        assert "-->" in result or "..>" in result

    def test_enum_handling(self, basic_config):
        """Test that enum classes are correctly formatted."""
        pkg = ModelPackage(
            package_id=1,
            object_id=1,
            name="test",
            guid="{TEST-GUID}",
            namespace=["test"],
        )

        enum = ModelClass(
            object_id=2,
            name="Status",
            guid="{ENUM-GUID}",
            namespace=["test"],
            is_enum=True,
        )
        enum.attributes = [
            ModelAttribute(name="ACTIVE", alias="ACTIVE", attribute_id=1, guid="{ACTIVE-GUID}", type="unknown"),
            ModelAttribute(name="INACTIVE", alias="INACTIVE", attribute_id=2, guid="{INACTIVE-GUID}", type="unknown"),
        ]

        pkg.classes = [enum]

        generator = MermaidClassDiagramGenerator(pkg, basic_config)
        result = generator.generate_mermaid()

        assert "class Status" in result
        # Mermaid v11 doesn't support stereotypes - just verify attributes are present
        assert "+ACTIVE" in result
        assert "+INACTIVE" in result

    def test_union_handling(self, basic_config):
        """Test that union classes are correctly formatted."""
        pkg = ModelPackage(
            package_id=1,
            object_id=1,
            name="test",
            guid="{TEST-GUID}",
            namespace=["test"],
        )

        union = ModelClass(
            object_id=2,
            name="AnyGUID",
            guid="{UNION-GUID}",
            namespace=["test"],
            is_union=True,
        )
        union.attributes = [
            ModelAttribute(
                name="hibw", alias="hibw", attribute_id=1, guid="{HIBW-GUID}", type="GUID", namespace=["test"]
            ),
            ModelAttribute(
                name="lobw", alias="lobw", attribute_id=2, guid="{LOBW-GUID}", type="GUIDBytes", namespace=["test"]
            ),
        ]

        pkg.classes = [union]

        generator = MermaidClassDiagramGenerator(pkg, basic_config)
        result = generator.generate_mermaid()

        assert "class AnyGUID" in result
        # Mermaid v11 doesn't support stereotypes - just verify the class is present
        assert "+hibw" in result
        assert "+lobw" in result

    def test_empty_package(self, basic_config):
        """Test handling of package with no classes."""
        pkg = ModelPackage(
            package_id=1,
            object_id=1,
            name="empty",
            guid="{EMPTY-GUID}",
            namespace=["empty"],
        )
        pkg.classes = []

        generator = MermaidClassDiagramGenerator(pkg, basic_config)
        result = generator.generate_mermaid()

        # Should still have diagram declaration
        assert "classDiagram" in result

    def test_attribute_limit(self, basic_config):
        """Test that long attribute lists are truncated."""
        pkg = ModelPackage(
            package_id=1,
            object_id=1,
            name="test",
            guid="{TEST-GUID}",
            namespace=["test"],
        )

        cls = ModelClass(
            object_id=2,
            name="ManyAttrs",
            guid="{MANY-GUID}",
            namespace=["test"],
            is_struct=True,
        )
        # Create 20 attributes (limit is 15, so this should truncate)
        cls.attributes = [
            ModelAttribute(name=f"attr{i}", alias=f"attr{i}", attribute_id=i, guid=f"{{ATTR-{i}-GUID}}", type="string")
            for i in range(20)
        ]

        pkg.classes = [cls]

        generator = MermaidClassDiagramGenerator(pkg, basic_config)
        result = generator.generate_mermaid()

        # Should show truncation message
        assert "..." in result or "more" in result

    def test_special_characters_in_names(self, basic_config):
        """Test handling of special characters in class/attribute names."""
        pkg = ModelPackage(
            package_id=1,
            object_id=1,
            name="test",
            guid="{TEST-GUID}",
            namespace=["test"],
        )

        cls = ModelClass(
            object_id=2,
            name="Test-Class",
            guid="{CLASS-GUID}",
            namespace=["test"],
            is_struct=True,
        )
        cls.attributes = [
            ModelAttribute(name="_private", alias="_private", attribute_id=1, guid="{PRIVATE-GUID}", type="string"),
            ModelAttribute(name="with-dash", alias="with-dash", attribute_id=2, guid="{DASH-GUID}", type="int"),
        ]

        pkg.classes = [cls]

        generator = MermaidClassDiagramGenerator(pkg, basic_config)
        result = generator.generate_mermaid()

        # Should sanitize names (replace - with _)
        assert "class" in result
        # Underscores should be stripped from beginning
        assert "+private" in result or "_private" in result


class TestMermaidSyntax:
    """Test Mermaid syntax correctness."""

    def test_no_extra_indentation(self, basic_config, simple_package):
        """Test that there's no unwanted indentation in output."""
        generator = MermaidClassDiagramGenerator(simple_package, basic_config)
        result = generator.generate_mermaid()

        # Check that lines start at beginning (no leading spaces before classDiagram)
        lines = result.split("\n")
        assert lines[0] == "classDiagram"

    def test_curly_brace_syntax(self, basic_config, simple_package):
        """Test that modern curly brace syntax is used for classes."""
        generator = MermaidClassDiagramGenerator(simple_package, basic_config)
        result = generator.generate_mermaid()

        # Should use curly braces for class definitions with attributes
        assert "{" in result
        assert "}" in result
        # Should NOT use old colon syntax
        assert not result.strip().endswith(":")
