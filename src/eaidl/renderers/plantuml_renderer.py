"""
PlantUML renderer - Generates PlantUML diagrams via HTTP server.

This renderer converts renderer-agnostic diagram descriptions into PlantUML syntax,
sends it to a PlantUML server via HTTP, and receives SVG output. This enables
rich diagram features like stereotypes that Mermaid doesn't support.
"""

from typing import List
import requests
import logging
from eaidl.diagram_model import (
    ClassDiagramDescription,
    SequenceDiagramDescription,
    DiagramOutput,
    OutputType,
    DiagramClassNode,
    DiagramAttribute,
    DiagramRelationship,
    RelationType,
    DiagramClickHandler,
    MessageType,
    SequenceMessage,
)

log = logging.getLogger(__name__)


class PlantUMLServerError(Exception):
    """Raised when PlantUML server request fails."""

    pass


class PlantUMLClient:
    """HTTP client for PlantUML server communication."""

    def __init__(self, server_url: str, timeout: int = 30):
        """
        Initialize PlantUML client.

        :param server_url: Base URL of PlantUML server (e.g., http://localhost:10005/)
        :param timeout: Request timeout in seconds
        """
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def generate_svg(self, plantuml_text: str) -> str:
        """
        Send PlantUML text to server and get SVG back.

        :param plantuml_text: PlantUML diagram syntax
        :return: SVG XML string
        :raises PlantUMLServerError: If server request fails
        """
        try:
            # POST to /svg endpoint with PlantUML text
            response = requests.post(
                f"{self.server_url}/svg",
                data=plantuml_text.encode("utf-8"),
                timeout=self.timeout,
                headers={"Content-Type": "text/plain; charset=utf-8"},
            )

            if response.status_code == 400:
                # For bad request plantuml returns information on error as svg, we can return it
                log.error(f"Got bad request {response.status_code}")
                log.error(plantuml_text)
                log.error(response.text)

                return response.text
            if response.status_code == 200:
                return response.text
            raise PlantUMLServerError(f"PlantUML server returned HTTP {response.status_code}: {response.text}")

        except requests.exceptions.Timeout:
            raise PlantUMLServerError(f"PlantUML server request timed out after {self.timeout} seconds")
        except requests.exceptions.ConnectionError as e:
            raise PlantUMLServerError(f"Failed to connect to PlantUML server at {self.server_url}: {e}")
        except requests.exceptions.RequestException as e:
            raise PlantUMLServerError(f"PlantUML server request failed: {e}")

    def check_health(self) -> bool:
        """
        Check if PlantUML server is reachable.

        :return: True if server is healthy
        """
        try:
            response = requests.get(f"{self.server_url}/", timeout=5)
            return response.status_code == 200
        except Exception:
            return False


class PlantUMLRenderer:
    """Renders diagram descriptions as PlantUML diagrams (SVG output)."""

    def __init__(self, server_url: str, timeout: int = 30):
        """
        Initialize PlantUML renderer.

        :param server_url: PlantUML server URL
        :param timeout: Request timeout in seconds
        """
        self.client = PlantUMLClient(server_url, timeout)

    def render_class_diagram(self, desc: ClassDiagramDescription) -> DiagramOutput:
        """
        Render a class diagram to PlantUML SVG.

        :param desc: ClassDiagramDescription
        :return: DiagramOutput with SVG content
        :raises PlantUMLServerError: If server request fails
        """
        plantuml_text = self._generate_class_diagram_syntax(desc)
        return self._render(plantuml_text)

    def render_sequence_diagram(self, desc: SequenceDiagramDescription) -> DiagramOutput:
        """
        Render a sequence diagram to PlantUML SVG.

        :param desc: SequenceDiagramDescription
        :return: DiagramOutput with SVG content
        """
        plantuml_text = self._generate_sequence_diagram_syntax(desc)
        return self._render(plantuml_text)

    def _render(self, desc: str) -> DiagramOutput:
        try:
            svg_content = self.client.generate_svg(desc)
            return DiagramOutput(output_type=OutputType.SVG, content=svg_content)
        except PlantUMLServerError as e:
            log.error(f"PlantUML server error: {e}")
            log.error(f"PlantUML sequence syntax ({len(desc)} chars)")
            raise
        except Exception as e:
            log.error(f"Failed to render PlantUML sequence diagram: {e}")
            raise

    def _generate_sequence_diagram_syntax(self, desc: SequenceDiagramDescription) -> str:
        """
        Generate PlantUML sequence diagram syntax.

        :param desc: SequenceDiagramDescription
        :return: PlantUML syntax string
        """
        lines = ["@startuml"]

        # Define participants
        for participant in desc.participants:
            lines.append(f"participant {participant.id}")

        # Output notes in Y-order (higher Y first, which means less negative)
        # EA coordinate system: larger values = higher on diagram
        sorted_notes = sorted(desc.notes, key=lambda n: n.rect_top, reverse=True)

        # For proper positioning, we output notes at logical points:
        # - Notes with Y > max(participant Y) before first message
        # - Other notes after corresponding messages
        # Since we don't have message Y-positions here, we use a simple heuristic:
        # Output notes in their Y-order, interspersed with messages

        note_idx = 0

        # Output notes that should appear at the top (before all messages)
        # These are notes with higher Y values (less negative) than typical message positions
        # Simple heuristic: notes with Y > -150 appear before messages
        early_threshold = -150  # Notes above this Y appear before messages

        while note_idx < len(sorted_notes):
            note = sorted_notes[note_idx]
            if note.rect_top < early_threshold:
                break
            if note.attached_to:
                note_text = note.text.replace('"', '\\"')
                lines.append(f"note right of {note.attached_to}: {repr(note_text)}")
            elif desc.participants:
                note_text = note.text.replace('"', '\\"')
                lines.append(f"note over {desc.participants[0].id}: {repr(note_text)}")
            note_idx += 1

        # Add messages (not in fragments)
        for message in desc.messages:
            msg_line = self._generate_sequence_message_syntax(message)
            lines.append(msg_line)

        # Add fragments
        for fragment in desc.fragments:
            condition = fragment.condition.replace('"', '\\"')
            lines.append(f"{fragment.fragment_type} {condition}")
            for message in fragment.messages:
                msg_line = self._generate_sequence_message_syntax(message)
                lines.append(msg_line)
            lines.append("end")

        # Output remaining notes (those that should appear after messages/fragments)
        while note_idx < len(sorted_notes):
            note = sorted_notes[note_idx]
            if note.attached_to:
                note_text = note.text.replace('"', '\\"')
                lines.append(f"note right of {note.attached_to}: {repr(note_text)}")
            elif desc.participants:
                note_text = note.text.replace('"', '\\"')
                lines.append(f"note over {desc.participants[0].id}: {repr(note_text)}")
            note_idx += 1

        lines.append("@enduml")
        return "\n".join(lines)

    def _generate_sequence_message_syntax(self, message: SequenceMessage) -> str:
        """
        Generate PlantUML sequence message syntax.

        :param message: SequenceMessage
        :return: PlantUML message syntax
        """
        # Choose arrow type based on message type
        if message.message_type == MessageType.ASYNC:
            arrow = "->>"
        elif message.message_type == MessageType.RETURN:
            arrow = "-->"
        else:  # SYNC
            arrow = "->"

        label = message.label.replace('"', '\\"')
        return f"{message.from_id} {arrow} {message.to_id}: {label}"

    def _generate_class_diagram_syntax(self, desc: ClassDiagramDescription) -> str:
        """
        Generate PlantUML class diagram syntax.

        :param desc: ClassDiagramDescription
        :return: PlantUML text
        """
        lines = ["@startuml"]

        # PlantUML styling
        lines.append("skinparam classAttributeIconSize 0")
        lines.append("")

        # Generate class definitions
        for node in desc.nodes:
            class_def = self._generate_class_definition(node)
            lines.extend(class_def)
            lines.append("")

        # Generate relationships
        for rel in desc.relationships:
            rel_line = self._generate_relationship(rel)
            lines.append(rel_line)

        # Generate click handlers (PlantUML hyperlinks)
        for handler in desc.click_handlers:
            click_line = self._generate_click_handler(handler)
            lines.append(click_line)

        lines.append("@enduml")
        return "\n".join(lines)

    def _generate_class_definition(self, node: DiagramClassNode) -> List[str]:
        """
        Generate PlantUML class definition.

        :param node: DiagramClassNode
        :return: List of PlantUML lines
        """
        lines = []

        # Build class header with stereotypes
        # PlantUML DOES support stereotypes! This is a key advantage over Mermaid
        stereotypes_str = ""
        if node.stereotypes:
            stereotypes_str = " " + " ".join(f"<<{s}>>" for s in node.stereotypes)

        # Mark abstract classes
        abstract_keyword = "abstract " if node.is_abstract else ""

        # Class declaration
        lines.append(f"{abstract_keyword}class {node.id}{stereotypes_str} {{")

        # Add attributes
        for attr in node.attributes:
            attr_line = self._format_attribute(attr)
            lines.append(f"  {attr_line}")

        lines.append("}")

        return lines

    def _format_attribute(self, attr: DiagramAttribute) -> str:
        """
        Format attribute for PlantUML.

        :param attr: DiagramAttribute
        :return: Formatted attribute string
        """
        # PlantUML visibility: + public, - private, # protected
        visibility = attr.visibility

        # Mark inherited attributes
        prefix = "{field} " if attr.is_inherited else ""

        # Build type string
        type_str = attr.type
        if attr.is_collection:
            type_str = f"{type_str}[]"

        # Optional indicator
        optional_marker = "?" if attr.is_optional else ""

        # PlantUML format: visibility name: type
        return f"{prefix}{visibility}{attr.name}{optional_marker}: {type_str}"

    def _generate_relationship(self, rel: DiagramRelationship) -> str:
        """
        Generate PlantUML relationship line.

        :param rel: DiagramRelationship
        :return: PlantUML syntax
        """
        # Determine arrow type based on relationship type
        if rel.type == RelationType.INHERITANCE:
            # Inheritance: hollow triangle arrow
            arrow = "--|>"
        elif rel.type == RelationType.COMPOSITION:
            # Composition: filled diamond
            arrow = "*--"
        elif rel.type == RelationType.AGGREGATION:
            # Aggregation: hollow diamond
            arrow = "o--"
        elif rel.type == RelationType.DEPENDENCY:
            # Dependency: dotted arrow
            arrow = "..>"
        elif rel.type == RelationType.ASSOCIATION:
            arrow = "-->"
        else:
            # Default: simple association
            arrow = "-->"

        # Build relationship line
        rel_line = f"{rel.source_id} {arrow} {rel.target_id}"

        # Add stereotypes if present
        if rel.stereotypes:
            stereotypes_str = " ".join(f"<<{s}>>" for s in rel.stereotypes)
            rel_line += f" : {stereotypes_str}"

        return rel_line

    def _generate_click_handler(self, handler: DiagramClickHandler) -> str:
        """
        Generate PlantUML hyperlink (click handler).

        :param handler: DiagramClickHandler
        :return: PlantUML syntax
        """
        # PlantUML hyperlink syntax
        return f"url of {handler.node_id} is [[{handler.link}]]"
