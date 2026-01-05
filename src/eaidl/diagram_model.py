"""
Diagram description model - Renderer-agnostic diagram structures.

This module defines renderer-agnostic diagram description classes that separate
the "what to render" from "how to render it". Diagram builders create these
descriptions from EA models, and renderers (Mermaid, PlantUML) consume them
to generate format-specific output.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Protocol


class DiagramType(str, Enum):
    """Type of diagram."""

    CLASS = "class"
    SEQUENCE = "sequence"


class OutputType(str, Enum):
    """Type of diagram output."""

    TEXT = "text"  # Mermaid text syntax
    SVG = "svg"  # PlantUML SVG output


class RelationType(str, Enum):
    """Type of relationship between classes."""

    INHERITANCE = "inheritance"  # Generalization
    COMPOSITION = "composition"  # Strong ownership
    AGGREGATION = "aggregation"  # Weak ownership
    ASSOCIATION = "association"  # Simple reference
    DEPENDENCY = "dependency"  # Dotted line (e.g., union→enum)


class MessageType(str, Enum):
    """Type of message in sequence diagram."""

    SYNC = "sync"  # Synchronous call
    ASYNC = "async"  # Asynchronous call
    RETURN = "return"  # Return message


@dataclass
class DiagramAttribute:
    """Represents an attribute in a class diagram."""

    name: str
    type: str
    visibility: str = "+"  # +, -, #
    is_collection: bool = False
    is_optional: bool = False
    is_inherited: bool = False


@dataclass
class DiagramClassNode:
    """Represents a class/struct in a class diagram."""

    id: str  # Sanitized identifier
    name: str  # Display name
    attributes: List[DiagramAttribute] = field(default_factory=list)
    stereotypes: List[str] = field(default_factory=list)
    is_abstract: bool = False
    namespace: List[str] = field(default_factory=list)


@dataclass
class DiagramRelationship:
    """Represents a relationship between classes."""

    source_id: str
    target_id: str
    type: RelationType
    source_label: Optional[str] = None
    target_label: Optional[str] = None
    source_cardinality: Optional[str] = None
    target_cardinality: Optional[str] = None
    stereotypes: List[str] = field(default_factory=list)


@dataclass
class DiagramClickHandler:
    """Represents a click handler for navigation."""

    node_id: str
    link: str  # Relative URL


@dataclass
class DiagramNote:
    """Represents a note in a diagram."""

    text: str
    attached_to: Optional[str] = None  # Node ID, if attached
    rect_top: int = 0  # Y-position for ordering in sequence diagrams


@dataclass
class ClassDiagramDescription:
    """Complete description of a class diagram."""

    nodes: List[DiagramClassNode] = field(default_factory=list)
    relationships: List[DiagramRelationship] = field(default_factory=list)
    click_handlers: List[DiagramClickHandler] = field(default_factory=list)
    notes: List[DiagramNote] = field(default_factory=list)


@dataclass
class SequenceParticipant:
    """Represents a participant in a sequence diagram."""

    id: str  # Sanitized identifier
    name: str  # Display name


@dataclass
class SequenceMessage:
    """Represents a message in a sequence diagram."""

    from_id: str
    to_id: str
    label: str
    message_type: MessageType = MessageType.SYNC
    stereotype: Optional[str] = None


@dataclass
class SequenceFragment:
    """Represents a fragment (alt, opt, loop, etc.) in a sequence diagram."""

    fragment_type: str  # alt, opt, loop, etc.
    condition: str
    messages: List[SequenceMessage] = field(default_factory=list)


@dataclass
class SequenceDiagramDescription:
    """Complete description of a sequence diagram."""

    participants: List[SequenceParticipant] = field(default_factory=list)
    messages: List[SequenceMessage] = field(default_factory=list)
    fragments: List[SequenceFragment] = field(default_factory=list)
    notes: List[DiagramNote] = field(default_factory=list)


@dataclass
class DiagramOutput:
    """Container for rendered diagram output."""

    output_type: OutputType
    content: str  # Either Mermaid text or SVG XML
    error: Optional[str] = None


class DiagramRenderer(Protocol):
    """Protocol for diagram renderers."""

    def render_class_diagram(self, desc: ClassDiagramDescription) -> DiagramOutput:
        """
        Render a class diagram to format-specific output.

        :param desc: Class diagram description
        :return: Diagram output (text or SVG)
        """
        ...

    def render_sequence_diagram(self, desc: SequenceDiagramDescription) -> DiagramOutput:
        """
        Render a sequence diagram to format-specific output.

        :param desc: Sequence diagram description
        :return: Diagram output (text or SVG)
        """
        ...
