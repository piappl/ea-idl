from typing import List, Dict, Callable, Set, Optional
from collections import deque
import logging

from eaidl.model import ModelClass, ModelPackage

log = logging.getLogger(__name__)


class CircularDependencyError(Exception):
    """Exception raised for circular dependencies in topological sort."""

    pass


def find_cycle_path(
    start_id: int, id_to_class: Dict[int, ModelClass], remaining_ids: Set[int], max_depth: int = 20
) -> Optional[List[str]]:
    """
    Find a cycle path starting from start_id using DFS.

    Returns a list of class names forming a cycle, or None if no cycle found.
    """
    visited = set()
    path = []

    def dfs(current_id: int, depth: int) -> bool:
        if depth > max_depth:
            return False

        if current_id in path:
            # Found a cycle! Return the cycle portion
            return True

        if current_id in visited:
            return False

        visited.add(current_id)
        path.append(current_id)

        current_cls = id_to_class.get(current_id)
        if current_cls:
            for dep_id in current_cls.depends_on:
                if dep_id in remaining_ids and dep_id in id_to_class:
                    if dfs(dep_id, depth + 1):
                        return True

        path.pop()
        return False

    if dfs(start_id, 0):
        # Convert IDs to names
        return [id_to_class[cls_id].name for cls_id in path]
    return None


def topological_sort_classes(classes: List[ModelClass], scc_map: Dict[int, Set[int]] = None) -> List[ModelClass]:
    """
    Performs a deterministic topological sort on a list of ModelClass objects.

    Each object in the list must have an 'object_id' attribute and a 'depends_on'
    attribute which is a list of object_ids it depends on.

    :param classes: A list of ModelClass-like objects.
    :param scc_map: Optional dict mapping object_id to its SCC (strongly connected component).
                    Dependencies within the same SCC are ignored to allow circular references.
    :return: A new list of ModelClass-like objects in topological order.
    :raises CircularDependencyError: If a circular dependency is detected (outside of allowed SCCs).
    """
    scc_map = scc_map or {}
    in_degree: Dict[int, int] = {cls.object_id: 0 for cls in classes}
    adj: Dict[int, List[int]] = {cls.object_id: [] for cls in classes}
    id_to_class: Dict[int, ModelClass] = {cls.object_id: cls for cls in classes}

    for cls in classes:
        for dep_id in cls.depends_on:
            if dep_id not in id_to_class:
                continue  # Only consider dependencies within the provided classes

            # Check if this dependency is within the same SCC (allowed cycle)
            cls_scc = scc_map.get(cls.object_id, {cls.object_id})
            if dep_id in cls_scc:
                # Dependency within same SCC - skip to allow circular references
                log.debug(f"Ignoring circular dependency: {cls.name} -> " f"{id_to_class[dep_id].name} (same SCC)")
                continue

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
        # Build detailed error message with dependency information
        remaining_ids = [cls_id for cls_id, degree in in_degree.items() if degree > 0]
        remaining_nodes = [id_to_class[cls_id] for cls_id in remaining_ids]
        remaining_id_set = set(remaining_ids)

        # Try to find an example cycle path
        cycle_path = None
        for cls_id in remaining_ids[:5]:  # Check first 5 for performance
            cycle_path = find_cycle_path(cls_id, id_to_class, remaining_id_set)
            if cycle_path:
                break

        # Build dependency graph for remaining nodes
        error_msg = ["Circular dependency detected in classes:", ""]

        if cycle_path:
            error_msg.append("Example cycle path:")
            for i, name in enumerate(cycle_path):
                cls = next((c for c in remaining_nodes if c.name == name), None)
                if cls:
                    typedef_marker = " [typedef]" if cls.is_typedef else ""
                    struct_marker = " [struct]" if cls.is_struct else ""
                    union_marker = " [union]" if cls.is_union else ""
                    type_marker = typedef_marker or struct_marker or union_marker
                    error_msg.append(f"  {i+1}. {name}{type_marker}")
            error_msg.append(f"  {len(cycle_path)+1}. {cycle_path[0]} (back to start)")
            error_msg.append("")

        error_msg.append(f"All classes in cycle ({len(remaining_nodes)}):")

        for cls in remaining_nodes:
            # Show class info
            typedef_marker = " [typedef]" if cls.is_typedef else ""
            struct_marker = " [struct]" if cls.is_struct else ""
            union_marker = " [union]" if cls.is_union else ""
            enum_marker = " [enum]" if cls.is_enum else ""
            type_marker = typedef_marker or struct_marker or union_marker or enum_marker

            # Show dependencies
            deps_in_cycle = [
                id_to_class[dep_id].name
                for dep_id in cls.depends_on
                if dep_id in id_to_class and dep_id in remaining_id_set
            ]

            if deps_in_cycle:
                error_msg.append(f"  - {cls.name}{type_marker} -> {', '.join(deps_in_cycle)}")
            else:
                error_msg.append(f"  - {cls.name}{type_marker} (no deps in cycle)")

        error_msg.append("")
        error_msg.append("Hint: Check for circular references between these types.")
        error_msg.append("      If using recursive types, ensure they use sequence<> or are in the same SCC.")

        raise CircularDependencyError("\n".join(error_msg))

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
