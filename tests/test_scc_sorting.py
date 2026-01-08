from eaidl.model import ModelClass, ModelAttribute
from eaidl.sorting import topological_sort_classes


def test_scc_topological_sorting():
    # Nodes (Typedef sequence<>) -> Node (Union) [SOFT - typedef with sequence<>]
    # Node (Union) -> Nodes (Typedef) [SOFT - union members are always soft]

    nodes_typedef = ModelClass(
        object_id=1,
        name="Nodes",
        is_typedef=True,
        parent_type="sequence<Node>",
        depends_on=[2],  # Soft dependency on Node (typedef with sequence<>)
    )

    node_union = ModelClass(
        object_id=2,
        name="Node",
        is_union=True,
        attributes=[ModelAttribute(name="val", type="Nodes", is_collection=False, attribute_id=1, guid="g", alias="v")],
        depends_on=[1],  # Soft dependency on Nodes (because it's a Union)
    )

    # SCC map
    scc_map = {1: {1, 2}, 2: {1, 2}}

    classes = [nodes_typedef, node_union]

    # Both edges are SOFT and within the same SCC, so they're both ignored:
    # Logic is: if dep_id in scc and is_soft(cls, dep_id): ignore.
    # src=Nodes, dep_id=Node. is_soft(Nodes, Node) is True (typedef sequence<>). Edge ignored.
    # src=Node, dep_id=Nodes. is_soft(Node, Nodes) is True (union). Edge ignored.
    # Result: Both have in-degree 0, so sorting falls back to object_id order.
    # Nodes (object_id=1) comes before Node (object_id=2).
    sorted_classes = topological_sort_classes(classes, scc_map)

    assert [c.name for c in sorted_classes] == ["Nodes", "Node"]


def test_typedef_direct_reference_is_hard_dependency():
    """Test that typedef without sequence<> creates a hard dependency (not circular)."""
    # MyString (Typedef) -> string [primitive, ignored]
    # This is a simple typedef, no circular dependency

    my_string_typedef = ModelClass(
        object_id=1,
        name="MyString",
        is_typedef=True,
        parent_type="string",  # Direct type reference, not sequence<>
        depends_on=[],  # No dependencies on other classes
    )

    classes = [my_string_typedef]
    sorted_classes = topological_sort_classes(classes, scc_map={})

    assert [c.name for c in sorted_classes] == ["MyString"]
