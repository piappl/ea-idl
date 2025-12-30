"""Tests for recursive struct detection and forward declarations."""

import pytest
from eaidl.model import ModelClass, ModelAttribute, ModelPackage
from eaidl.recursion import (
    tarjan_scc,
    find_struct_cycles,
    validate_cycles_within_modules,
    detect_structs_needing_forward_declarations,
)
from eaidl.validation.struct import recursive_struct_uses_sequence
from eaidl.config import Configuration


def test_tarjan_scc_simple_cycle():
    """Test Tarjan's SCC algorithm with a simple cycle."""
    # Graph: 1 -> 2 -> 3 -> 1 (cycle)
    graph = {
        1: [2],
        2: [3],
        3: [1],
    }

    sccs = tarjan_scc(graph)

    # Should find one SCC with all three nodes
    assert len(sccs) == 1
    assert sccs[0] == {1, 2, 3}


def test_tarjan_scc_self_loop():
    """Test Tarjan's SCC algorithm with a self-loop."""
    # Graph: 1 -> 1 (self-loop)
    graph = {
        1: [1],
        2: [],
    }

    sccs = tarjan_scc(graph)

    # Should find one SCC with node 1, and one with node 2
    scc_sizes = sorted([len(scc) for scc in sccs])
    assert scc_sizes == [1, 1]

    # Node 1 should be in its own SCC
    node1_scc = [scc for scc in sccs if 1 in scc][0]
    assert node1_scc == {1}


def test_tarjan_scc_no_cycles():
    """Test Tarjan's SCC algorithm with no cycles."""
    # Graph: 1 -> 2, 2 -> 3 (DAG)
    graph = {
        1: [2],
        2: [3],
        3: [],
    }

    sccs = tarjan_scc(graph)

    # Should find three SCCs, each with one node
    assert len(sccs) == 3
    for scc in sccs:
        assert len(scc) == 1


def test_detect_self_referential_struct():
    """Test detection of self-referential struct via sequence."""
    node = ModelClass(
        name="Node",
        object_id=100,
        is_struct=True,
        namespace=["root", "tree"],
        attributes=[
            ModelAttribute(
                name="value",
                type="long",
                attribute_id=1,
                guid="guid1",
                alias="value",
            ),
            ModelAttribute(
                name="children",
                type="Node",
                is_collection=True,
                namespace=["root", "tree"],
                attribute_id=2,
                guid="guid2",
                alias="children",
            ),
        ],
    )

    package = ModelPackage(package_id=1, object_id=1, name="root", guid="pkg1", classes=[node])

    scc_map = find_struct_cycles([package])

    # Should detect the self-reference
    assert 100 in scc_map
    assert scc_map[100] == {100}


def test_detect_mutual_recursion_same_module():
    """Test detection of mutually recursive structs in the same module."""
    struct_a = ModelClass(
        name="A",
        object_id=200,
        is_struct=True,
        namespace=["root", "data"],
        attributes=[
            ModelAttribute(
                name="b_list",
                type="B",
                is_collection=True,
                namespace=["root", "data"],
                attribute_id=1,
                guid="guid1",
                alias="b_list",
            )
        ],
    )

    struct_b = ModelClass(
        name="B",
        object_id=201,
        is_struct=True,
        namespace=["root", "data"],
        attributes=[
            ModelAttribute(
                name="a_list",
                type="A",
                is_collection=True,
                namespace=["root", "data"],
                attribute_id=2,
                guid="guid2",
                alias="a_list",
            )
        ],
    )

    package = ModelPackage(package_id=1, object_id=1, name="root", guid="pkg1", classes=[struct_a, struct_b])

    scc_map = find_struct_cycles([package])

    # Should detect mutual recursion
    assert 200 in scc_map
    assert 201 in scc_map
    assert scc_map[200] == {200, 201}
    assert scc_map[201] == {200, 201}


def test_detect_multiple_self_referential_structs_same_module():
    """Test detection of multiple self-referential structs in the same module."""
    struct_a = ModelClass(
        name="A",
        object_id=300,
        is_struct=True,
        namespace=["root", "data"],
        attributes=[
            ModelAttribute(
                name="a_list",
                type="A",
                is_collection=True,
                namespace=["root", "data"],
                attribute_id=1,
                guid="guid1",
                alias="a_list",
            )
        ],
    )

    struct_b = ModelClass(
        name="B",
        object_id=301,
        is_struct=True,
        namespace=["root", "data"],
        attributes=[
            ModelAttribute(
                name="b_list",
                type="B",
                is_collection=True,
                namespace=["root", "data"],
                attribute_id=2,
                guid="guid2",
                alias="b_list",
            )
        ],
    )

    package = ModelPackage(package_id=1, object_id=1, name="root", guid="pkg1", classes=[struct_a, struct_b])

    scc_map = find_struct_cycles([package])

    # Should detect both self-references
    assert 300 in scc_map
    assert 301 in scc_map
    # Each should be in its own SCC (no mutual recursion)
    assert scc_map[300] == {300}
    assert scc_map[301] == {301}


def test_non_recursive_struct_not_detected():
    """Test that non-recursive structs are not flagged."""
    simple = ModelClass(
        name="Simple",
        object_id=400,
        is_struct=True,
        namespace=["root"],
        attributes=[
            ModelAttribute(
                name="value",
                type="long",
                attribute_id=1,
                guid="guid1",
                alias="value",
            )
        ],
    )

    package = ModelPackage(package_id=1, object_id=1, name="root", guid="pkg1", classes=[simple])

    scc_map = find_struct_cycles([package])

    # Should not detect any cycles
    assert 400 not in scc_map


def test_direct_reference_not_detected():
    """Test that direct (non-sequence) references don't create cycles."""
    struct_a = ModelClass(
        name="A",
        object_id=500,
        is_struct=True,
        namespace=["root"],
        attributes=[
            ModelAttribute(
                name="next",
                type="A",
                is_collection=False,  # Direct reference, not a sequence
                namespace=["root"],
                attribute_id=1,
                guid="guid1",
                alias="next",
            )
        ],
    )

    package = ModelPackage(package_id=1, object_id=1, name="root", guid="pkg1", classes=[struct_a])

    scc_map = find_struct_cycles([package])

    # Should NOT detect cycle (only sequences are considered)
    assert 500 not in scc_map


def test_validate_cross_module_cycle_rejected():
    """Test that cross-module circular dependencies are rejected."""
    struct_a = ModelClass(
        name="A",
        object_id=600,
        is_struct=True,
        namespace=["root", "module1"],
        attributes=[
            ModelAttribute(
                name="b_ref",
                type="B",
                is_collection=True,
                namespace=["root", "module2"],  # Different namespace!
                attribute_id=1,
                guid="guid1",
                alias="b_ref",
            )
        ],
    )

    struct_b = ModelClass(
        name="B",
        object_id=601,
        is_struct=True,
        namespace=["root", "module2"],
        attributes=[
            ModelAttribute(
                name="a_ref",
                type="A",
                is_collection=True,
                namespace=["root", "module1"],  # Different namespace!
                attribute_id=2,
                guid="guid2",
                alias="a_ref",
            )
        ],
    )

    package = ModelPackage(package_id=1, object_id=1, name="root", guid="pkg1", classes=[struct_a, struct_b])

    scc_map = find_struct_cycles([package])

    # Should detect the cycle
    assert 600 in scc_map
    assert 601 in scc_map

    # But validation should reject it due to cross-module
    with pytest.raises(ValueError, match="Cross-module circular dependency"):
        validate_cycles_within_modules([package], scc_map)


def test_detect_structs_needing_forward_declarations_integration():
    """Test the full integration of detection."""
    node = ModelClass(
        name="Node",
        object_id=700,
        is_struct=True,
        namespace=["root", "tree"],
        attributes=[
            ModelAttribute(
                name="children",
                type="Node",
                is_collection=True,
                namespace=["root", "tree"],
                attribute_id=1,
                guid="guid1",
                alias="children",
            )
        ],
    )

    package = ModelPackage(package_id=1, object_id=1, name="root", guid="pkg1", classes=[node])

    needs_forward_decl, scc_map = detect_structs_needing_forward_declarations([package])

    # Should detect that Node needs forward declaration
    assert 700 in needs_forward_decl
    assert 700 in scc_map


def test_validator_rejects_direct_self_reference():
    """Test that validator rejects non-sequence recursive reference."""
    config = Configuration(
        allow_recursive_structs=True,
        validators_fail=["struct.recursive_struct_uses_sequence"],
    )

    bad_node = ModelClass(
        name="Node",
        object_id=800,
        is_struct=True,
        namespace=["root"],
        attributes=[
            ModelAttribute(
                name="next",
                type="Node",
                is_collection=False,  # NOT a sequence - illegal!
                namespace=["root"],
                attribute_id=1,
                guid="guid1",
                alias="next",
            )
        ],
    )

    with pytest.raises(ValueError, match="must be a sequence"):
        recursive_struct_uses_sequence(config, cls=bad_node)


def test_validator_allows_sequence_self_reference():
    """Test that validator allows sequence recursive reference."""
    config = Configuration(
        allow_recursive_structs=True,
        validators_fail=["struct.recursive_struct_uses_sequence"],
    )

    good_node = ModelClass(
        name="Node",
        object_id=900,
        is_struct=True,
        namespace=["root"],
        attributes=[
            ModelAttribute(
                name="children",
                type="Node",
                is_collection=True,  # Sequence - legal!
                namespace=["root"],
                attribute_id=1,
                guid="guid1",
                alias="children",
            )
        ],
    )

    # Should not raise
    recursive_struct_uses_sequence(config, cls=good_node)


def test_validator_skips_when_disabled():
    """Test that validator skips when recursion support is disabled."""
    config = Configuration(allow_recursive_structs=False)

    # Even with illegal direct reference, should not raise when disabled
    bad_node = ModelClass(
        name="Node",
        object_id=1000,
        is_struct=True,
        namespace=["root"],
        attributes=[
            ModelAttribute(
                name="next",
                type="Node",
                is_collection=False,
                namespace=["root"],
                attribute_id=1,
                guid="guid1",
                alias="next",
            )
        ],
    )

    # Should not raise (validator is disabled)
    recursive_struct_uses_sequence(config, cls=bad_node)


def test_validator_only_checks_self_references():
    """Test that validator only checks self-references, not other types."""
    config = Configuration(
        allow_recursive_structs=True,
        validators_fail=["struct.recursive_struct_uses_sequence"],
    )

    # Struct with reference to OTHER type (not self-reference)
    struct_a = ModelClass(
        name="A",
        object_id=1100,
        is_struct=True,
        namespace=["root"],
        attributes=[
            ModelAttribute(
                name="b_ref",
                type="B",  # Different type
                is_collection=False,  # Not a sequence
                namespace=["root"],
                attribute_id=1,
                guid="guid1",
                alias="b_ref",
            )
        ],
    )

    # Should not raise (not a self-reference)
    recursive_struct_uses_sequence(config, cls=struct_a)
