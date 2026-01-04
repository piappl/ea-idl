"""
Mermaid renderer - Generates Mermaid.js diagram syntax from diagram descriptions.

This renderer converts renderer-agnostic diagram descriptions into Mermaid text format.
The generated text can be embedded in HTML and rendered client-side by Mermaid.js.
"""

from typing import List
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
from eaidl.mermaid_utils import get_class_label, escape_label
import logging

log = logging.getLogger(__name__)


class MermaidRenderer:
    """Renders diagram descriptions as Mermaid.js text syntax."""

    def render_class_diagram(self, desc: ClassDiagramDescription) -> DiagramOutput:
        """
        Render a class diagram to Mermaid.js syntax.

        :param desc: ClassDiagramDescription
        :return: DiagramOutput with Mermaid text
        """
        try:
            lines = ["classDiagram"]

            # Generate class definitions
            for node in desc.nodes:
                class_def = self._generate_class_definition(node)
                lines.extend(class_def)

            # Generate relationships
            for rel in desc.relationships:
                rel_line = self._generate_relationship(rel)
                lines.append(rel_line)

            # Generate click handlers
            for handler in desc.click_handlers:
                click_line = self._generate_click_handler(handler)
                lines.append(click_line)

            # Note: Mermaid v11 doesn't support stereotypes in class diagrams,
            # so we skip rendering stereotype notes. They're preserved in class detail pages.

            content = "\n".join(lines)
            return DiagramOutput(output_type=OutputType.TEXT, content=content)

        except Exception as e:
            log.error(f"Failed to render Mermaid class diagram: {e}")
            return DiagramOutput(
                output_type=OutputType.TEXT,
                content="",
                error=f"Mermaid rendering failed: {e}",
            )

    def render_sequence_diagram(self, desc: SequenceDiagramDescription) -> DiagramOutput:
        """
        Render a sequence diagram to Mermaid.js syntax.

        :param desc: SequenceDiagramDescription
        :return: DiagramOutput with Mermaid text
        """
        try:
            lines = ["sequenceDiagram"]

            # Define participants
            for participant in desc.participants:
                lines.append(f"    participant {participant.id}")

            # Add notes
            for note in desc.notes:
                if note.attached_to:
                    note_text = escape_label(note.text[:80])  # Limit length
                    lines.append(f"    Note right of {note.attached_to}: {note_text}")
                elif desc.participants:
                    note_text = escape_label(note.text[:80])
                    lines.append(f"    Note over {desc.participants[0].id}: {note_text}")

            # Add messages (not in fragments)
            for message in desc.messages:
                msg_line = self._generate_sequence_message(message)
                lines.append(msg_line)

            # Add fragments
            for fragment in desc.fragments:
                condition = escape_label(fragment.condition)
                lines.append(f"    {fragment.fragment_type} {condition}")
                for message in fragment.messages:
                    msg_line = self._generate_sequence_message(message)
                    lines.append(msg_line)
                lines.append("    end")

            content = "\n".join(lines)
            return DiagramOutput(output_type=OutputType.TEXT, content=content)

        except Exception as e:
            log.error(f"Failed to render Mermaid sequence diagram: {e}")
            return DiagramOutput(
                output_type=OutputType.TEXT,
                content="sequenceDiagram\n%% Error rendering diagram",
                error=f"Mermaid sequence rendering failed: {e}",
            )

    def _generate_sequence_message(self, message: SequenceMessage) -> str:
        """
        Generate Mermaid sequence message syntax.

        :param message: SequenceMessage
        :return: Mermaid message syntax
        """
        # Choose arrow type based on message type
        if message.message_type == MessageType.ASYNC:
            arrow = "->>"
        elif message.message_type == MessageType.RETURN:
            arrow = "-->"
        else:  # SYNC
            arrow = "->>"

        label = escape_label(message.label)
        return f"    {message.from_id}{arrow}{message.to_id}: {label}"

    def _generate_class_definition(self, node: DiagramClassNode) -> List[str]:
        """
        Generate Mermaid class definition for a node.

        :param node: DiagramClassNode
        :return: List of Mermaid syntax lines
        """
        lines = []

        # Use label syntax if name contains special characters
        class_decl = get_class_label(node.name)

        # CRITICAL: Mermaid v11 does NOT support stereotypes in class diagrams
        # Neither "class Foo <<stereotype>>" nor "class Foo <<stereotype>> {}" work
        # Solution: Never add stereotypes - just show class name and attributes
        # The stereotype information is preserved in the class detail pages

        if node.attributes:
            # Class with attributes - show them
            lines.append(f"class {class_decl} {{")

            for attr in node.attributes:
                attr_line = self._format_attribute(attr)
                lines.append(f"    {attr_line}")

            lines.append("}")
        else:
            # Class with no attributes - add empty placeholder to help with layout
            # Empty class declarations can cause "Could not find suitable point" errors
            # when they are used in relationships
            lines.append(f"class {class_decl} {{")
            lines.append("}")

        return lines

    def _format_attribute(self, attr: DiagramAttribute) -> str:
        """
        Format attribute for Mermaid class diagram.

        :param attr: DiagramAttribute
        :return: Formatted attribute string
        """
        # Mark inherited attributes with asterisk prefix
        prefix = ""
        if attr.is_inherited:
            # Prepend asterisk after visibility marker
            prefix = "*"

        # Build type string
        type_str = attr.type

        # Add collection indicator
        if attr.is_collection:
            type_str = f"{type_str}[]"

        # Add optional indicator
        optional_marker = "?" if attr.is_optional else ""

        # Format: +name type or +*name type (inherited)
        return f"{attr.visibility}{prefix}{attr.name}{optional_marker} {type_str}"

    def _generate_relationship(self, rel: DiagramRelationship) -> str:
        """
        Generate Mermaid relationship line.

        :param rel: DiagramRelationship
        :return: Mermaid syntax
        """
        if rel.type == RelationType.INHERITANCE:
            # Generalization: solid line with hollow triangle
            return f"{rel.source_id} --|> {rel.target_id}"

        elif rel.type == RelationType.COMPOSITION:
            # Composition: solid diamond
            return f"{rel.source_id} *-- {rel.target_id}"

        elif rel.type == RelationType.AGGREGATION:
            # Aggregation: hollow diamond
            return f"{rel.source_id} o-- {rel.target_id}"

        elif rel.type == RelationType.DEPENDENCY:
            # Dependency: dotted arrow
            return f"{rel.source_id} ..> {rel.target_id}"

        elif rel.type == RelationType.ASSOCIATION:
            # Association: simple arrow
            # Handle cardinality if present
            if rel.source_cardinality and rel.target_cardinality:
                return f'{rel.source_id} "{rel.source_cardinality}" --> "{rel.target_cardinality}" {rel.target_id}'
            else:
                return f"{rel.source_id} --> {rel.target_id}"

        else:
            # Default: simple association
            return f"{rel.source_id} --> {rel.target_id}"

    def _generate_click_handler(self, handler: DiagramClickHandler) -> str:
        """
        Generate Mermaid click handler for interactive link.

        :param handler: DiagramClickHandler
        :return: Mermaid click syntax
        """
        # Mermaid click syntax - _self makes it open in same tab instead of new tab
        return f'click {handler.node_id} href "{handler.link}" _self'
