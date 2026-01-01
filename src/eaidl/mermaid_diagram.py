"""
Mermaid class diagram generator for HTML documentation.

This module generates Mermaid.js class diagrams from EA model packages,
including interactive links to class detail pages.
"""

from typing import List, Set
from eaidl.model import ModelPackage, ModelClass, ModelAttribute
from eaidl.config import Configuration
from eaidl.link_utils import generate_class_link, get_inherited_attributes
from eaidl.mermaid_utils import sanitize_id, get_class_label
import logging

log = logging.getLogger(__name__)


class MermaidClassDiagramGenerator:
    """Generates Mermaid class diagrams from model packages."""

    def __init__(self, package: ModelPackage, config: Configuration, all_packages: List[ModelPackage] = None):
        """
        Initialize Mermaid diagram generator.

        :param package: Package to generate diagram for
        :param config: Configuration object
        :param all_packages: All packages in the model (for inheritance lookups)
        """
        self.package = package
        self.config = config
        self.all_packages = all_packages or [package]
        self.processed_classes: Set[str] = set()

    def _collect_external_types(self) -> Set[str]:
        """
        Collect all type names that are referenced but not defined in this package.

        :return: Set of external type names
        """
        external_types = set()
        package_class_names = {cls.name for cls in self.package.classes}

        for cls in self.package.classes:
            for attr in cls.attributes:
                if attr.type and attr.type not in package_class_names:
                    # Skip primitive types
                    if not self.config.is_primitive_type(attr.type):
                        external_types.add(attr.type)

        return external_types

    def generate_mermaid(self) -> str:
        """
        Generate Mermaid class diagram for the package.

        Returns Mermaid syntax showing:
        - All classes in package (not nested packages)
        - Class attributes with types
        - Relationships (associations, generalizations)
        - Interactive links to class detail pages

        :return: Mermaid class diagram syntax
        """
        lines = ["classDiagram"]

        # Note: We don't declare external types as separate classes because:
        # 1. They're already visible in attribute type annotations
        # 2. Declaring them without relationships creates orphaned nodes
        # 3. It keeps diagrams focused on the current package

        # Generate class definitions
        for cls in self.package.classes:
            class_def = self._generate_class_definition(cls)
            lines.extend(class_def)

        # Generate relationships
        for cls in self.package.classes:
            relationships = self._generate_relationships(cls)
            lines.extend(relationships)

        # Generate click handlers for interactivity
        for cls in self.package.classes:
            click_handler = self._generate_click_handler(cls)
            if click_handler:
                lines.append(click_handler)

        return "\n".join(lines)

    def _sanitize_name(self, name: str) -> str:
        """
        Generate safe Mermaid identifier from name.

        Uses mermaid_utils.sanitize_id for robust handling of special characters.

        :param name: Original name
        :return: Safe identifier
        """
        return sanitize_id(name)

    def _get_stereotype_marker(self, cls: ModelClass) -> str:
        """
        Get Mermaid stereotype marker for a class.

        :param cls: Model class
        :return: Stereotype string
        """
        if self.config.stereotypes.idl_enum in cls.stereotypes:
            return "<<enumeration>>"
        elif self.config.stereotypes.idl_union in cls.stereotypes:
            return "<<union>>"
        elif self.config.stereotypes.idl_typedef in cls.stereotypes:
            return "<<typedef>>"
        elif cls.is_abstract:
            return "<<abstract>>"
        return ""

    def _generate_class_definition(self, cls: ModelClass) -> List[str]:
        """
        Generate Mermaid class definition including inherited attributes.

        Uses label syntax for names with special characters.

        :param cls: Model class
        :return: List of Mermaid syntax lines
        """
        lines = []
        safe_id = self._sanitize_name(cls.name)

        # Use label syntax if name contains special characters
        class_decl = get_class_label(cls.name)

        # CRITICAL: Mermaid v11 does NOT support stereotypes in class diagrams
        # Neither "class Foo <<stereotype>>" nor "class Foo <<stereotype>> {}" work
        # Solution: Never add stereotypes - just show class name and attributes
        # The stereotype information is preserved in the class detail pages

        # Collect all attributes (inherited + own)
        all_attrs = []

        # Get inherited attributes first
        if cls.generalization:
            inherited_attrs = get_inherited_attributes(cls, self.all_packages)
            all_attrs.extend(inherited_attrs)

        # Add own attributes
        all_attrs.extend(cls.attributes)

        if all_attrs:
            # Class with attributes - show them
            lines.append(f"class {class_decl} {{")

            # Show inherited attributes first
            inherited_count = len(all_attrs) - len(cls.attributes)
            for i, attr in enumerate(all_attrs[:15]):  # Limit total to 15
                attr_line = self._format_attribute(attr)
                # Mark inherited attributes - use asterisk prefix to avoid parser issues
                if i < inherited_count:
                    # Prepend asterisk to indicate inheritance
                    # Split the line to insert asterisk after visibility marker
                    if attr_line.startswith("+") or attr_line.startswith("-"):
                        attr_line = attr_line[0] + "*" + attr_line[1:]
                lines.append(f"    {attr_line}")

            if len(all_attrs) > 15:
                lines.append(f"    ... ({len(all_attrs) - 15} more)")

            lines.append("}")
        else:
            # Class with no attributes - add empty placeholder to help with layout
            # Empty class declarations can cause "Could not find suitable point" errors
            # when they are used in relationships
            lines.append(f"class {class_decl} {{")
            lines.append("}")

        self.processed_classes.add(safe_id)
        return lines

    def _format_attribute(self, attr: ModelAttribute) -> str:
        """
        Format attribute for Mermaid class diagram.

        Sanitizes attribute names to avoid special characters.

        :param attr: Model attribute
        :return: Formatted attribute string
        """
        # Sanitize attribute name (remove special chars)
        attr_name = sanitize_id(attr.name)
        # Remove leading underscores for display
        attr_name = attr_name.lstrip("_") if attr_name.startswith("_") else attr_name

        # Determine visibility
        visibility = "+"  # Public by default

        # Build type string - sanitize type name too
        type_str = sanitize_id(attr.type) if attr.type else "unknown"

        # Add collection indicator (use simpler syntax for better compatibility)
        if attr.is_collection:
            type_str = f"{type_str}[]"

        # Add optional indicator
        optional_marker = "?" if attr.is_optional else ""

        # Format: +name type or +name? type
        return f"{visibility}{attr_name}{optional_marker} {type_str}"

    def _generate_relationships(self, cls: ModelClass) -> List[str]:
        """
        Generate Mermaid relationship lines for a class.

        :param cls: Model class
        :return: List of Mermaid relationship syntax
        """
        lines = []
        class_name = self._sanitize_name(cls.name)

        # Generalization (inheritance)
        if cls.generalization:
            parent_name = cls.generalization[-1]  # Last element is class name
            sanitized_parent = self._sanitize_name(parent_name)
            lines.append(f"{class_name} --|> {sanitized_parent}")

        # Associations (attributes referencing other classes)
        for attr in cls.attributes:
            if attr.type and attr.namespace:
                # Check if type is another class (not primitive)
                target_name = self._sanitize_name(attr.type)

                # Only add relationship if target class is in same package
                target_in_package = any(c.name == attr.type for c in self.package.classes)

                if target_in_package and target_name != class_name:
                    # Use composition for non-optional, association for optional
                    # Note: Labels removed to avoid "Could not find suitable point" errors in browser Mermaid.js
                    if attr.is_collection:
                        lines.append(f'{class_name} "1" --> "*" {target_name}')
                    elif attr.is_optional:
                        lines.append(f"{class_name} --> {target_name}")
                    else:
                        lines.append(f"{class_name} *-- {target_name}")

        # Union-Enum relationship
        if cls.union_enum:
            enum_name = cls.union_enum.split("::")[-1]  # Get last part of qualified name
            sanitized_enum = self._sanitize_name(enum_name)
            # Check if enum is in same package
            enum_in_package = any(c.name == enum_name for c in self.package.classes)
            if enum_in_package:
                lines.append(f"{class_name} ..> {sanitized_enum}")

        return lines

    def _generate_click_handler(self, cls: ModelClass) -> str:
        """
        Generate Mermaid click handler for interactive link.

        :param cls: Model class
        :return: Mermaid click syntax
        """
        class_name = self._sanitize_name(cls.name)

        # Generate relative link from diagram page to class page
        # Diagram is at packages/{namespace}/diagram.html
        # Class is at classes/{namespace}/{ClassName}.html
        # From packages/{namespace}/ we need to go to root, then to classes/{namespace}/
        namespace = cls.namespace

        # Calculate relative path
        link = generate_class_link(namespace, namespace, cls.name)

        # Mermaid click syntax - _self makes it open in same tab instead of new tab
        return f'click {class_name} href "{link}" _self'


def generate_package_diagram(
    package: ModelPackage, config: Configuration, all_packages: List[ModelPackage] = None
) -> str:
    """
    Generate Mermaid class diagram for a package.

    Convenience function that creates a MermaidClassDiagramGenerator
    and generates the diagram.

    :param package: Package to diagram
    :param config: Configuration
    :param all_packages: All packages in the model (for inheritance lookups)
    :return: Mermaid diagram syntax
    """
    generator = MermaidClassDiagramGenerator(package, config, all_packages)
    return generator.generate_mermaid()
