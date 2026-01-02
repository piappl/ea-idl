from eaidl.model import ModelClass, ModelAttribute
from eaidl.sorting import topological_sort_classes


def test_scc_topological_sorting():
    # Nodes (Typedef) -> Node (Union) [HARD]
    # Node (Union) -> Nodes (Typedef) [SOFT]

    nodes_typedef = ModelClass(
        object_id=1,
        name="Nodes",
        is_typedef=True,
        parent_type="sequence<Node>",
        depends_on=[2],  # Hard dependency on Node
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

    # Node should come first because it has in-degree 0 (its incoming edge from Nodes is HARD,
    # but its outgoing edge to Nodes is SOFT and thus ignored in the SCC).
    # Wait, Nodes has in-degree 1 (Hard edge from Node is... no!
    # Node -> Nodes is SOFT. Nodes -> Node is HARD.
    # So Node has in-degree 0 (soft edge from Nodes ignored? No!
    # Logic is: if dep_id in scc and is_soft(cls, dep_id): ignore.
    # src=Node, dep_id=Nodes. is_soft(Node, Nodes) is True. So edge ignored.
    # src=Nodes, dep_id=Node. is_soft(Nodes, Node) is False. So edge KEPT.
    # Result: in_degree(Node) = 0. in_degree(Nodes) = 1.
    # Node pops first. SUCCESS.
    sorted_classes = topological_sort_classes(classes, scc_map)

    assert [c.name for c in sorted_classes] == ["Node", "Nodes"]
