"""
EA Diagram Builder - Converts EA diagrams to renderer-agnostic descriptions.

This module builds diagram descriptions from EA-authored diagrams stored in the database.
It follows the new architecture: EA Model → Builder → Description → Renderer → Output.
"""

from typing import List, Optional, Dict
from eaidl.model import ModelDiagram, ModelPackage, ModelClass
from eaidl.config import Configuration
from eaidl.diagram_model import (
    SequenceDiagramDescription,
    SequenceParticipant,
    SequenceMessage,
    SequenceFragment,
    DiagramNote,
    MessageType,
    ClassDiagramDescription,
    DiagramClassNode,
    DiagramAttribute,
    DiagramRelationship,
    RelationType,
    DiagramClickHandler,
)
from eaidl.mermaid_utils import sanitize_id
from eaidl.link_utils import generate_class_link
from sqlalchemy.orm import Session
import logging

# Reuse the automap base from load.py
from eaidl.load import base

log = logging.getLogger(__name__)


class EADiagramBuilder:
    """Builds renderer-agnostic diagram descriptions from EA diagrams."""

    def __init__(
        self,
        diagram: ModelDiagram,
        all_packages: List[ModelPackage],
        config: Configuration,
        session: Session,
    ):
        """
        Initialize EA diagram builder.

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

    def build(self):
        """
        Build diagram description from EA diagram.

        Routes to appropriate builder based on diagram type.

        :return: SequenceDiagramDescription or ClassDiagramDescription
        """
        if self._is_sequence_diagram():
            return self.build_sequence_diagram()
        else:
            return self.build_class_diagram()

    def _is_sequence_diagram(self) -> bool:
        """
        Determine if this is a sequence diagram.

        Checks both diagram type and presence of Sequence-type connectors.
        Excludes composite structure diagrams (diagrams with Part objects).
        """
        # Explicit sequence diagram type
        if self.diagram.diagram_type == "Sequence":
            return True

        # Check if diagram has Sequence-type connectors
        object_ids = [obj.object_id for obj in self.diagram.objects]
        if not object_ids:
            return False

        # Check if this is a composite structure diagram (contains Part objects)
        # Composite structure diagrams should be rendered as class diagrams, not sequence diagrams
        TObject = base.classes.t_object
        part_objects = (
            self.session.query(TObject)
            .filter(TObject.attr_object_id.in_(object_ids))
            .filter(TObject.attr_object_type == "Part")
            .limit(1)
            .first()
        )

        # If diagram contains Part objects, it's a composite structure, not a sequence diagram
        if part_objects is not None:
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

    def build_sequence_diagram(self) -> SequenceDiagramDescription:
        """
        Build sequence diagram description from EA diagram.

        :return: SequenceDiagramDescription
        """
        # Build object lookup for participants
        self._build_object_lookup()
        self._load_part_objects()

        # Build participants sorted by horizontal position (left to right)
        participants = []
        sorted_objects = sorted(self.diagram.objects, key=lambda obj: obj.rect_left)
        for diag_obj in sorted_objects:
            cls = self.object_lookup.get(diag_obj.object_id)
            if cls:
                participant_id = sanitize_id(cls.name)
                participants.append(SequenceParticipant(id=participant_id, name=cls.name))

        # Load sequence connectors (messages)
        participant_ids = [obj.object_id for obj in self.diagram.objects]
        sequence_connectors = self._load_sequence_connectors(participant_ids)

        # Assign messages to fragments and build ordered notes
        messages, fragments, notes = self._build_sequence_elements(sequence_connectors, participants)

        return SequenceDiagramDescription(
            participants=participants, messages=messages, fragments=fragments, notes=notes
        )

    def build_class_diagram(self) -> ClassDiagramDescription:
        """
        Build class diagram description from EA diagram.

        :return: ClassDiagramDescription
        """
        self._build_object_lookup()
        self._load_part_objects()  # Also load Part objects for composite structures
        self._build_connector_lookup()

        # Build nodes
        nodes = []
        for diag_obj in self.diagram.objects:
            node = self._build_class_node(diag_obj)
            if node:
                nodes.append(node)

        # Build relationships
        relationships = []
        for diag_link in self.diagram.links:
            if diag_link.hidden:
                continue
            rel = self._build_relationship(diag_link)
            if rel:
                relationships.append(rel)

        # For composite structure diagrams, add composition relationships from container to parts
        relationships.extend(self._build_composite_structure_relationships())

        # Build click handlers
        click_handlers = []
        for diag_obj in self.diagram.objects:
            handler = self._build_click_handler(diag_obj)
            if handler:
                click_handlers.append(handler)

        # Build notes (stereotypes as notes)
        notes = []
        for diag_obj in self.diagram.objects:
            cls = self.object_lookup.get(diag_obj.object_id)
            if cls and cls.stereotypes:
                node_id = sanitize_id(cls.name)
                for stereotype in cls.stereotypes:
                    notes.append(DiagramNote(text=stereotype, attached_to=node_id))

        return ClassDiagramDescription(
            nodes=nodes, relationships=relationships, click_handlers=click_handlers, notes=notes
        )

    def _build_class_node(self, diag_obj) -> Optional[DiagramClassNode]:
        """Build DiagramClassNode from EA diagram object."""
        cls = self.object_lookup.get(diag_obj.object_id)
        if not cls:
            return None

        # Build attributes (limit to first 5 for EA diagrams)
        attributes = []
        for attr in cls.attributes[:5]:
            attributes.append(
                DiagramAttribute(
                    name=attr.name,
                    type=attr.type if attr.type else "unknown",
                    visibility="+",
                    is_collection=attr.is_collection,
                    is_optional=attr.is_optional,
                    is_inherited=False,
                )
            )

        return DiagramClassNode(
            id=sanitize_id(cls.name),
            name=cls.name,
            attributes=attributes,
            stereotypes=cls.stereotypes,
            is_abstract=cls.is_abstract,
            namespace=cls.namespace,
        )

    def _build_relationship(self, diag_link) -> Optional[DiagramRelationship]:
        """Build DiagramRelationship from EA diagram link."""
        conn = self.connector_lookup.get(diag_link.connector_id)
        if not conn:
            return None

        source_cls = self.object_lookup.get(conn.start_object_id)
        dest_cls = self.object_lookup.get(conn.end_object_id)

        if not source_cls or not dest_cls:
            return None

        source_id = sanitize_id(source_cls.name)
        target_id = sanitize_id(dest_cls.name)

        # Map EA connector type to RelationType
        rel_type = self._map_connector_type(conn.connector_type, conn)

        return DiagramRelationship(
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            source_label=conn.source.role if conn.source.role else None,
            target_label=conn.destination.role if conn.destination.role else None,
            stereotypes=conn.stereotypes,
        )

    def _map_connector_type(self, connector_type: str, conn) -> RelationType:
        """Map EA connector type to RelationType."""
        if connector_type == "Generalization":
            return RelationType.INHERITANCE
        elif connector_type == "Aggregation":
            if hasattr(conn.source, "is_aggregate") and conn.source.is_aggregate:
                return RelationType.AGGREGATION
            else:
                return RelationType.COMPOSITION
        elif connector_type == "Association":
            return RelationType.ASSOCIATION
        elif connector_type == "Dependency":
            return RelationType.DEPENDENCY
        else:
            return RelationType.ASSOCIATION

    def _build_click_handler(self, diag_obj) -> Optional[DiagramClickHandler]:
        """Build DiagramClickHandler from EA diagram object."""
        cls = self.object_lookup.get(diag_obj.object_id)
        if not cls:
            return None

        node_id = sanitize_id(cls.name)
        namespace = cls.namespace
        link = generate_class_link(namespace, namespace, cls.name)

        return DiagramClickHandler(node_id=node_id, link=link)

    def _build_sequence_message(self, conn) -> Optional[SequenceMessage]:
        """Build SequenceMessage from EA connector."""
        source_cls = self.object_lookup.get(conn.start_object_id)
        dest_cls = self.object_lookup.get(conn.end_object_id)

        if not source_cls or not dest_cls:
            return None

        from_id = sanitize_id(source_cls.name)
        to_id = sanitize_id(dest_cls.name)

        # Get message data from connector
        TConnector = base.classes.t_connector
        t_conn = self.session.query(TConnector).filter(TConnector.attr_connector_id == conn.connector_id).first()

        if not t_conn:
            return None

        # Get message name
        msg_name = getattr(t_conn, "attr_name", "Message")

        # Parse PDATA2 for parameters
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

        # Build label
        if param_values:
            label = f"{msg_name}({param_values})"
        elif params_dict.get("paramsDlg"):
            label = f"{msg_name}({params_dict['paramsDlg']})"
        else:
            label = f"{msg_name}()"

        # Add return value
        retval = params_dict.get("retval", "void")
        if retval and retval != "void":
            label += f": {retval}"

        # Determine message type
        msg_type_str = getattr(t_conn, "attr_pdata1", "Synchronous")
        message_type = MessageType.ASYNC if msg_type_str == "Asynchronous" else MessageType.SYNC

        # Use first stereotype from conn if available (SequenceMessage currently supports single stereotype)
        stereotype = conn.stereotypes[0] if conn.stereotypes else None

        return SequenceMessage(
            from_id=from_id,
            to_id=to_id,
            label=label,
            message_type=message_type,
            stereotype=stereotype,
        )

    def _find_closest_participant(self, note) -> Optional[tuple]:
        """Find the closest participant to a note by X position."""
        closest = None
        min_distance = float("inf")

        for diag_obj in self.diagram.objects:
            cls = self.object_lookup.get(diag_obj.object_id)
            if cls:
                distance = abs(note.rect_left - diag_obj.rect_left)
                if distance < min_distance:
                    min_distance = distance
                    closest = (sanitize_id(cls.name), diag_obj.rect_left)

        return closest

    def _build_sequence_elements(
        self, sequence_connectors: List, participants: List[SequenceParticipant]
    ) -> tuple[List[SequenceMessage], List[SequenceFragment], List[DiagramNote]]:
        """
        Build messages, fragments, and notes with proper spatial ordering.

        Uses spatial positioning to determine which messages belong to fragments
        and where notes should appear relative to messages.

        :param sequence_connectors: List of sequence connectors from EA
        :param participants: List of participants for note attachment
        :return: Tuple of (messages, fragments, notes)
        """
        messages = []
        fragments = []
        notes = []

        if not sequence_connectors:
            return messages, fragments, notes

        # Estimate Y-positions for messages based on their sequence number
        # In EA, messages are drawn top-to-bottom in SeqNo order
        message_positions = self._estimate_message_positions(sequence_connectors)

        # Assign messages to fragments based on spatial overlap
        fragment_assignments = self._assign_messages_to_fragments(sequence_connectors, message_positions)

        # Build fragments with their assigned messages
        for fragment in self.diagram.fragments:
            assigned_conns = fragment_assignments.get(fragment.object_id, [])
            if assigned_conns:
                fragment_messages = []
                for conn in assigned_conns:
                    msg = self._build_sequence_message(conn)
                    if msg:
                        fragment_messages.append(msg)

                if fragment_messages:
                    fragment_type = fragment.stereotype.lower() if fragment.stereotype else "alt"
                    fragments.append(
                        SequenceFragment(
                            fragment_type=fragment_type, condition=fragment.name, messages=fragment_messages
                        )
                    )

        # Build top-level messages (not in any fragment)
        for conn in sequence_connectors:
            # Check if this connector is assigned to any fragment
            in_fragment = any(conn in fragment_assignments.get(frag.object_id, []) for frag in self.diagram.fragments)
            if not in_fragment:
                msg = self._build_sequence_message(conn)
                if msg:
                    messages.append(msg)

        # Build notes with spatial ordering (for PlantUML only, positioned by Y-coordinate)
        # Note: Mermaid doesn't support positioned notes, so they'll just be added at the top
        for note in self.diagram.notes:
            closest_participant = self._find_closest_participant(note)
            if closest_participant:
                notes.append(
                    DiagramNote(text=note.name[:80], attached_to=closest_participant[0], rect_top=note.rect_top)
                )

        return messages, fragments, notes

    def _estimate_message_positions(self, sequence_connectors: List) -> Dict[int, int]:
        """
        Estimate Y-position for each message based on SeqNo.

        In EA sequence diagrams, messages are drawn from top to bottom based on their
        execution order (SeqNo). This estimates their Y-coordinate for spatial analysis.

        :param sequence_connectors: List of sequence connectors
        :return: Dict mapping connector_id to estimated Y-position
        """
        if not sequence_connectors:
            return {}

        # Get the Y-range of the diagram from participants
        participant_tops = [obj.rect_top for obj in self.diagram.objects if obj.rect_top != 0]
        if not participant_tops:
            # No positioning info, return empty
            return {}

        # Start messages below the participants (more negative Y)
        start_y = max(participant_tops)  # EA: larger value = higher on diagram

        # Calculate dynamic spacing based on fragment positions if available
        message_spacing = 80  # Default spacing
        if self.diagram.fragments:
            # Use fragment positions to estimate better spacing
            # Assume last message should be in the middle of the deepest fragment
            fragment_bottoms = [f.rect_bottom for f in self.diagram.fragments]
            fragment_tops = [f.rect_top for f in self.diagram.fragments]
            deepest_bottom = min(fragment_bottoms)  # Most negative = lowest
            deepest_top = min(fragment_tops)  # Entry point of deepest fragment

            # Estimate that messages reach the deepest fragment
            # Calculate spacing to spread messages from start_y to deepest fragment
            num_messages = len(sequence_connectors)
            if num_messages > 0:
                # Target the middle of the deepest fragment for the last message
                target_y = (deepest_top + deepest_bottom) // 2
                total_distance = start_y - target_y  # Distance from start to fragment middle
                message_spacing = total_distance // num_messages

        positions = {}
        for conn in sequence_connectors:
            # Get SeqNo from the connector
            TConnector = base.classes.t_connector
            t_conn = self.session.query(TConnector).filter(TConnector.attr_connector_id == conn.connector_id).first()
            if t_conn:
                seqno = getattr(t_conn, "attr_seqno", 0)
                # Move down (more negative) for each message
                estimated_y = start_y - (seqno * message_spacing)
                positions[conn.connector_id] = estimated_y

        return positions

    def _assign_messages_to_fragments(
        self, sequence_connectors: List, message_positions: Dict[int, int]
    ) -> Dict[int, List]:
        """
        Assign messages to fragments based on spatial overlap.

        A message belongs to a fragment if its estimated Y-position falls within
        the fragment's bounding box (rect_top to rect_bottom).

        :param sequence_connectors: List of sequence connectors
        :param message_positions: Dict mapping connector_id to Y-position
        :return: Dict mapping fragment object_id to list of connectors
        """
        assignments = {}

        for fragment in self.diagram.fragments:
            assigned_conns = []
            for conn in sequence_connectors:
                msg_y = message_positions.get(conn.connector_id)
                if msg_y is not None:
                    # Check if message falls within fragment's vertical range
                    # EA Y-axis is inverted: rect_top > rect_bottom (top is larger number)
                    if fragment.rect_bottom <= msg_y <= fragment.rect_top:
                        assigned_conns.append(conn)

            if assigned_conns:
                assignments[fragment.object_id] = assigned_conns

        return assignments

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
        """Load Part objects from the diagram for sequence diagram participants."""
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
                from eaidl.model import ModelClass

                part_class = ModelClass(
                    name=part_obj.attr_name or f"Part{part_obj.attr_object_id}",
                    object_id=part_obj.attr_object_id,
                    namespace=[],
                )
                self.object_lookup[part_obj.attr_object_id] = part_class

    def _load_sequence_connectors(self, participant_ids: List[int]) -> List:
        """Load Sequence type connectors for sequence diagram participants."""
        if not participant_ids:
            return []

        TConnector = base.classes.t_connector

        # Query for Sequence connectors
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
            except Exception as e:
                log.warning(f"Failed to parse connector {t_conn.attr_connector_id}: {e}")

        return connectors

    def _build_connector_lookup(self):
        """Load connector details for all diagram links."""
        self.connector_lookup = {}
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

    def _parse_connector(self, t_connector):
        """Parse a connector from database."""
        from eaidl.model import ModelConnectionEnd, ModelConnection

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

    def _build_composite_structure_relationships(self) -> List[DiagramRelationship]:
        """
        Build composition relationships for composite structure diagrams.

        In composite structures, Part objects should be shown as composed within
        their parent Class objects.

        :return: List of composition relationships
        """
        relationships = []

        # Get all object IDs in the diagram
        object_ids = [obj.object_id for obj in self.diagram.objects]
        if not object_ids:
            return relationships

        # Query for Part objects and their parent class
        TObject = base.classes.t_object

        # Get all objects in the diagram
        objects_in_diagram = self.session.query(TObject).filter(TObject.attr_object_id.in_(object_ids)).all()

        # Find Part objects and create composition relationships to their parent
        part_objects = [obj for obj in objects_in_diagram if obj.attr_object_type == "Part"]
        class_objects = [obj for obj in objects_in_diagram if obj.attr_object_type == "Class"]

        # If we have parts but only one class, assume all parts belong to that class
        if part_objects and len(class_objects) == 1:
            parent_class = self.object_lookup.get(class_objects[0].attr_object_id)
            if parent_class:
                parent_id = sanitize_id(parent_class.name)

                for part_obj in part_objects:
                    part_class = self.object_lookup.get(part_obj.attr_object_id)
                    if part_class:
                        part_id = sanitize_id(part_class.name)
                        relationships.append(
                            DiagramRelationship(
                                source_id=parent_id,
                                target_id=part_id,
                                type=RelationType.COMPOSITION,
                                source_label=None,
                                target_label=None,
                            )
                        )

        return relationships
