"""
Demo test showing Mermaid diagram output with special characters.

This demonstrates that class names with #, <, >, and other special
characters are properly sanitized and displayed.
"""

from eaidl.mermaid_diagram import MermaidClassDiagramGenerator
from eaidl.model import ModelPackage, ModelClass, ModelAttribute
from eaidl.config import Configuration


def test_diagram_with_special_chars():
    """Test that diagrams handle special characters in class names."""
    # Create config with minimal settings
    config = Configuration()

    # Create classes with problematic names
    class1 = ModelClass(
        name="MUV_#1",  # Hash symbol
        object_id=1,
        namespace=["test"],
        attributes=[
            ModelAttribute(
                name="data",
                alias="data",
                attribute_id=1,
                guid="{guid-1}",
                type="string",
                is_collection=False,
                is_optional=False,
            )
        ],
    )

    class2 = ModelClass(
        name="Data<T>",  # Angle brackets (generics)
        object_id=2,
        namespace=["test"],
        attributes=[
            ModelAttribute(
                name="value#1",  # Hash in attribute
                alias="value#1",
                attribute_id=2,
                guid="{guid-2}",
                type="int",
                is_collection=False,
                is_optional=False,
            )
        ],
    )

    class3 = ModelClass(
        name="Service::Client",  # Namespace separator
        object_id=3,
        namespace=["test"],
        attributes=[],
    )

    # Create package
    package = ModelPackage(
        name="test",
        package_id=1,
        object_id=100,
        guid="{pkg-guid}",
        namespace=[],
        classes=[class1, class2, class3],
    )

    # Generate diagram
    generator = MermaidClassDiagramGenerator(package, config, all_packages=[package])
    diagram = generator.generate_mermaid()

    print("\n" + "=" * 60)
    print("Generated Mermaid Diagram:")
    print("=" * 60)
    print(diagram)
    print("=" * 60 + "\n")

    # Verify safe IDs are used
    assert "MUV_1" in diagram  # Hash removed from ID
    assert "DataT" in diagram  # Angle brackets removed from ID
    assert "Service_Client" in diagram  # :: converted to _

    # Verify label syntax is used for display names
    assert 'MUV_1["MUV_#1"]' in diagram  # Original name preserved in label
    assert 'DataT["Data<T>"]' in diagram  # Original name preserved in label
    assert 'Service_Client["Service::Client"]' in diagram  # Original name preserved in label

    # Verify attributes are sanitized
    assert "+data string" in diagram  # Simple attribute
    assert "+value1 int" in diagram  # Attribute with hash removed

    # Verify diagram is valid Mermaid syntax
    assert diagram.startswith("classDiagram")
    assert "class MUV_1" in diagram or 'class MUV_1["MUV_#1"]' in diagram


def test_relationship_with_special_chars():
    """Test that relationships work with sanitized names."""
    config = Configuration()

    # Create parent class with special chars
    parent = ModelClass(
        name="Base<T>",
        object_id=1,
        namespace=["test"],
        attributes=[],
    )

    # Create child that inherits
    child = ModelClass(
        name="Derived#1",
        object_id=2,
        namespace=["test"],
        attributes=[],
        generalization=["test", "Base<T>"],  # Inherits from Base<T>
    )

    package = ModelPackage(
        name="test",
        package_id=1,
        object_id=100,
        guid="{pkg-guid}",
        namespace=[],
        classes=[parent, child],
    )

    generator = MermaidClassDiagramGenerator(package, config, all_packages=[package])
    diagram = generator.generate_mermaid()

    print("\n" + "=" * 60)
    print("Diagram with Inheritance:")
    print("=" * 60)
    print(diagram)
    print("=" * 60 + "\n")

    # Verify both classes use safe IDs
    assert "BaseT" in diagram
    assert "Derived1" in diagram

    # Verify inheritance relationship uses safe IDs
    assert "Derived1 --|> BaseT" in diagram

    # Verify display names are preserved
    assert 'BaseT["Base<T>"]' in diagram
    assert 'Derived1["Derived#1"]' in diagram
