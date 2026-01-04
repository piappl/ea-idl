"""Tests for diagram_model.py - Diagram description structures."""

from eaidl.diagram_model import (
    DiagramType,
    OutputType,
    RelationType,
    MessageType,
    DiagramAttribute,
    DiagramClassNode,
    DiagramRelationship,
    DiagramClickHandler,
    DiagramNote,
    ClassDiagramDescription,
    SequenceParticipant,
    SequenceMessage,
    SequenceFragment,
    SequenceDiagramDescription,
    DiagramOutput,
)


class TestDiagramEnums:
    """Test diagram enum types."""

    def test_diagram_type(self):
        assert DiagramType.CLASS == "class"
        assert DiagramType.SEQUENCE == "sequence"

    def test_output_type(self):
        assert OutputType.TEXT == "text"
        assert OutputType.SVG == "svg"

    def test_relation_type(self):
        assert RelationType.INHERITANCE == "inheritance"
        assert RelationType.COMPOSITION == "composition"
        assert RelationType.AGGREGATION == "aggregation"
        assert RelationType.ASSOCIATION == "association"
        assert RelationType.DEPENDENCY == "dependency"

    def test_message_type(self):
        assert MessageType.SYNC == "sync"
        assert MessageType.ASYNC == "async"
        assert MessageType.RETURN == "return"


class TestDiagramAttribute:
    """Test DiagramAttribute dataclass."""

    def test_basic_attribute(self):
        attr = DiagramAttribute(name="id", type="int")
        assert attr.name == "id"
        assert attr.type == "int"
        assert attr.visibility == "+"
        assert attr.is_collection is False
        assert attr.is_optional is False
        assert attr.is_inherited is False

    def test_optional_collection_attribute(self):
        attr = DiagramAttribute(name="items", type="string", is_collection=True, is_optional=True)
        assert attr.is_collection is True
        assert attr.is_optional is True

    def test_inherited_attribute(self):
        attr = DiagramAttribute(name="base_id", type="int", is_inherited=True)
        assert attr.is_inherited is True


class TestDiagramClassNode:
    """Test DiagramClassNode dataclass."""

    def test_basic_class_node(self):
        node = DiagramClassNode(id="Message", name="Message")
        assert node.id == "Message"
        assert node.name == "Message"
        assert len(node.attributes) == 0
        assert len(node.stereotypes) == 0
        assert node.is_abstract is False
        assert len(node.namespace) == 0

    def test_class_node_with_attributes(self):
        attr1 = DiagramAttribute(name="id", type="int")
        attr2 = DiagramAttribute(name="name", type="string")
        node = DiagramClassNode(id="Message", name="Message", attributes=[attr1, attr2])
        assert len(node.attributes) == 2
        assert node.attributes[0].name == "id"
        assert node.attributes[1].name == "name"

    def test_class_node_with_stereotypes(self):
        node = DiagramClassNode(
            id="Message",
            name="Message",
            stereotypes=["struct", "experimental"],
            is_abstract=False,
        )
        assert len(node.stereotypes) == 2
        assert "struct" in node.stereotypes

    def test_abstract_class_node(self):
        node = DiagramClassNode(id="BaseClass", name="BaseClass", is_abstract=True)
        assert node.is_abstract is True

    def test_class_node_with_namespace(self):
        node = DiagramClassNode(id="Message", name="Message", namespace=["core", "data"])
        assert node.namespace == ["core", "data"]


class TestDiagramRelationship:
    """Test DiagramRelationship dataclass."""

    def test_inheritance_relationship(self):
        rel = DiagramRelationship(source_id="Child", target_id="Parent", type=RelationType.INHERITANCE)
        assert rel.source_id == "Child"
        assert rel.target_id == "Parent"
        assert rel.type == RelationType.INHERITANCE
        assert rel.source_label is None
        assert rel.source_cardinality is None

    def test_association_with_cardinality(self):
        rel = DiagramRelationship(
            source_id="Order",
            target_id="Item",
            type=RelationType.ASSOCIATION,
            source_cardinality="1",
            target_cardinality="*",
        )
        assert rel.source_cardinality == "1"
        assert rel.target_cardinality == "*"

    def test_relationship_with_labels(self):
        rel = DiagramRelationship(
            source_id="Person",
            target_id="Car",
            type=RelationType.ASSOCIATION,
            source_label="owner",
            target_label="owns",
        )
        assert rel.source_label == "owner"
        assert rel.target_label == "owns"


class TestDiagramClickHandler:
    """Test DiagramClickHandler dataclass."""

    def test_click_handler(self):
        handler = DiagramClickHandler(node_id="Message", link="../classes/core/Message.html")
        assert handler.node_id == "Message"
        assert handler.link == "../classes/core/Message.html"


class TestDiagramNote:
    """Test DiagramNote dataclass."""

    def test_standalone_note(self):
        note = DiagramNote(text="This is a note")
        assert note.text == "This is a note"
        assert note.attached_to is None

    def test_attached_note(self):
        note = DiagramNote(text="Note about Message", attached_to="Message")
        assert note.attached_to == "Message"


class TestClassDiagramDescription:
    """Test ClassDiagramDescription dataclass."""

    def test_empty_diagram(self):
        diagram = ClassDiagramDescription()
        assert len(diagram.nodes) == 0
        assert len(diagram.relationships) == 0
        assert len(diagram.click_handlers) == 0
        assert len(diagram.notes) == 0

    def test_diagram_with_nodes_and_relationships(self):
        node1 = DiagramClassNode(id="Parent", name="Parent")
        node2 = DiagramClassNode(id="Child", name="Child")
        rel = DiagramRelationship(source_id="Child", target_id="Parent", type=RelationType.INHERITANCE)

        diagram = ClassDiagramDescription(nodes=[node1, node2], relationships=[rel])

        assert len(diagram.nodes) == 2
        assert len(diagram.relationships) == 1
        assert diagram.relationships[0].type == RelationType.INHERITANCE

    def test_diagram_with_click_handlers(self):
        node = DiagramClassNode(id="Message", name="Message")
        handler = DiagramClickHandler(node_id="Message", link="../classes/Message.html")

        diagram = ClassDiagramDescription(nodes=[node], click_handlers=[handler])

        assert len(diagram.click_handlers) == 1
        assert diagram.click_handlers[0].node_id == "Message"


class TestSequenceParticipant:
    """Test SequenceParticipant dataclass."""

    def test_participant(self):
        participant = SequenceParticipant(id="Client", name="Client")
        assert participant.id == "Client"
        assert participant.name == "Client"


class TestSequenceMessage:
    """Test SequenceMessage dataclass."""

    def test_sync_message(self):
        msg = SequenceMessage(from_id="Client", to_id="Server", label="request()", message_type=MessageType.SYNC)
        assert msg.from_id == "Client"
        assert msg.to_id == "Server"
        assert msg.label == "request()"
        assert msg.message_type == MessageType.SYNC
        assert msg.stereotype is None

    def test_async_message(self):
        msg = SequenceMessage(
            from_id="Client",
            to_id="Server",
            label="notify()",
            message_type=MessageType.ASYNC,
        )
        assert msg.message_type == MessageType.ASYNC

    def test_message_with_stereotype(self):
        msg = SequenceMessage(from_id="A", to_id="B", label="call()", stereotype="create")
        assert msg.stereotype == "create"


class TestSequenceFragment:
    """Test SequenceFragment dataclass."""

    def test_fragment(self):
        msg = SequenceMessage(from_id="A", to_id="B", label="call()")
        fragment = SequenceFragment(fragment_type="alt", condition="x > 0", messages=[msg])
        assert fragment.fragment_type == "alt"
        assert fragment.condition == "x > 0"
        assert len(fragment.messages) == 1


class TestSequenceDiagramDescription:
    """Test SequenceDiagramDescription dataclass."""

    def test_empty_sequence_diagram(self):
        diagram = SequenceDiagramDescription()
        assert len(diagram.participants) == 0
        assert len(diagram.messages) == 0
        assert len(diagram.fragments) == 0
        assert len(diagram.notes) == 0

    def test_sequence_diagram_with_messages(self):
        p1 = SequenceParticipant(id="Client", name="Client")
        p2 = SequenceParticipant(id="Server", name="Server")
        msg = SequenceMessage(from_id="Client", to_id="Server", label="request()")

        diagram = SequenceDiagramDescription(participants=[p1, p2], messages=[msg])

        assert len(diagram.participants) == 2
        assert len(diagram.messages) == 1
        assert diagram.messages[0].label == "request()"


class TestDiagramOutput:
    """Test DiagramOutput dataclass."""

    def test_text_output(self):
        output = DiagramOutput(output_type=OutputType.TEXT, content="classDiagram\nclass Foo")
        assert output.output_type == OutputType.TEXT
        assert "classDiagram" in output.content
        assert output.error is None

    def test_svg_output(self):
        output = DiagramOutput(output_type=OutputType.SVG, content="<svg>...</svg>")
        assert output.output_type == OutputType.SVG
        assert "<svg>" in output.content

    def test_output_with_error(self):
        output = DiagramOutput(
            output_type=OutputType.TEXT,
            content="",
            error="Failed to render diagram",
        )
        assert output.error == "Failed to render diagram"
