"""Tests for diagram_builder.py - Building diagram descriptions from model."""

from eaidl.diagram_builder import ClassDiagramBuilder
from eaidl.diagram_model import RelationType


class TestClassDiagramBuilder:
    """Test ClassDiagramBuilder functionality."""

    def test_empty_package(self, test_config, create_package):
        """Test building diagram from empty package."""
        package = create_package(name="Empty", classes=[])
        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        assert len(diagram.nodes) == 0
        assert len(diagram.relationships) == 0
        assert len(diagram.click_handlers) == 0

    def test_single_class_with_attributes(self, test_config, struct_class, create_attribute, create_package):
        """Test building diagram with single class containing attributes."""
        attr1 = create_attribute(name="id", type="long")
        attr2 = create_attribute(name="name", type="string", is_optional=True)

        cls = struct_class(name="Message", attributes=[attr1, attr2])
        package = create_package(name="TestPkg", classes=[cls])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        # Verify nodes
        assert len(diagram.nodes) == 1
        node = diagram.nodes[0]
        assert node.id == "Message"
        assert node.name == "Message"
        assert len(node.attributes) == 2
        assert node.attributes[0].name == "id"
        assert node.attributes[0].type == "long"
        assert node.attributes[1].name == "name"
        assert node.attributes[1].is_optional is True

    def test_inheritance_relationship(self, test_config, struct_class, create_package):
        """Test that inheritance relationships are built correctly."""
        parent = struct_class(name="BaseMessage")
        child = struct_class(name="SpecificMessage", generalization=["root", "BaseMessage"])

        package = create_package(name="TestPkg", classes=[parent, child])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        # Find inheritance relationship
        inheritance_rels = [r for r in diagram.relationships if r.type == RelationType.INHERITANCE]
        assert len(inheritance_rels) == 1
        rel = inheritance_rels[0]
        assert rel.source_id == "SpecificMessage"
        assert rel.target_id == "BaseMessage"

    def test_composition_relationship(self, test_config, struct_class, create_attribute, create_package):
        """Test that composition relationships are built (non-optional attributes)."""
        target = struct_class(name="Address")
        attr = create_attribute(
            name="address",
            type="Address",
            namespace=["root"],
            is_optional=False,
        )
        source = struct_class(name="Person", attributes=[attr])

        package = create_package(name="TestPkg", classes=[source, target])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        # Find composition relationship
        composition_rels = [r for r in diagram.relationships if r.type == RelationType.COMPOSITION]
        assert len(composition_rels) == 1
        rel = composition_rels[0]
        assert rel.source_id == "Person"
        assert rel.target_id == "Address"

    def test_association_relationship(self, test_config, struct_class, create_attribute, create_package):
        """Test that association relationships are built (optional attributes)."""
        target = struct_class(name="Company")
        attr = create_attribute(name="employer", type="Company", namespace=["root"], is_optional=True)
        source = struct_class(name="Person", attributes=[attr])

        package = create_package(name="TestPkg", classes=[source, target])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        # Find association relationship
        association_rels = [r for r in diagram.relationships if r.type == RelationType.ASSOCIATION]
        assert len(association_rels) == 1
        rel = association_rels[0]
        assert rel.source_id == "Person"
        assert rel.target_id == "Company"
        assert rel.source_cardinality is None  # Optional, not collection

    def test_collection_association(self, test_config, struct_class, create_attribute, create_package):
        """Test that collection associations show cardinality."""
        target = struct_class(name="Item")
        attr = create_attribute(
            name="items",
            type="Item",
            namespace=["root"],
            is_collection=True,
        )
        source = struct_class(name="Order", attributes=[attr])

        package = create_package(name="TestPkg", classes=[source, target])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        # Find collection association
        collection_rels = [
            r for r in diagram.relationships if r.type == RelationType.ASSOCIATION and r.target_cardinality == "*"
        ]
        assert len(collection_rels) == 1
        rel = collection_rels[0]
        assert rel.source_id == "Order"
        assert rel.target_id == "Item"
        assert rel.source_cardinality == "1"
        assert rel.target_cardinality == "*"

    def test_union_enum_dependency(self, test_config, union_class, enum_class, create_package):
        """Test that union→enum dependencies are built."""
        enum = enum_class(name="MessageType")
        union = union_class(name="MessageUnion", union_enum="root::MessageType")

        package = create_package(name="TestPkg", classes=[enum, union])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        # Find dependency relationship
        dependency_rels = [r for r in diagram.relationships if r.type == RelationType.DEPENDENCY]
        assert len(dependency_rels) == 1
        rel = dependency_rels[0]
        assert rel.source_id == "MessageUnion"
        assert rel.target_id == "MessageType"

    def test_click_handlers_generated(self, test_config, struct_class, create_package):
        """Test that click handlers are generated for all classes."""
        cls1 = struct_class(name="Class1", namespace=["root", "pkg"])
        cls2 = struct_class(name="Class2", namespace=["root", "pkg"])

        package = create_package(name="pkg", classes=[cls1, cls2])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        assert len(diagram.click_handlers) == 2
        handler_ids = {h.node_id for h in diagram.click_handlers}
        assert "Class1" in handler_ids
        assert "Class2" in handler_ids

        # Check that links are generated
        for handler in diagram.click_handlers:
            assert handler.link.endswith(".html")

    def test_stereotype_notes_generated(self, test_config, struct_class, create_package):
        """Test that stereotype notes are generated for classes with stereotypes."""
        cls = struct_class(
            name="Message",
            stereotypes=["idlStruct", "experimental"],
        )
        package = create_package(name="TestPkg", classes=[cls])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        # Check that notes are generated for stereotypes
        assert len(diagram.notes) > 0
        note = diagram.notes[0]
        assert note.attached_to == "Message"
        assert "<<idlStruct>>" in note.text or "<<experimental>>" in note.text

    def test_max_attributes_limit(self, test_config, struct_class, create_attribute, create_package):
        """Test that attributes are limited to max_attributes_displayed."""
        # Create class with more attributes than the limit
        attrs = [create_attribute(name=f"attr{i}", type="long") for i in range(20)]
        cls = struct_class(name="BigClass", attributes=attrs)
        package = create_package(name="TestPkg", classes=[cls])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        # Should only have max_attributes_displayed attributes
        node = diagram.nodes[0]
        assert len(node.attributes) == test_config.diagrams.max_attributes_displayed

    def test_inherited_attributes_marked(self, test_config, struct_class, create_attribute, create_package):
        """Test that inherited attributes are marked correctly."""
        parent_attr = create_attribute(name="base_id", type="long")
        parent = struct_class(name="Base", attributes=[parent_attr])

        child_attr = create_attribute(name="child_name", type="string")
        child = struct_class(name="Child", generalization=["root", "Base"], attributes=[child_attr])

        package = create_package(name="TestPkg", classes=[parent, child])

        builder = ClassDiagramBuilder(package, test_config, all_packages=[package])
        diagram = builder.build()

        # Find the Child node
        child_node = [n for n in diagram.nodes if n.id == "Child"][0]

        # Should have both inherited and own attributes
        assert len(child_node.attributes) == 2

        # First attribute should be inherited
        assert child_node.attributes[0].is_inherited is True
        assert child_node.attributes[0].name == "base_id"

        # Second attribute should not be inherited
        assert child_node.attributes[1].is_inherited is False
        assert child_node.attributes[1].name == "child_name"

    def test_abstract_class_marked(self, test_config, struct_class, create_package):
        """Test that abstract classes are marked correctly."""
        cls = struct_class(name="AbstractBase", is_abstract=True)
        package = create_package(name="TestPkg", classes=[cls])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        node = diagram.nodes[0]
        assert node.is_abstract is True

    def test_namespace_captured(self, test_config, struct_class, create_package):
        """Test that class namespace is captured correctly."""
        cls = struct_class(name="Message", namespace=["root", "data", "messages"])
        package = create_package(name="messages", classes=[cls])

        builder = ClassDiagramBuilder(package, test_config)
        diagram = builder.build()

        node = diagram.nodes[0]
        assert node.namespace == ["root", "data", "messages"]
