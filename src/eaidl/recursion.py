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


def find_type_cycles(packages: List[ModelPackage], check_non_collection_cycles: bool = False) -> Dict[int, Set[int]]:
    """
    Find all strongly connected components (cycles) in struct and union dependencies.

    IDL allows recursive types if at least one edge in each cycle uses a sequence<>.
    This prevents infinite size and allows forward declarations.

    Rules:
    - Self-reference (A → A) MUST use sequence
    - Mutual recursion (A → B → A) can have direct refs if at least one edge uses sequence

    This handles:
    - Struct ↔ Struct cycles
    - Union ↔ Union cycles
    - Struct ↔ Union cycles

    Args:
        packages: List of model packages to analyze
        check_non_collection_cycles: If True, raises ValueError for cycles with no sequences

    Returns:
        Dict mapping each struct/union object_id in a cycle to its SCC
        (set of object_ids in the same cycle, including itself)

    Raises:
        ValueError: If check_non_collection_cycles=True and a cycle has no sequence edges
    """
    # Build dependency graphs
    all_deps_graph = {}  # All dependencies (collection and non-collection)
    sequence_deps_graph = {}  # Only dependencies through sequences
    all_types = {}  # object_id -> ModelClass

    # First pass: collect all structs and unions and initialize graphs
    for pkg in flatten_packages(packages):
        for cls in pkg.classes:
            if cls.is_struct or cls.is_union:
                all_types[cls.object_id] = cls
                all_deps_graph[cls.object_id] = []
                sequence_deps_graph[cls.object_id] = []

    # Second pass: build dependency edges
    for cls_id, cls in all_types.items():
        for attr in cls.attributes:
            # Find target type by name and namespace
            target = find_class(packages, lambda c: c.name == attr.type and c.namespace == attr.namespace)

            if target and (target.is_struct or target.is_union) and target.object_id in all_types:
                # Track in all_deps_graph
                all_deps_graph[cls_id].append((target.object_id, attr.name, attr.is_collection))

                # For sequence_deps_graph: only track sequences (for structs) or all members (for unions)
                if cls.is_union or attr.is_collection:
                    sequence_deps_graph[cls_id].append(target.object_id)

    # Find ALL cycles using the full dependency graph
    # Convert all_deps_graph to simple format for Tarjan
    simple_all_graph = {cls_id: [dep[0] for dep in deps] for cls_id, deps in all_deps_graph.items()}
    all_sccs = tarjan_scc(simple_all_graph)

    # Find cycles and check if they have at least one sequence edge
    scc_map = {}
    for scc in all_sccs:
        # Check if this is actually a cycle
        is_cycle = len(scc) > 1 or (len(scc) == 1 and list(scc)[0] in simple_all_graph[list(scc)[0]])

        if not is_cycle:
            continue  # Not a cycle, skip

        # Check if cycle has at least one sequence edge
        has_sequence = False
        missing_sequence_edges = []

        for cls_id in scc:
            cls = all_types[cls_id]
            for target_id, attr_name, is_collection in all_deps_graph[cls_id]:
                if target_id in scc:  # Dependency within this SCC
                    if cls.is_union or is_collection:
                        has_sequence = True
                    else:
                        # Non-sequence edge in cycle
                        target = all_types[target_id]
                        missing_sequence_edges.append((cls.full_name, attr_name, target.full_name))

        if has_sequence:
            # Valid cycle with at least one sequence - mark all types for forward declaration
            for node_id in scc:
                scc_map[node_id] = scc
                type_kind = "struct" if all_types[node_id].is_struct else "union"
                log.debug(f"{type_kind.capitalize()} {all_types[node_id].full_name} is in SCC of size {len(scc)}")
        elif check_non_collection_cycles:
            # Cycle with NO sequences - this is an error if checking is enabled
            cycle_types = [all_types[cls_id].full_name for cls_id in scc]
            raise ValueError(
                f"Circular dependency with no sequence edges detected.\n"
                f"IDL requires at least one sequence<> in each cycle to break recursion.\n"
                f"Cycle: {' ↔ '.join(cycle_types)}\n"
                f"Non-sequence edges:\n  "
                + "\n  ".join([f"{src}.{attr} → {tgt}" for src, attr, tgt in missing_sequence_edges])
                + "\n"
                "To fix: Change at least one attribute in the cycle to use IsCollection=true."
            )

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
    scc_map = find_type_cycles(packages, check_non_collection_cycles=True)

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
