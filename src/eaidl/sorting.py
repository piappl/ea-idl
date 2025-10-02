from typing import List, Dict, Callable
from collections import deque
import logging

from eaidl.model import ModelClass, ModelPackage

log = logging.getLogger(__name__)


class CircularDependencyError(Exception):
    """Exception raised for circular dependencies in topological sort."""

    pass


def topological_sort_classes(classes: List[ModelClass]) -> List[ModelClass]:
    """
    Performs a deterministic topological sort on a list of ModelClass objects.

    Each object in the list must have an 'object_id' attribute and a 'depends_on'
    attribute which is a list of object_ids it depends on.

    :param classes: A list of ModelClass-like objects.
    :return: A new list of ModelClass-like objects in topological order.
    :raises CircularDependencyError: If a circular dependency is detected.
    """
    in_degree: Dict[int, int] = {cls.object_id: 0 for cls in classes}
    adj: Dict[int, List[int]] = {cls.object_id: [] for cls in classes}
    id_to_class: Dict[int, ModelClass] = {cls.object_id: cls for cls in classes}

    for cls in classes:
        for dep_id in cls.depends_on:
            if dep_id in id_to_class:  # Only consider dependencies within the provided classes
                adj[dep_id].append(cls.object_id)
                in_degree[cls.object_id] += 1

    # Initialize queue with all nodes having in-degree 0, sorted for determinism
    queue = deque(sorted([cls_id for cls_id, degree in in_degree.items() if degree == 0]))
    sorted_classes: List[ModelClass] = []

    while queue:
        u_id = queue.popleft()
        sorted_classes.append(id_to_class[u_id])

        for v_id in sorted(adj[u_id]):  # Sort for determinism
            in_degree[v_id] -= 1
            if in_degree[v_id] == 0:
                queue.append(v_id)
        # Re-sort the queue to maintain determinism if new items are added
        # This is important if multiple nodes become ready at the same time
        # and their relative order matters for determinism.
        # A simple way is to convert to list, sort, and convert back to deque.
        temp_list = sorted(list(queue))
        queue = deque(temp_list)

    if len(sorted_classes) != len(classes):
        remaining_nodes = [id_to_class[cls_id].name for cls_id, degree in in_degree.items() if degree > 0]
        raise CircularDependencyError(f"Circular dependency detected in classes: {remaining_nodes}")

    return sorted_classes


def topological_sort_packages(
    packages: List[ModelPackage],
    get_all_depends_on: Callable[[ModelPackage], List[int]],
    get_all_class_id: Callable[[ModelPackage], List[int]],
) -> List[ModelPackage]:
    """
    Performs a deterministic topological sort on a list of ModelPackage objects.

    Each object in the list must have a 'package_id' attribute.
    Dependencies are determined by comparing 'depends_on' of a package's contents
    with 'object_id's of other packages' contents.

    :param packages: A list of ModelPackage-like objects.
    :param get_all_depends_on: A callable that takes a ModelPackage and returns a list of object_ids it depends on.
    :param get_all_class_id: A callable that takes a ModelPackage and returns a list of object_ids of classes it contains.
    :return: A new list of ModelPackage-like objects in topological order.
    :raises CircularDependencyError: If a circular dependency is detected.
    """
    in_degree: Dict[int, int] = {pkg.package_id: 0 for pkg in packages}
    adj: Dict[int, List[int]] = {pkg.package_id: [] for pkg in packages}
    id_to_package: Dict[int, ModelPackage] = {pkg.package_id: pkg for pkg in packages}

    # Build the graph
    for u_pkg in packages:
        u_depends_on = set(get_all_depends_on(u_pkg))
        for v_pkg in packages:
            if u_pkg.package_id == v_pkg.package_id:
                continue

            v_class_ids = set(get_all_class_id(v_pkg))
            if u_depends_on.intersection(v_class_ids):
                # u_pkg depends on v_pkg
                adj[v_pkg.package_id].append(u_pkg.package_id)
                in_degree[u_pkg.package_id] += 1

    # Initialize queue with all nodes having in-degree 0, sorted for determinism
    queue = deque(sorted([pkg_id for pkg_id, degree in in_degree.items() if degree == 0]))
    sorted_packages: List[ModelPackage] = []

    while queue:
        u_id = queue.popleft()
        sorted_packages.append(id_to_package[u_id])

        for v_id in sorted(adj[u_id]):  # Sort for determinism
            in_degree[v_id] -= 1
            if in_degree[v_id] == 0:
                queue.append(v_id)
        # Re-sort the queue to maintain determinism
        temp_list = sorted(list(queue))
        queue = deque(temp_list)

    if len(sorted_packages) != len(packages):
        remaining_nodes = [id_to_package[pkg_id].name for pkg_id, degree in in_degree.items() if degree > 0]
        raise CircularDependencyError(f"Circular dependency detected in packages: {remaining_nodes}")

    return sorted_packages
