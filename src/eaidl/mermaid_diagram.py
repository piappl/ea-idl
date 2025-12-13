"""
Mermaid class diagram generator for HTML documentation.

This module generates Mermaid.js class diagrams from EA model packages,
including interactive links to class detail pages.
"""

from typing import List, Set
from eaidl.model import ModelPackage, ModelClass, ModelAttribute
from eaidl.config import Configuration
from eaidl.link_utils import generate_class_link
import logging

log = logging.getLogger(__name__)


class MermaidClassDiagramGenerator:
    """Generates Mermaid class diagrams from model packages."""

    def __init__(self, package: ModelPackage, config: Configuration):
        """
        Initialize Mermaid diagram generator.

        :param package: Package to generate diagram for
        :param config: Configuration object
        """
        self.package = package
        self.config = config
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
                    if attr.type not in self.config.primitive_types:
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

        # Collect external type references (types used but not defined in this package)
        external_types = self._collect_external_types()

        # Add stub definitions for external types (to avoid Mermaid errors)
        # Note: No stereotype since Mermaid v11 doesn't support stereotypes on empty classes
        for ext_type in sorted(external_types):
            sanitized = self._sanitize_name(ext_type)
            lines.append(f"class {sanitized}")

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
        Sanitize name for Mermaid syntax.

        Replaces special characters that might break Mermaid syntax.

        :param name: Original name
        :return: Sanitized name
        """
        # Mermaid class names should be alphanumeric + underscore
        # Replace :: with _ for namespace separators
        sanitized = name.replace("::", "_")
        sanitized = sanitized.replace("-", "_")
        sanitized = sanitized.replace(" ", "_")
        return sanitized

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
        Generate Mermaid class definition.

        :param cls: Model class
        :return: List of Mermaid syntax lines
        """
        lines = []
        class_name = self._sanitize_name(cls.name)

        # CRITICAL: Mermaid v11 does NOT support stereotypes in class diagrams
        # Neither "class Foo <<stereotype>>" nor "class Foo <<stereotype>> {}" work
        # Solution: Never add stereotypes - just show class name and attributes
        # The stereotype information is preserved in the class detail pages

        if cls.attributes:
            # Class with attributes - show them
            lines.append(f"class {class_name} {{")
            for i, attr in enumerate(cls.attributes[:10]):
                attr_line = self._format_attribute(attr)
                lines.append(f"    {attr_line}")

            if len(cls.attributes) > 10:
                lines.append(f"    ... ({len(cls.attributes) - 10} more)")

            lines.append("}")
        else:
            # Class with no attributes - just declare it
            lines.append(f"class {class_name}")

        self.processed_classes.add(class_name)
        return lines

    def _format_attribute(self, attr: ModelAttribute) -> str:
        """
        Format attribute for Mermaid class diagram.

        :param attr: Model attribute
        :return: Formatted attribute string
        """
        # Sanitize attribute name (remove leading underscores, special chars)
        attr_name = attr.name.lstrip("_") if attr.name.startswith("_") else attr.name
        attr_name = attr_name.replace("-", "_")

        # Determine visibility
        visibility = "+"  # Public by default

        # Build type string
        type_str = attr.type or "unknown"

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
            lines.append(f"{class_name} --|> {sanitized_parent} : inherits")

        # Associations (attributes referencing other classes)
        for attr in cls.attributes:
            if attr.type and attr.namespace:
                # Check if type is another class (not primitive)
                target_name = self._sanitize_name(attr.type)

                # Only add relationship if target class is in same package
                target_in_package = any(c.name == attr.type for c in self.package.classes)

                if target_in_package and target_name != class_name:
                    # Use composition for non-optional, association for optional
                    if attr.is_collection:
                        lines.append(f'{class_name} "1" --> "*" {target_name} : {attr.name}')
                    elif attr.is_optional:
                        lines.append(f"{class_name} --> {target_name} : {attr.name}")
                    else:
                        lines.append(f"{class_name} *-- {target_name} : {attr.name}")

        # Union-Enum relationship
        if cls.union_enum:
            enum_name = cls.union_enum.split("::")[-1]  # Get last part of qualified name
            sanitized_enum = self._sanitize_name(enum_name)
            # Check if enum is in same package
            enum_in_package = any(c.name == enum_name for c in self.package.classes)
            if enum_in_package:
                lines.append(f"{class_name} ..> {sanitized_enum} : <<union>>")

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


def generate_package_diagram(package: ModelPackage, config: Configuration) -> str:
    """
    Generate Mermaid class diagram for a package.

    Convenience function that creates a MermaidClassDiagramGenerator
    and generates the diagram.

    :param package: Package to diagram
    :param config: Configuration
    :return: Mermaid diagram syntax
    """
    generator = MermaidClassDiagramGenerator(package, config)
    return generator.generate_mermaid()
