"""Tests for mermaid_renderer.py - Mermaid diagram rendering."""

import pytest
from eaidl.renderers.mermaid_renderer import MermaidRenderer
from eaidl.diagram_model import (
    ClassDiagramDescription,
    DiagramClassNode,
    DiagramAttribute,
    DiagramRelationship,
    DiagramClickHandler,
    RelationType,
    OutputType,
)


class TestMermaidRenderer:
    """Test MermaidRenderer functionality."""

    @pytest.fixture
    def renderer(self):
        """Create a MermaidRenderer instance."""
        return MermaidRenderer()

    def test_empty_diagram(self, renderer):
        """Test rendering an empty diagram."""
        desc = ClassDiagramDescription()
        output = renderer.render_class_diagram(desc)

        assert output.output_type == OutputType.TEXT
        assert output.error is None
        assert "classDiagram" in output.content

    def test_single_class_no_attributes(self, renderer):
        """Test rendering a single class with no attributes."""
        node = DiagramClassNode(id="Message", name="Message")
        desc = ClassDiagramDescription(nodes=[node])

        output = renderer.render_class_diagram(desc)

        assert output.output_type == OutputType.TEXT
        assert "classDiagram" in output.content
        assert "class Message {" in output.content
        assert "}" in output.content

    def test_class_with_attributes(self, renderer):
        """Test rendering a class with attributes."""
        attr1 = DiagramAttribute(name="id", type="long")
        attr2 = DiagramAttribute(name="name", type="string", is_optional=True)
        node = DiagramClassNode(id="Message", name="Message", attributes=[attr1, attr2])
        desc = ClassDiagramDescription(nodes=[node])

        output = renderer.render_class_diagram(desc)

        content = output.content
        assert "class Message {" in content
        assert "+id long" in content
        assert "+name? string" in content

    def test_inherited_attributes_marked(self, renderer):
        """Test that inherited attributes are marked with asterisk."""
        attr1 = DiagramAttribute(name="base_id", type="long", is_inherited=True)
        attr2 = DiagramAttribute(name="child_name", type="string", is_inherited=False)
        node = DiagramClassNode(id="Child", name="Child", attributes=[attr1, attr2])
        desc = ClassDiagramDescription(nodes=[node])

        output = renderer.render_class_diagram(desc)

        content = output.content
        assert "+*base_id long" in content  # Inherited, marked with *
        assert "+child_name string" in content  # Not inherited

    def test_collection_attributes(self, renderer):
        """Test that collection attributes show array notation."""
        attr = DiagramAttribute(name="items", type="string", is_collection=True)
        node = DiagramClassNode(id="List", name="List", attributes=[attr])
        desc = ClassDiagramDescription(nodes=[node])

        output = renderer.render_class_diagram(desc)

        assert "+items string[]" in output.content

    def test_inheritance_relationship(self, renderer):
        """Test rendering inheritance relationship."""
        parent = DiagramClassNode(id="Base", name="Base")
        child = DiagramClassNode(id="Child", name="Child")
        rel = DiagramRelationship(source_id="Child", target_id="Base", type=RelationType.INHERITANCE)
        desc = ClassDiagramDescription(nodes=[parent, child], relationships=[rel])

        output = renderer.render_class_diagram(desc)

        assert "Child --|> Base" in output.content

    def test_composition_relationship(self, renderer):
        """Test rendering composition relationship."""
        node1 = DiagramClassNode(id="Person", name="Person")
        node2 = DiagramClassNode(id="Address", name="Address")
        rel = DiagramRelationship(source_id="Person", target_id="Address", type=RelationType.COMPOSITION)
        desc = ClassDiagramDescription(nodes=[node1, node2], relationships=[rel])

        output = renderer.render_class_diagram(desc)

        assert "Person *-- Address" in output.content

    def test_aggregation_relationship(self, renderer):
        """Test rendering aggregation relationship."""
        node1 = DiagramClassNode(id="Team", name="Team")
        node2 = DiagramClassNode(id="Player", name="Player")
        rel = DiagramRelationship(source_id="Team", target_id="Player", type=RelationType.AGGREGATION)
        desc = ClassDiagramDescription(nodes=[node1, node2], relationships=[rel])

        output = renderer.render_class_diagram(desc)

        assert "Team o-- Player" in output.content

    def test_dependency_relationship(self, renderer):
        """Test rendering dependency relationship."""
        node1 = DiagramClassNode(id="Union", name="Union")
        node2 = DiagramClassNode(id="Enum", name="Enum")
        rel = DiagramRelationship(source_id="Union", target_id="Enum", type=RelationType.DEPENDENCY)
        desc = ClassDiagramDescription(nodes=[node1, node2], relationships=[rel])

        output = renderer.render_class_diagram(desc)

        assert "Union ..> Enum" in output.content

    def test_association_without_cardinality(self, renderer):
        """Test rendering association without cardinality."""
        node1 = DiagramClassNode(id="A", name="A")
        node2 = DiagramClassNode(id="B", name="B")
        rel = DiagramRelationship(source_id="A", target_id="B", type=RelationType.ASSOCIATION)
        desc = ClassDiagramDescription(nodes=[node1, node2], relationships=[rel])

        output = renderer.render_class_diagram(desc)

        assert "A --> B" in output.content

    def test_association_with_cardinality(self, renderer):
        """Test rendering association with cardinality."""
        node1 = DiagramClassNode(id="Order", name="Order")
        node2 = DiagramClassNode(id="Item", name="Item")
        rel = DiagramRelationship(
            source_id="Order",
            target_id="Item",
            type=RelationType.ASSOCIATION,
            source_cardinality="1",
            target_cardinality="*",
        )
        desc = ClassDiagramDescription(nodes=[node1, node2], relationships=[rel])

        output = renderer.render_class_diagram(desc)

        assert 'Order "1" --> "*" Item' in output.content

    def test_click_handlers(self, renderer):
        """Test rendering click handlers."""
        node = DiagramClassNode(id="Message", name="Message")
        handler = DiagramClickHandler(node_id="Message", link="../classes/Message.html")
        desc = ClassDiagramDescription(nodes=[node], click_handlers=[handler])

        output = renderer.render_class_diagram(desc)

        assert 'click Message href "../classes/Message.html" _self' in output.content

    def test_multiple_classes_and_relationships(self, renderer):
        """Test rendering complex diagram with multiple classes and relationships."""
        node1 = DiagramClassNode(
            id="Base",
            name="Base",
            attributes=[DiagramAttribute(name="id", type="long")],
            is_abstract=True,
        )
        node2 = DiagramClassNode(
            id="Child",
            name="Child",
            attributes=[DiagramAttribute(name="name", type="string")],
        )
        node3 = DiagramClassNode(id="Helper", name="Helper")

        rel1 = DiagramRelationship(source_id="Child", target_id="Base", type=RelationType.INHERITANCE)
        rel2 = DiagramRelationship(source_id="Child", target_id="Helper", type=RelationType.ASSOCIATION)

        handler1 = DiagramClickHandler(node_id="Base", link="Base.html")
        handler2 = DiagramClickHandler(node_id="Child", link="Child.html")

        desc = ClassDiagramDescription(
            nodes=[node1, node2, node3],
            relationships=[rel1, rel2],
            click_handlers=[handler1, handler2],
        )

        output = renderer.render_class_diagram(desc)

        content = output.content
        # Check all classes present
        assert "class Base {" in content
        assert "class Child {" in content
        assert "class Helper {" in content

        # Check relationships
        assert "Child --|> Base" in content
        assert "Child --> Helper" in content

        # Check click handlers
        assert 'click Base href "Base.html" _self' in content
        assert 'click Child href "Child.html" _self' in content

    def test_special_characters_in_class_name(self, renderer):
        """Test that special characters in class names are handled."""
        # The renderer uses get_class_label which should handle special chars
        node = DiagramClassNode(id="MUV_1", name="MUV_#1")
        desc = ClassDiagramDescription(nodes=[node])

        output = renderer.render_class_diagram(desc)

        # Should not crash, content should be generated
        assert output.output_type == OutputType.TEXT
        assert "classDiagram" in output.content

    def test_stereotypes_not_rendered(self, renderer):
        """Test that stereotypes are not rendered in Mermaid (v11 limitation)."""
        node = DiagramClassNode(id="Message", name="Message", stereotypes=["struct", "experimental"])
        desc = ClassDiagramDescription(nodes=[node])

        output = renderer.render_class_diagram(desc)

        # Stereotypes should not appear in Mermaid output (v11 doesn't support them)
        assert "<<struct>>" not in output.content
        assert "<<experimental>>" not in output.content

        # But class should still be rendered
        assert "class Message {" in output.content
