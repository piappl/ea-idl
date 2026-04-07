from eaidl.model import ModelClass, ModelAttribute
from eaidl.sorting import topological_sort_classes


def test_scc_topological_sorting():
    # Nodes (Typedef sequence<>) -> Node (Union) [SOFT - typedef with sequence<>]
    # Node (Union) -> Nodes (Typedef) [SOFT - union member is a collection]

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
        attributes=[ModelAttribute(name="val", type="Nodes", is_collection=True, attribute_id=1, guid="g", alias="v")],
        depends_on=[1],  # Soft dependency on Nodes (collection member)
    )

    scc_map = {1: {1, 2}, 2: {1, 2}}

    classes = [nodes_typedef, node_union]

    # Both edges are SOFT and within the same SCC, so they're both ignored:
    # src=Nodes, dep_id=Node. is_soft(Nodes, Node) is True (typedef sequence<>). Edge ignored.
    # src=Node, dep_id=Nodes. is_soft(Node, Nodes) is True (collection member). Edge ignored.
    # Result: Both have in-degree 0, so sorting falls back to object_id order.
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


def test_union_non_collection_member_is_hard_dependency():
    """Non-collection union member is a hard dependency, not soft.

    Union members follow the same rules as struct members: only collection
    types (sequence<>, map<>) are soft.  A direct (non-collection) member
    must be fully defined before the union → hard dependency.
    """
    detail = ModelClass(
        object_id=1,
        name="Detail",
        attributes=[],
        depends_on=[],
    )

    choice = ModelClass(
        object_id=2,
        name="Choice",
        is_union=True,
        attributes=[
            ModelAttribute(name="d", type="Detail", is_collection=False, attribute_id=1, guid="g", alias="d"),
        ],
        depends_on=[1],  # Hard — non-collection member
    )

    classes = [choice, detail]
    sorted_classes = topological_sort_classes(classes, scc_map={})

    # Detail must come before Choice because it's a hard dependency.
    assert [c.name for c in sorted_classes] == ["Detail", "Choice"]


def test_union_non_collection_member_in_scc_is_hard():
    """Within an SCC, a non-collection union member remains hard.

    Even when two classes form a cycle (same SCC), a non-collection union
    member is NOT treated as soft — the cycle cannot be broken at that edge.
    """
    alpha = ModelClass(
        object_id=1,
        name="Alpha",
        attributes=[
            ModelAttribute(name="b", type="Beta", is_collection=True, attribute_id=1, guid="g1", alias="b"),
        ],
        depends_on=[2],  # Soft — collection member
    )

    beta = ModelClass(
        object_id=2,
        name="Beta",
        is_union=True,
        attributes=[
            ModelAttribute(name="a", type="Alpha", is_collection=False, attribute_id=2, guid="g2", alias="a"),
        ],
        depends_on=[1],  # Hard — non-collection union member
    )

    scc_map = {1: {1, 2}, 2: {1, 2}}
    classes = [beta, alpha]
    sorted_classes = topological_sort_classes(classes, scc_map)

    # Alpha→Beta is soft (collection), so that edge is ignored within the SCC.
    # Beta→Alpha is hard (non-collection union member), so it is kept.
    # Alpha must come first.
    assert [c.name for c in sorted_classes] == ["Alpha", "Beta"]
