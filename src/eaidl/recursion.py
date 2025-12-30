"""Detect and handle recursive struct references using SCC algorithm."""

from typing import Set, List, Dict, Tuple
import logging

from eaidl.model import ModelPackage
from eaidl.utils import flatten_packages, find_class

log = logging.getLogger(__name__)


def tarjan_scc(graph: Dict[int, List[int]]) -> List[Set[int]]:
    """
    Find strongly connected components using Tarjan's algorithm.

    Args:
        graph: Adjacency list mapping node_id -> list of node_ids it points to

    Returns:
        List of sets, where each set is a strongly connected component
    """
    index_counter = [0]
    stack = []
    lowlinks = {}
    index = {}
    on_stack = set()
    sccs = []

    def strongconnect(node: int):
        index[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack.add(node)

        # Consider successors
        for successor in graph.get(node, []):
            if successor not in index:
                # Successor has not yet been visited; recurse on it
                strongconnect(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif successor in on_stack:
                # Successor is in stack and hence in the current SCC
                lowlinks[node] = min(lowlinks[node], index[successor])

        # If node is a root node, pop the stack and create an SCC
        if lowlinks[node] == index[node]:
            connected_component = set()
            while True:
                w = stack.pop()
                on_stack.remove(w)
                connected_component.add(w)
                if w == node:
                    break
            sccs.append(connected_component)

    for node in graph:
        if node not in index:
            strongconnect(node)

    return sccs


def find_type_cycles(packages: List[ModelPackage]) -> Dict[int, Set[int]]:
    """
    Find all strongly connected components (cycles) in struct and union dependencies.

    Only considers dependencies through sequence attributes (collections),
    as direct references are not allowed for recursive types in IDL.

    This handles:
    - Struct ↔ Struct cycles
    - Union ↔ Union cycles
    - Struct ↔ Union cycles

    Args:
        packages: List of model packages to analyze

    Returns:
        Dict mapping each struct/union object_id in a cycle to its SCC
        (set of object_ids in the same cycle, including itself)
    """
    # Build dependency graph for structs and unions
    graph = {}  # object_id -> list of object_ids it depends on (via sequence)
    all_types = {}  # object_id -> ModelClass

    # First pass: collect all structs and unions and initialize graph
    for pkg in flatten_packages(packages):
        for cls in pkg.classes:
            if cls.is_struct or cls.is_union:
                all_types[cls.object_id] = cls
                graph[cls.object_id] = []

    # Second pass: build dependency edges
    for cls_id, cls in all_types.items():
        for attr in cls.attributes:
            # Only consider sequence/collection attributes (IDL requirement)
            if not attr.is_collection:
                continue

            # Find target type by name and namespace
            target = find_class(packages, lambda c: c.name == attr.type and c.namespace == attr.namespace)

            if target and (target.is_struct or target.is_union) and target.object_id in all_types:
                graph[cls_id].append(target.object_id)

    # Run Tarjan's SCC algorithm
    sccs = tarjan_scc(graph)

    # Map each node to its SCC (only for nodes actually in cycles)
    scc_map = {}
    for scc in sccs:
        # An SCC is a cycle if:
        # 1. It has multiple nodes (mutual recursion), OR
        # 2. It has one node that depends on itself (self-reference)
        is_cycle = len(scc) > 1 or (len(scc) == 1 and list(scc)[0] in graph[list(scc)[0]])

        if is_cycle:
            for node_id in scc:
                scc_map[node_id] = scc
                type_kind = "struct" if all_types[node_id].is_struct else "union"
                log.debug(f"{type_kind.capitalize()} {all_types[node_id].full_name} is in SCC of size {len(scc)}")

    return scc_map


def validate_cycles_within_modules(packages: List[ModelPackage], scc_map: Dict[int, Set[int]]) -> None:
    """
    Validate that all cycles are contained within a single module.

    Cross-module circular dependencies are not supported as they would
    require module reopening which is not universally supported in IDL.

    Args:
        packages: List of model packages
        scc_map: Dict mapping object_id to its SCC

    Raises:
        ValueError: If a cycle crosses module boundaries
    """
    all_types = {}
    for pkg in flatten_packages(packages):
        for cls in pkg.classes:
            if cls.is_struct or cls.is_union:
                all_types[cls.object_id] = cls

    # Check each SCC
    processed_sccs = set()
    for cls_id, scc in scc_map.items():
        scc_tuple = tuple(sorted(scc))  # Make hashable for deduplication
        if scc_tuple in processed_sccs:
            continue
        processed_sccs.add(scc_tuple)

        # Get all classes in this SCC
        scc_classes = [all_types[oid] for oid in scc]

        # Check if all classes share the same namespace (same module)
        first_namespace = scc_classes[0].namespace
        for cls in scc_classes[1:]:
            if cls.namespace != first_namespace:
                # Build error message with all classes in the cycle
                cycle_names = " ↔ ".join([c.full_name for c in scc_classes])
                raise ValueError(
                    f"Cross-module circular dependency detected: {cycle_names}. "
                    f"Circular dependencies are only supported within the same module."
                )


def detect_types_needing_forward_declarations(
    packages: List[ModelPackage],
) -> Tuple[Set[int], Dict[int, Set[int]]]:
    """
    Detect structs and unions that need forward declarations due to circular dependencies.

    This includes:
    - Self-referential types (A contains sequence<A>)
    - Mutually recursive types in the same module (A refs B, B refs A)
    - Multiple self-referential types in the same module
    - Struct ↔ Union circular dependencies

    Args:
        packages: List of model packages to analyze

    Returns:
        Tuple of:
        - Set of object_ids needing forward declarations
        - Dict mapping object_id to its SCC (for cycle detection in sorting)

    Raises:
        ValueError: If cross-module circular dependencies are detected
    """
    scc_map = find_type_cycles(packages)

    # Validate all cycles are within modules
    validate_cycles_within_modules(packages, scc_map)

    # All types in any SCC need forward declarations
    needs_forward_decl = set(scc_map.keys())

    if needs_forward_decl:
        all_types = {}
        for pkg in flatten_packages(packages):
            for cls in pkg.classes:
                if cls.is_struct or cls.is_union:
                    all_types[cls.object_id] = cls

        log.info(
            f"Found {len(needs_forward_decl)} type(s) requiring forward declarations: "
            f"{', '.join([all_types[oid].full_name for oid in sorted(needs_forward_decl)])}"
        )

    return needs_forward_decl, scc_map
