"""
EA diagram to Mermaid converter for HTML documentation.

This module converts EA-authored diagrams from the database to Mermaid.js syntax,
preserving the diagram author's intent about which objects to show.
"""

from typing import List, Dict, Optional
from eaidl.model import (
    ModelDiagram,
    ModelDiagramObject,
    ModelDiagramLink,
    ModelPackage,
    ModelClass,
    ModelConnection,
)
from eaidl.config import Configuration
from eaidl.link_utils import generate_class_link
from eaidl.mermaid_utils import (
    sanitize_id,
    escape_label,
    get_class_label,
    get_participant_declaration,
    format_note_text,
)
from sqlalchemy.orm import Session
import logging

# Reuse the automap base from load.py
from eaidl.load import base

log = logging.getLogger(__name__)


class EADiagramToMermaidConverter:
    """Converts EA diagram data to Mermaid class diagram syntax."""

    def __init__(
        self,
        diagram: ModelDiagram,
        all_packages: List[ModelPackage],
        config: Configuration,
        session: Session,
    ):
        """
        Initialize converter.

        :param diagram: EA diagram to convert
        :param all_packages: All packages in the model (for class lookup)
        :param config: Configuration object
        :param session: SQLAlchemy session for connector lookup
        """
        self.diagram = diagram
        self.all_packages = all_packages
        self.config = config
        self.session = session
        self.object_lookup: Dict[int, ModelClass] = {}
        self.connector_lookup: Dict[int, ModelConnection] = {}

    def convert(self) -> str:
        """
        Convert EA diagram to Mermaid syntax.

        :return: Mermaid diagram syntax (class or sequence)
        """
        # Route to appropriate converter based on diagram type or presence of sequence connectors
        if self._is_sequence_diagram():
            return self._convert_sequence_diagram()
        else:
            return self._convert_class_diagram()

    def _is_sequence_diagram(self) -> bool:
        """
        Determine if this is a sequence diagram.

        Checks both diagram type and presence of Sequence-type connectors.
        """
        # Explicit sequence diagram type
        if self.diagram.diagram_type == "Sequence":
            return True

        # Check if diagram has Sequence-type connectors
        # Get all object IDs on the diagram
        object_ids = [obj.object_id for obj in self.diagram.objects]
        if not object_ids:
            return False

        # Query for any Sequence connectors involving these objects
        TConnector = base.classes.t_connector
        sequence_connectors = (
            self.session.query(TConnector)
            .filter(TConnector.attr_connector_type == "Sequence")
            .filter((TConnector.attr_start_object_id.in_(object_ids)) | (TConnector.attr_end_object_id.in_(object_ids)))
            .limit(1)
            .first()
        )

        return sequence_connectors is not None

    def _convert_class_diagram(self) -> str:
        """Convert EA class/custom diagram to Mermaid class diagram."""
        lines = ["classDiagram"]

        # Build object and connector lookups
        self._build_object_lookup()
        self._build_connector_lookup()

        # Generate class definitions from diagram objects
        for diag_obj in self.diagram.objects:
            class_def = self._generate_class_from_object(diag_obj)
            if class_def:
                lines.extend(class_def)

        # Add stereotypes as notes
        for diag_obj in self.diagram.objects:
            cls = self.object_lookup.get(diag_obj.object_id)
            if cls and cls.stereotypes:
                safe_id = self._sanitize_name(cls.name)
                for stereotype in cls.stereotypes:
                    safe_stereotype = escape_label(stereotype)
                    lines.append(f'    note for {safe_id} "{safe_stereotype}"')

        # Generate relationships from diagram links
        for diag_link in self.diagram.links:
            if diag_link.hidden:
                continue
            rel_def = self._generate_relationship(diag_link)
            if rel_def:
                lines.append(rel_def)

        # Generate click handlers for navigation
        for diag_obj in self.diagram.objects:
            click_handler = self._generate_click_handler(diag_obj)
            if click_handler:
                lines.append(click_handler)

        return "\n".join(lines)

    def _convert_sequence_diagram(self) -> str:
        """Convert EA sequence diagram to Mermaid sequence diagram."""
        lines = ["sequenceDiagram"]

        # Build object lookup for participants
        self._build_object_lookup()

        # Also load Part objects for sequence diagrams (instances in composite structures)
        self._load_part_objects()

        # Define participants
        for diag_obj in self.diagram.objects:
            cls = self.object_lookup.get(diag_obj.object_id)
            if cls:
                participant_decl = get_participant_declaration(cls.name)
                lines.append(f"    {participant_decl}")

        # Add notes on participants
        for note in self.diagram.notes:
            # Find closest participant by position
            closest_participant = self._find_closest_participant(note)
            if closest_participant:
                position = "right" if note.rect_left > closest_participant[1] else "left"
                safe_note_text = format_note_text(note.name, max_length=80)
                lines.append(f"    Note {position} of {closest_participant[0]}: {safe_note_text}")

        # For sequence diagrams, messages are not in t_diagramlinks
        # Query t_connector directly for Sequence connectors involving diagram participants
        participant_ids = [obj.object_id for obj in self.diagram.objects]
        sequence_connectors = self._load_sequence_connectors(participant_ids)

        # Determine which messages belong inside fragments
        # NOTE: EA doesn't provide direct fragment-message linkage in the database.
        # Proper solution would require:
        # 1. Parse fragment position data (RectTop/RectBottom from t_diagramobjects)
        # 2. Parse message geometry from t_diagramlinks (if available)
        # 3. Perform spatial analysis to determine containment
        # Current heuristic: place last N messages in fragments based on SeqNo
        messages_before_fragment, messages_in_fragment = self._partition_messages_by_fragments(
            sequence_connectors, self.diagram.fragments
        )

        # Add messages before fragments
        for conn in messages_before_fragment:
            msg_line = self._generate_sequence_message(conn)
            if msg_line:
                lines.append(msg_line)

        # Add interaction fragments with their messages
        for i, fragment in enumerate(self.diagram.fragments):
            if fragment.stereotype:
                fragment_type = fragment.stereotype.lower()
            else:
                fragment_type = "alt"  # Default

            safe_fragment_name = escape_label(fragment.name)
            lines.append(f"    {fragment_type} {safe_fragment_name}")

            # Add message(s) inside this fragment
            if i < len(messages_in_fragment):
                msg_line = self._generate_sequence_message(messages_in_fragment[i])
                if msg_line:
                    lines.append(msg_line)

            lines.append("    end")

        return "\n".join(lines)

    def _find_closest_participant(self, note) -> Optional[tuple]:
        """Find the closest participant to a note by X position.

        Returns: tuple of (participant_name, x_position) or None
        """
        closest = None
        min_distance = float("inf")

        for diag_obj in self.diagram.objects:
            cls = self.object_lookup.get(diag_obj.object_id)
            if cls:
                distance = abs(note.rect_left - diag_obj.rect_left)
                if distance < min_distance:
                    min_distance = distance
                    closest = (self._sanitize_name(cls.name), diag_obj.rect_left)

        return closest

    def _partition_messages_by_fragments(
        self, connectors: List[ModelConnection], fragments: List
    ) -> tuple[List[ModelConnection], List[ModelConnection]]:
        """Partition messages into those before and inside fragments.

        Uses simple heuristic: last N messages go inside N fragments.
        See NOTE in _convert_sequence_diagram for limitations.
        """
        if not fragments or not connectors:
            return connectors, []

        # Simple heuristic: put last message(s) inside the fragment
        num_in_fragment = len(fragments)
        return connectors[:-num_in_fragment], connectors[-num_in_fragment:]

    def _sort_connectors_by_seqno(self, connectors: List[ModelConnection]) -> List[ModelConnection]:
        """Sort connectors by SeqNo field from database."""
        # We need to query the database for SeqNo
        TConnector = base.classes.t_connector
        connector_ids = [c.connector_id for c in connectors]

        t_connectors = (
            self.session.query(TConnector)
            .filter(TConnector.attr_connector_id.in_(connector_ids))
            .order_by(TConnector.attr_seqno)
            .all()
        )

        # Create a mapping of connector_id to seqno
        seqno_map = {tc.attr_connector_id: getattr(tc, "attr_seqno", 0) for tc in t_connectors}

        # Sort connectors by seqno
        return sorted(connectors, key=lambda c: seqno_map.get(c.connector_id, 0))

    def _generate_sequence_message(self, conn: ModelConnection) -> Optional[str]:
        """Generate Mermaid sequence message syntax."""
        source_cls = self.object_lookup.get(conn.start_object_id)
        dest_cls = self.object_lookup.get(conn.end_object_id)

        if not source_cls or not dest_cls:
            return None

        source_name = self._sanitize_name(source_cls.name)
        dest_name = self._sanitize_name(dest_cls.name)

        # Parse message data from connector (PDATA fields)
        TConnector = base.classes.t_connector
        t_conn = self.session.query(TConnector).filter(TConnector.attr_connector_id == conn.connector_id).first()

        if not t_conn:
            return None

        # Get message name
        msg_name = getattr(t_conn, "attr_name", "Message")

        # Parse PDATA2 for parameters and return value
        pdata2 = getattr(t_conn, "attr_pdata2", "")
        params_dict = {}
        if pdata2:
            for item in pdata2.split(";"):
                if "=" in item:
                    key, val = item.split("=", 1)
                    params_dict[key] = val

        # Parse StyleEx for parameter values
        styleex = getattr(t_conn, "attr_styleex", "")
        param_values = ""
        if styleex:
            for item in styleex.split(";"):
                if item.startswith("paramvalues="):
                    param_values = item.split("=", 1)[1]
                    break

        # Build message label - sanitize parameters and return values
        safe_msg_name = escape_label(msg_name)
        if param_values:
            safe_params = escape_label(param_values)
            label = f"{safe_msg_name}({safe_params})"
        elif params_dict.get("paramsDlg"):
            safe_params = escape_label(params_dict["paramsDlg"])
            label = f"{safe_msg_name}({safe_params})"
        else:
            label = f"{safe_msg_name}()"

        # Add return value if not void
        retval = params_dict.get("retval", "void")
        if retval and retval != "void":
            safe_retval = escape_label(retval)
            label += f": {safe_retval}"

        # Determine arrow type
        msg_type = getattr(t_conn, "attr_pdata1", "Synchronous")
        if msg_type == "Asynchronous":
            arrow = "->>"
        else:
            arrow = "->>"  # Synchronous

        message_line = f"    {source_name}{arrow}{dest_name}: {label}"

        # Add stereotype as note if present
        stereotype = getattr(t_conn, "attr_stereotype", None)
        if stereotype:
            safe_stereotype = escape_label(stereotype)
            # Return list with message and note
            return message_line + f"\n    Note right of {dest_name}: {safe_stereotype}"

        return message_line

    def _build_object_lookup(self):
        """Map object_id to ModelClass for quick lookup."""
        for package in self.all_packages:
            self._index_package_objects(package)

    def _index_package_objects(self, package: ModelPackage):
        """Recursively index all objects."""
        for cls in package.classes:
            self.object_lookup[cls.object_id] = cls
        for child_pkg in package.packages:
            self._index_package_objects(child_pkg)

    def _load_part_objects(self):
        """Load Part objects from the diagram for sequence diagram participants.

        Part objects are composite structure instances that aren't loaded as ModelClass.
        We create minimal class-like objects for them to enable sequence diagram rendering.
        """
        TObject = base.classes.t_object
        TDiagramObjects = base.classes.t_diagramobjects

        # Query for Part objects on this diagram
        part_objects = (
            self.session.query(TObject)
            .join(TDiagramObjects, TObject.attr_object_id == TDiagramObjects.attr_object_id)
            .filter(TDiagramObjects.attr_diagram_id == self.diagram.diagram_id)
            .filter(TObject.attr_object_type == "Part")
            .all()
        )

        # Create minimal ModelClass entries for each Part
        for part_obj in part_objects:
            if part_obj.attr_object_id not in self.object_lookup:
                # Create a minimal class-like object for the part
                from eaidl.model import ModelClass

                part_class = ModelClass(
                    name=part_obj.attr_name or f"Part{part_obj.attr_object_id}",
                    object_id=part_obj.attr_object_id,
                    namespace=[],  # Parts don't have namespaces
                )
                self.object_lookup[part_obj.attr_object_id] = part_class
                log.debug(f"Loaded Part object: {part_class.name} (ID: {part_obj.attr_object_id})")

    def _load_sequence_connectors(self, participant_ids: List[int]) -> List[ModelConnection]:
        """Load Sequence type connectors for sequence diagram participants.

        Sequence diagram messages are not stored in t_diagramlinks. Instead, we query
        t_connector for all Sequence type connectors involving the diagram participants.

        :param participant_ids: List of object IDs that are participants on the diagram
        :return: List of sequence connectors, sorted by SeqNo
        """
        if not participant_ids:
            return []

        TConnector = base.classes.t_connector

        # Query for Sequence connectors involving any of the participants
        t_connectors = (
            self.session.query(TConnector)
            .filter(TConnector.attr_connector_type == "Sequence")
            .filter(
                (TConnector.attr_start_object_id.in_(participant_ids))
                | (TConnector.attr_end_object_id.in_(participant_ids))
            )
            .order_by(TConnector.attr_seqno)
            .all()
        )

        # Parse connectors
        connectors = []
        for t_conn in t_connectors:
            try:
                conn = self._parse_connector(t_conn)
                connectors.append(conn)
                log.debug(
                    f"Loaded sequence message: {getattr(t_conn, 'attr_name', 'unnamed')} "
                    f"(SeqNo: {getattr(t_conn, 'attr_seqno', 0)})"
                )
            except Exception as e:
                log.warning(f"Failed to parse connector {t_conn.attr_connector_id}: {e}")

        return connectors

    def _build_connector_lookup(self):
        """Load connector details for all diagram links."""
        if not self.diagram.links:
            return

        TConnector = base.classes.t_connector

        # Get all connector IDs from diagram links
        connector_ids = [link.connector_id for link in self.diagram.links]

        # Query all connectors at once
        t_connectors = self.session.query(TConnector).filter(TConnector.attr_connector_id.in_(connector_ids)).all()

        # Parse and store connectors
        for t_conn in t_connectors:
            try:
                conn = self._parse_connector(t_conn)
                self.connector_lookup[conn.connector_id] = conn
            except Exception as e:
                log.warning(f"Failed to parse connector {t_conn.attr_connector_id}: {e}")

    def _parse_connector(self, t_connector) -> ModelConnection:
        """Parse a connector from database."""
        from eaidl.model import ModelConnectionEnd

        # Parse source and destination ends
        source = ModelConnectionEnd(
            cardinality=getattr(t_connector, "attr_sourcecard", None),
            role=getattr(t_connector, "attr_sourcerole", None),
            role_type=getattr(t_connector, "attr_sourceroletype", None),
        )

        destination = ModelConnectionEnd(
            cardinality=getattr(t_connector, "attr_destcard", None),
            role=getattr(t_connector, "attr_destrole", None),
            role_type=getattr(t_connector, "attr_destroletype", None),
        )

        # Wrap single stereotype in list
        stereotype = getattr(t_connector, "attr_stereotype", None)
        stereotypes = [stereotype] if stereotype else []

        conn = ModelConnection(
            connector_id=t_connector.attr_connector_id,
            connector_type=t_connector.attr_connector_type,
            start_object_id=t_connector.attr_start_object_id,
            end_object_id=t_connector.attr_end_object_id,
            stereotypes=stereotypes,
            source=source,
            destination=destination,
        )

        return conn

    def _generate_class_from_object(self, diag_obj: ModelDiagramObject) -> List[str]:
        """
        Generate Mermaid class definition from diagram object.

        Uses label syntax for names with special characters.

        :param diag_obj: Diagram object placement
        :return: List of Mermaid syntax lines
        """
        cls = self.object_lookup.get(diag_obj.object_id)
        if not cls:
            # Object not found - might be a note or external reference
            log.debug(f"Object {diag_obj.object_id} not found in model")
            return []

        lines = []
        # Use label syntax if name contains special characters
        class_decl = get_class_label(cls.name)

        # Show limited attributes (EA diagrams often hide attributes anyway)
        visible_attrs = cls.attributes[:5]  # Show first 5 attributes

        if visible_attrs:
            lines.append(f"class {class_decl} {{")
            for attr in visible_attrs:
                attr_line = self._format_attribute(attr)
                lines.append(f"    {attr_line}")
            if len(cls.attributes) > 5:
                lines.append(f"    ... ({len(cls.attributes) - 5} more)")
            lines.append("}")
        else:
            # Class with no attributes
            lines.append(f"class {class_decl} {{")
            lines.append("}")

        return lines

    def _generate_relationship(self, diag_link: ModelDiagramLink) -> Optional[str]:
        """
        Generate Mermaid relationship from diagram link.

        :param diag_link: Diagram link
        :return: Mermaid relationship syntax or None
        """
        conn = self.connector_lookup.get(diag_link.connector_id)
        if not conn:
            log.debug(f"Connector {diag_link.connector_id} not found")
            return None

        # Get source and destination classes
        source_cls = self.object_lookup.get(conn.start_object_id)
        dest_cls = self.object_lookup.get(conn.end_object_id)

        if not source_cls or not dest_cls:
            log.debug(f"Source or dest class not found for connector {conn.connector_id}")
            return None

        source_name = self._sanitize_name(source_cls.name)
        dest_name = self._sanitize_name(dest_cls.name)

        # Map EA connector types to Mermaid relationship syntax
        rel_syntax = self._get_relationship_syntax(conn)

        # Build relationship with labels - sanitize role names
        label_parts = []
        if conn.source.role:
            label_parts.append(escape_label(conn.source.role))
        if conn.destination.role:
            label_parts.append(escape_label(conn.destination.role))

        if label_parts:
            label = " : " + " / ".join(label_parts)
        else:
            label = ""

        return f"{source_name} {rel_syntax} {dest_name}{label}"

    def _get_relationship_syntax(self, conn: ModelConnection) -> str:
        """
        Map EA connector type to Mermaid relationship syntax.

        :param conn: Model connection
        :return: Mermaid relationship arrow syntax
        """
        # Map common EA connector types to Mermaid syntax
        # See: https://mermaid.js.org/syntax/classDiagram.html#defining-relationship

        if conn.connector_type == "Generalization":
            return "--|>"  # Inheritance
        elif conn.connector_type == "Aggregation":
            if conn.source.is_aggregate:
                return "o--"  # Aggregation
            else:
                return "*--"  # Composition
        elif conn.connector_type == "Association":
            return "-->"  # Association
        elif conn.connector_type == "Dependency":
            return "..>"  # Dependency
        elif conn.connector_type == "Realisation":
            return "..|>"  # Realization
        else:
            # Default to simple association
            return "--"

    def _generate_click_handler(self, diag_obj: ModelDiagramObject) -> Optional[str]:
        """
        Generate click handler for navigation.

        :param diag_obj: Diagram object
        :return: Mermaid click handler or None
        """
        cls = self.object_lookup.get(diag_obj.object_id)
        if not cls:
            return None

        class_name = self._sanitize_name(cls.name)
        namespace = cls.namespace
        link = generate_class_link(namespace, namespace, cls.name)
        return f'click {class_name} href "{link}" _self'

    def _sanitize_name(self, name: str) -> str:
        """
        Generate safe Mermaid identifier from name.

        Uses mermaid_utils.sanitize_id for robust handling of special characters.

        :param name: Original name
        :return: Safe identifier
        """
        return sanitize_id(name)

    def _format_attribute(self, attr) -> str:
        """
        Format attribute for Mermaid.

        Sanitizes attribute names and types.

        :param attr: Model attribute
        :return: Formatted attribute string
        """
        visibility = "+"
        # Sanitize attribute name
        attr_name = sanitize_id(attr.name)
        attr_name = attr_name.lstrip("_")

        # Sanitize type name
        type_str = sanitize_id(attr.type) if attr.type else "unknown"
        if attr.is_collection:
            type_str = f"{type_str}[]"

        optional_marker = "?" if attr.is_optional else ""

        return f"{visibility}{attr_name}{optional_marker} {type_str}"
