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

        :return: Mermaid class diagram syntax
        """
        lines = ["classDiagram"]

        # Build object and connector lookups
        self._build_object_lookup()
        self._build_connector_lookup()

        # Generate class definitions from diagram objects
        for diag_obj in self.diagram.objects:
            class_def = self._generate_class_from_object(diag_obj)
            if class_def:
                lines.extend(class_def)

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

        conn = ModelConnection(
            connector_id=t_connector.attr_connector_id,
            connector_type=t_connector.attr_connector_type,
            start_object_id=t_connector.attr_start_object_id,
            end_object_id=t_connector.attr_end_object_id,
            stereotype=getattr(t_connector, "attr_stereotype", None),
            source=source,
            destination=destination,
        )

        return conn

    def _generate_class_from_object(self, diag_obj: ModelDiagramObject) -> List[str]:
        """
        Generate Mermaid class definition from diagram object.

        :param diag_obj: Diagram object placement
        :return: List of Mermaid syntax lines
        """
        cls = self.object_lookup.get(diag_obj.object_id)
        if not cls:
            # Object not found - might be a note or external reference
            log.debug(f"Object {diag_obj.object_id} not found in model")
            return []

        lines = []
        class_name = self._sanitize_name(cls.name)

        # Show limited attributes (EA diagrams often hide attributes anyway)
        visible_attrs = cls.attributes[:5]  # Show first 5 attributes

        if visible_attrs:
            lines.append(f"class {class_name} {{")
            for attr in visible_attrs:
                attr_line = self._format_attribute(attr)
                lines.append(f"    {attr_line}")
            if len(cls.attributes) > 5:
                lines.append(f"    ... ({len(cls.attributes) - 5} more)")
            lines.append("}")
        else:
            # Class with no attributes
            lines.append(f"class {class_name} {{")
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

        # Build relationship with labels
        label_parts = []
        if conn.source.role:
            label_parts.append(conn.source.role)
        if conn.destination.role:
            label_parts.append(conn.destination.role)

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
        Sanitize name for Mermaid syntax.

        :param name: Original name
        :return: Sanitized name
        """
        sanitized = name.replace("::", "_")
        sanitized = sanitized.replace("-", "_")
        sanitized = sanitized.replace(" ", "_")
        return sanitized

    def _format_attribute(self, attr) -> str:
        """
        Format attribute for Mermaid.

        :param attr: Model attribute
        :return: Formatted attribute string
        """
        visibility = "+"
        attr_name = attr.name.lstrip("_")
        attr_name = attr_name.replace("-", "_")

        type_str = attr.type or "unknown"
        if attr.is_collection:
            type_str = f"{type_str}[]"

        optional_marker = "?" if attr.is_optional else ""

        return f"{visibility}{attr_name}{optional_marker} {type_str}"
