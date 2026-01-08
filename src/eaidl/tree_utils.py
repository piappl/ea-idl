"""Generic tree traversal utilities for ModelPackage hierarchies.

This module provides reusable functions for traversing and searching
the package/class tree structure, eliminating code duplication across
the codebase.
"""

from typing import Callable, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from eaidl.model import ModelPackage, ModelClass, ModelAttribute


def traverse_packages(
    packages: List["ModelPackage"],
    package_visitor: Optional[Callable[["ModelPackage"], None]] = None,
    class_visitor: Optional[Callable[["ModelClass", "ModelPackage"], None]] = None,
) -> None:
    """Generic package tree traversal with visitor pattern.

    Recursively visits all packages and classes in the tree, applying
    visitor functions at each node. This is the foundation for all
    tree traversal operations.

    Args:
        packages: List of root packages to traverse
        package_visitor: Optional function called for each package
        class_visitor: Optional function called for each class with its parent package

    Example:
        >>> def print_package(pkg):
        ...     print(f"Package: {pkg.name}")
        >>> def print_class(cls, pkg):
        ...     print(f"  Class: {cls.name} in {pkg.name}")
        >>> traverse_packages(packages, print_package, print_class)
    """
    for pkg in packages:
        if package_visitor:
            package_visitor(pkg)

        if class_visitor:
            for cls in pkg.classes:
                class_visitor(cls, pkg)

        # Recurse into sub-packages
        traverse_packages(pkg.packages, package_visitor, class_visitor)


def find_class(packages: List["ModelPackage"], predicate: Callable[["ModelClass"], bool]) -> Optional["ModelClass"]:
    """Find first class matching predicate in package tree.

    This is the generic class finder that all other find_* functions use.
    Performs depth-first search through the package tree.

    Args:
        packages: List of packages to search
        predicate: Function that takes ModelClass and returns True if it matches

    Returns:
        First ModelClass matching predicate, or None if not found

    Example:
        >>> cls = find_class(packages, lambda c: c.name == "Message")
        >>> cls = find_class(packages, lambda c: c.object_id == 123)
    """
    result: Optional["ModelClass"] = None

    def visitor(cls: "ModelClass", pkg: "ModelPackage") -> None:
        nonlocal result
        if result is None and predicate(cls):
            result = cls

    traverse_packages(packages, class_visitor=visitor)
    return result


def find_class_by_id(packages: List["ModelPackage"], object_id: int) -> Optional["ModelClass"]:
    """Find class by object_id.

    Convenience wrapper around find_class for the common case of
    finding a class by its EA object ID.

    Args:
        packages: List of packages to search
        object_id: EA object ID to find

    Returns:
        ModelClass with matching object_id, or None if not found
    """
    return find_class(packages, lambda c: c.object_id == object_id)


def find_class_by_name(
    packages: List["ModelPackage"], name: str, namespace: Optional[List[str]] = None
) -> Optional["ModelClass"]:
    """Find class by name, optionally within a specific namespace.

    Args:
        packages: List of packages to search
        name: Class name to find
        namespace: Optional namespace to narrow search. If None, finds first match.

    Returns:
        ModelClass with matching name (and namespace if specified), or None

    Example:
        >>> cls = find_class_by_name(packages, "Message")
        >>> cls = find_class_by_name(packages, "Message", ["core", "data"])
    """
    return find_class(packages, lambda c: c.name == name and (namespace is None or c.namespace == namespace))


def find_class_by_namespace(packages: List["ModelPackage"], namespace: List[str]) -> Optional["ModelClass"]:
    """Find class by its full namespace path.

    The namespace includes the class name as the last element.
    For example, ["core", "data", "Message"] means class Message
    in namespace ["core", "data"].

    Args:
        packages: List of packages to search
        namespace: Full namespace path including class name as last element

    Returns:
        ModelClass at the specified namespace, or None if not found

    Example:
        >>> cls = find_class_by_namespace(packages, ["core", "data", "Message"])
    """
    if not namespace:
        return None

    class_name = namespace[-1]
    class_namespace = namespace[:-1]

    return find_class(packages, lambda c: c.name == class_name and c.namespace == class_namespace)


def collect_all_classes(packages: List["ModelPackage"]) -> List["ModelClass"]:
    """Flatten package tree to list of all classes.

    Recursively collects all classes from all packages in the tree.
    Useful for operations that need to process all classes without
    caring about package structure.

    Args:
        packages: List of root packages

    Returns:
        List of all ModelClass objects in the tree

    Example:
        >>> all_classes = collect_all_classes(packages)
        >>> print(f"Total classes: {len(all_classes)}")
    """
    classes: List["ModelClass"] = []

    def visitor(cls: "ModelClass", pkg: "ModelPackage") -> None:
        classes.append(cls)

    traverse_packages(packages, class_visitor=visitor)
    return classes


def collect_packages(
    packages: List["ModelPackage"], predicate: Optional[Callable[["ModelPackage"], bool]] = None
) -> List["ModelPackage"]:
    """Collect all packages matching predicate.

    Recursively collects packages from the tree. If no predicate is given,
    returns all packages (flattens the package hierarchy).

    Args:
        packages: List of root packages
        predicate: Optional filter function. If None, collects all packages.

    Returns:
        List of ModelPackage objects matching predicate

    Example:
        >>> all_pkgs = collect_packages(packages)
        >>> data_pkgs = collect_packages(packages, lambda p: "data" in p.name.lower())
    """
    collected: List["ModelPackage"] = []

    def visitor(pkg: "ModelPackage") -> None:
        if predicate is None or predicate(pkg):
            collected.append(pkg)

    traverse_packages(packages, package_visitor=visitor)
    return collected


def collect_attributes(
    packages: List["ModelPackage"], predicate: Callable[["ModelAttribute", "ModelClass"], bool]
) -> List["ModelAttribute"]:
    """Collect all attributes matching predicate.

    Recursively searches all classes in the package tree and collects
    attributes that match the predicate. The predicate receives both
    the attribute and its parent class for context.

    Args:
        packages: List of root packages
        predicate: Function that takes (ModelAttribute, ModelClass) and returns bool

    Returns:
        List of ModelAttribute objects matching predicate

    Example:
        >>> # Find all map attributes
        >>> maps = collect_attributes(packages, lambda attr, cls: attr.is_map)
        >>> # Find attributes of a specific type
        >>> strings = collect_attributes(packages, lambda attr, cls: attr.type == "string")
    """
    collected: List["ModelAttribute"] = []

    def visitor(cls: "ModelClass", pkg: "ModelPackage") -> None:
        for attr in cls.attributes:
            if predicate(attr, cls):
                collected.append(attr)

    traverse_packages(packages, class_visitor=visitor)
    return collected
