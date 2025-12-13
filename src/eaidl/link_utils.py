"""
Link utilities for HTML documentation export.

This module provides functions for generating relative links between different
pages in the HTML documentation hierarchy.
"""

from typing import List, Optional, Dict
from eaidl.model import ModelAttribute, ModelClass, ModelPackage


def get_relative_path(from_namespace: List[str], to_namespace: List[str]) -> str:
    """
    Calculate relative path from one namespace to another.

    Examples:
        >>> get_relative_path(['core', 'data'], ['core', 'types'])
        '../types'
        >>> get_relative_path(['core', 'data', 'nested'], ['core', 'types'])
        '../../types'
        >>> get_relative_path(['core'], ['core', 'data'])
        'data'
        >>> get_relative_path(['core', 'data'], ['core', 'data'])
        '.'

    :param from_namespace: Source namespace as list of names
    :param to_namespace: Target namespace as list of names
    :return: Relative path string
    """
    # Find common prefix
    common_len = 0
    for i, (f, t) in enumerate(zip(from_namespace, to_namespace)):
        if f == t:
            common_len = i + 1
        else:
            break

    # Calculate ups (..)
    ups = len(from_namespace) - common_len
    # Calculate downs (remaining path)
    downs = to_namespace[common_len:]

    # Build path
    if ups == 0 and len(downs) == 0:
        return "."

    path_parts = [".."] * ups + downs
    return "/".join(path_parts)


def get_namespace_depth(namespace: List[str]) -> int:
    """
    Get depth of namespace (number of levels).

    :param namespace: Namespace as list of names
    :return: Depth count
    """
    return len(namespace)


def generate_class_link(
    from_namespace: List[str], to_namespace: List[str], class_name: str, from_page_type: str = "package"
) -> str:
    """
    Generate relative link from current namespace to a class page.

    Example:
        From package page at packages/core/data/index.html
        To class page at classes/core/types/Identifier.html
        Returns: ../../../classes/core/types/Identifier.html

    :param from_namespace: Current page's namespace
    :param to_namespace: Target class's namespace
    :param class_name: Target class name
    :param from_page_type: Type of page we're linking from ('package', 'class', 'diagram')
    :return: Relative URL to class page
    """
    # Calculate path from current namespace to root
    # If from_namespace is empty, we're at the root index.html (no directory nesting)
    # Otherwise, add 1 for packages/ or classes/ directory
    if len(from_namespace) == 0:
        # At root index.html - no ups needed
        depth = 0
    else:
        # At packages/{namespace}/ or classes/{namespace}/ - need to go up
        depth = len(from_namespace) + 1  # +1 for packages/ or classes/ directory

    to_root = "/".join([".."] * depth)

    # Build path from root to target class
    if to_root:
        class_path_parts = [to_root, "classes"] + to_namespace + [f"{class_name}.html"]
    else:
        class_path_parts = ["classes"] + to_namespace + [f"{class_name}.html"]

    return "/".join(class_path_parts)


def generate_package_link(from_namespace: List[str], to_namespace: List[str]) -> str:
    """
    Generate relative link from current namespace to a package page.

    :param from_namespace: Current page's namespace
    :param to_namespace: Target package's namespace
    :return: Relative URL to package index page
    """
    # Calculate path from current namespace to root
    # If from_namespace is empty, we're at the root index.html (no directory nesting)
    # Otherwise, add 1 for packages/ directory
    if len(from_namespace) == 0:
        # At root index.html - no ups needed
        depth = 0
    else:
        # At packages/{namespace}/ - need to go up
        depth = len(from_namespace) + 1  # +1 for packages/ directory

    to_root = "/".join([".."] * depth)

    # Build path from root to target package
    if to_root:
        package_path_parts = [to_root, "packages"] + to_namespace + ["index.html"]
    else:
        package_path_parts = ["packages"] + to_namespace + ["index.html"]

    return "/".join(package_path_parts)


def generate_diagram_link(from_namespace: List[str], to_namespace: List[str]) -> str:
    """
    Generate relative link from current namespace to a package diagram page.

    :param from_namespace: Current page's namespace
    :param to_namespace: Target package's namespace
    :return: Relative URL to diagram page
    """
    # Calculate path from current namespace to root
    # If from_namespace is empty, we're at the root index.html (no directory nesting)
    # Otherwise, add 1 for packages/ directory
    if len(from_namespace) == 0:
        # At root index.html - no ups needed
        depth = 0
    else:
        # At packages/{namespace}/ - need to go up
        depth = len(from_namespace) + 1  # +1 for packages/ directory

    to_root = "/".join([".."] * depth)

    # Build path from root to target diagram
    if to_root:
        diagram_path_parts = [to_root, "packages"] + to_namespace + ["diagram.html"]
    else:
        diagram_path_parts = ["packages"] + to_namespace + ["diagram.html"]

    return "/".join(diagram_path_parts)


def generate_index_link(from_namespace: List[str]) -> str:
    """
    Generate relative link from current namespace to the index page.

    :param from_namespace: Current page's namespace
    :return: Relative URL to index.html
    """
    # If from_namespace is empty, we're already at the root index.html
    # Otherwise, pages are at packages/{namespace}/ or classes/{namespace}/
    if len(from_namespace) == 0:
        # At root index.html - link to self
        return "index.html"
    else:
        # At packages/{namespace}/ or classes/{namespace}/ - need to go up
        depth = len(from_namespace) + 1  # +1 for packages/ or classes/ directory
        to_root = "/".join([".."] * depth)
        return f"{to_root}/index.html"


def resolve_type_reference(
    attr: ModelAttribute, current_namespace: List[str], all_packages: List[ModelPackage]
) -> Dict[str, str]:
    """
    Resolve a type reference for an attribute to a clickable link.

    Returns dictionary with:
        - type: The type name (string)
        - link: Relative URL to type definition (or empty if primitive)
        - namespace: Namespace of the type
        - is_primitive: True if type is primitive (no link)
        - full_type: Full qualified type name

    :param attr: Model attribute
    :param current_namespace: Current page's namespace
    :param all_packages: All model packages (for type lookup)
    :return: Dictionary with type info
    """
    type_name = attr.type
    type_namespace = attr.namespace

    # Check if primitive type
    primitives = ["string", "int", "long", "float", "double", "bool", "octet", "char", "wchar"]
    if type_name in primitives:
        return {
            "type": type_name,
            "link": "",
            "namespace": [],
            "is_primitive": True,
            "full_type": type_name,
        }

    # Handle sequence/collection types
    is_collection = attr.is_collection or False
    if is_collection:
        # For sequences, link to the element type, not "sequence"
        if type_name and type_namespace:
            link = generate_class_link(current_namespace, type_namespace, type_name)
            full_type = "::".join(type_namespace + [type_name])
            return {
                "type": type_name,
                "link": link,
                "namespace": type_namespace,
                "is_primitive": False,
                "full_type": full_type,
                "is_collection": True,
            }

    # Regular class type
    if type_name and type_namespace:
        link = generate_class_link(current_namespace, type_namespace, type_name)
        full_type = "::".join(type_namespace + [type_name])
        return {
            "type": type_name,
            "link": link,
            "namespace": type_namespace,
            "is_primitive": False,
            "full_type": full_type,
        }

    # Fallback for unknown types
    return {
        "type": type_name or "unknown",
        "link": "",
        "namespace": [],
        "is_primitive": True,
        "full_type": type_name or "unknown",
    }


def find_class_by_name(
    packages: List[ModelPackage], class_name: str, namespace: Optional[List[str]] = None
) -> Optional[ModelClass]:
    """
    Find a class by name across all packages.

    :param packages: List of all model packages
    :param class_name: Class name to find
    :param namespace: Optional namespace to narrow search
    :return: ModelClass if found, None otherwise
    """

    def search_package(pkg: ModelPackage) -> Optional[ModelClass]:
        # Search classes in this package
        for cls in pkg.classes:
            if cls.name == class_name:
                if namespace is None or cls.namespace == namespace:
                    return cls

        # Search nested packages
        for nested in pkg.packages:
            result = search_package(nested)
            if result:
                return result

        return None

    for pkg in packages:
        result = search_package(pkg)
        if result:
            return result

    return None
