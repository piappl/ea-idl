"""
Diagram builder - Builds renderer-agnostic diagram descriptions from EA models.

This module extracts transformation logic from the EA model to diagram descriptions.
Builders create DiagramDescription objects that renderers can then convert to
format-specific output (Mermaid text, PlantUML SVG, etc.).
"""

from typing import List, Set
from eaidl.model import ModelPackage, ModelClass, ModelAttribute
from eaidl.config import Configuration
from eaidl.link_utils import generate_class_link, get_inherited_attributes
from eaidl.mermaid_utils import sanitize_id
from eaidl.diagram_model import (
    DiagramClassNode,
    DiagramAttribute,
    DiagramRelationship,
    DiagramClickHandler,
    DiagramNote,
    ClassDiagramDescription,
    RelationType,
)
import logging

log = logging.getLogger(__name__)


class ClassDiagramBuilder:
    """Builds ClassDiagramDescription from ModelPackage."""

    def __init__(
        self,
        package: ModelPackage,
        config: Configuration,
        all_packages: List[ModelPackage] = None,
    ):
        """
        Initialize diagram builder.

        :param package: Package to build diagram for
        :param config: Configuration object
        :param all_packages: All packages in the model (for inheritance lookups)
        """
        self.package = package
        self.config = config
        self.all_packages = all_packages or [package]
        self.processed_classes: Set[str] = set()
        self.max_attributes = config.diagrams.max_attributes_displayed

    def build(self) -> ClassDiagramDescription:
        """
        Build a complete class diagram description.

        :return: ClassDiagramDescription
        """
        nodes = []
        relationships = []
        click_handlers = []
        notes = []

        # Build nodes for all classes
        for cls in self.package.classes:
            node = self._build_class_node(cls)
            nodes.append(node)

        # Build relationships
        for cls in self.package.classes:
            cls_relationships = self._build_relationships(cls)
            relationships.extend(cls_relationships)

        # Build click handlers for navigation
        for cls in self.package.classes:
            handler = self._build_click_handler(cls)
            click_handlers.append(handler)

        # Build notes for stereotypes (if any)
        for cls in self.package.classes:
            if cls.stereotypes:
                node_notes = self._build_stereotype_notes(cls)
                notes.extend(node_notes)

        return ClassDiagramDescription(
            nodes=nodes,
            relationships=relationships,
            click_handlers=click_handlers,
            notes=notes,
        )

    def _build_class_node(self, cls: ModelClass) -> DiagramClassNode:
        """
        Build a DiagramClassNode from a ModelClass.

        :param cls: Model class
        :return: DiagramClassNode
        """
        safe_id = sanitize_id(cls.name)
        self.processed_classes.add(safe_id)

        # Collect all attributes (inherited + own)
        all_attrs = []

        # Get inherited attributes first
        if cls.generalization:
            inherited_attrs = get_inherited_attributes(cls, self.all_packages)
            all_attrs.extend(inherited_attrs)

        # Add own attributes
        all_attrs.extend(cls.attributes)

        # Convert to DiagramAttribute objects, respecting max limit
        diagram_attrs = []
        inherited_count = len(all_attrs) - len(cls.attributes)

        for i, attr in enumerate(all_attrs[: self.max_attributes]):
            is_inherited = i < inherited_count
            diagram_attr = self._build_diagram_attribute(attr, is_inherited)
            diagram_attrs.append(diagram_attr)

        # If there are more attributes than the limit, add a note
        if len(all_attrs) > self.max_attributes:
            # This will be represented differently by different renderers
            # For now, we just truncate and let renderers handle the "..." indicator
            pass

        # Build node with stereotypes
        stereotypes = list(cls.stereotypes) if cls.stereotypes else []

        # Handle namespace (can be string or list)
        if isinstance(cls.namespace, str):
            namespace = cls.namespace.split("::") if cls.namespace else []
        elif isinstance(cls.namespace, list):
            namespace = cls.namespace
        else:
            namespace = []

        return DiagramClassNode(
            id=safe_id,
            name=cls.name,
            attributes=diagram_attrs,
            stereotypes=stereotypes,
            is_abstract=cls.is_abstract,
            namespace=namespace,
        )

    def _build_diagram_attribute(self, attr: ModelAttribute, is_inherited: bool = False) -> DiagramAttribute:
        """
        Build a DiagramAttribute from a ModelAttribute.

        :param attr: Model attribute
        :param is_inherited: Whether this attribute is inherited
        :return: DiagramAttribute
        """
        # Sanitize attribute name
        attr_name = sanitize_id(attr.name)
        # Remove leading underscores for display
        attr_name = attr_name.lstrip("_") if attr_name.startswith("_") else attr_name

        # Sanitize type name
        type_str = sanitize_id(attr.type) if attr.type else "unknown"

        return DiagramAttribute(
            name=attr_name,
            type=type_str,
            visibility="+",  # Public by default
            is_collection=attr.is_collection,
            is_optional=attr.is_optional,
            is_inherited=is_inherited,
        )

    def _build_relationships(self, cls: ModelClass) -> List[DiagramRelationship]:
        """
        Build DiagramRelationship objects for a class.

        :param cls: Model class
        :return: List of relationships
        """
        relationships = []
        class_id = sanitize_id(cls.name)

        # Generalization (inheritance)
        if cls.generalization:
            parent_name = cls.generalization[-1]  # Last element is class name
            parent_id = sanitize_id(parent_name)
            relationships.append(
                DiagramRelationship(
                    source_id=class_id,
                    target_id=parent_id,
                    type=RelationType.INHERITANCE,
                )
            )

        # Associations (attributes referencing other classes)
        for attr in cls.attributes:
            if attr.type and attr.namespace:
                target_id = sanitize_id(attr.type)

                # Only add relationship if target class is in same package
                target_in_package = any(c.name == attr.type for c in self.package.classes)

                if target_in_package and target_id != class_id:
                    # Determine relationship type based on attribute properties
                    if attr.is_collection:
                        # Collection: show cardinality
                        relationships.append(
                            DiagramRelationship(
                                source_id=class_id,
                                target_id=target_id,
                                type=RelationType.ASSOCIATION,
                                source_cardinality="1",
                                target_cardinality="*",
                            )
                        )
                    elif attr.is_optional:
                        # Optional: simple association
                        relationships.append(
                            DiagramRelationship(
                                source_id=class_id,
                                target_id=target_id,
                                type=RelationType.ASSOCIATION,
                            )
                        )
                    else:
                        # Required: composition (strong ownership)
                        relationships.append(
                            DiagramRelationship(
                                source_id=class_id,
                                target_id=target_id,
                                type=RelationType.COMPOSITION,
                            )
                        )

        # Union-Enum relationship
        if cls.union_enum:
            enum_name = cls.union_enum.split("::")[-1]  # Get last part
            enum_id = sanitize_id(enum_name)
            # Check if enum is in same package
            enum_in_package = any(c.name == enum_name for c in self.package.classes)
            if enum_in_package:
                relationships.append(
                    DiagramRelationship(
                        source_id=class_id,
                        target_id=enum_id,
                        type=RelationType.DEPENDENCY,
                    )
                )

        return relationships

    def _build_click_handler(self, cls: ModelClass) -> DiagramClickHandler:
        """
        Build a DiagramClickHandler for interactive navigation.

        :param cls: Model class
        :return: DiagramClickHandler
        """
        class_id = sanitize_id(cls.name)

        # Handle namespace (can be string or list)
        if isinstance(cls.namespace, str):
            namespace = cls.namespace.split("::") if cls.namespace else []
        elif isinstance(cls.namespace, list):
            namespace = cls.namespace
        else:
            namespace = []

        # Generate relative link from diagram page to class page
        # Diagram is at packages/{namespace}/diagram.html
        # Class is at classes/{namespace}/{ClassName}.html
        # Pass from_page_type="diagram" to indicate we're linking from diagram page
        link = generate_class_link(namespace, namespace, cls.name, from_page_type="diagram")

        return DiagramClickHandler(node_id=class_id, link=link)

    def _build_stereotype_notes(self, cls: ModelClass) -> List[DiagramNote]:
        """
        Build notes for class stereotypes.

        Some renderers (like Mermaid v11) don't support stereotypes in class diagrams,
        so we can represent them as notes.

        :param cls: Model class
        :return: List of notes
        """
        notes = []

        if cls.stereotypes:
            # Create a note about the stereotypes
            stereotype_text = ", ".join(f"<<{s}>>" for s in cls.stereotypes)
            note = DiagramNote(text=stereotype_text, attached_to=sanitize_id(cls.name))
            notes.append(note)

        return notes
