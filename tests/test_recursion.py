"""Tests for recursive struct detection and forward declarations."""

import pytest
from eaidl.model import ModelClass, ModelAttribute, ModelPackage
from eaidl.recursion import (
    tarjan_scc,
    find_type_cycles,
    validate_cycles_within_modules,
    detect_types_needing_forward_declarations,
)
from eaidl.validation.struct import recursive_type_uses_sequence
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

    scc_map = find_type_cycles([package])

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

    scc_map = find_type_cycles([package])

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

    scc_map = find_type_cycles([package])

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

    scc_map = find_type_cycles([package])

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

    scc_map = find_type_cycles([package])

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

    scc_map = find_type_cycles([package])

    # Should detect the cycle
    assert 600 in scc_map
    assert 601 in scc_map

    # But validation should reject it due to cross-module
    with pytest.raises(ValueError, match="Cross-module circular dependency"):
        validate_cycles_within_modules([package], scc_map)


def test_detect_types_needing_forward_declarations_integration():
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

    needs_forward_decl, scc_map = detect_types_needing_forward_declarations([package])

    # Should detect that Node needs forward declaration
    assert 700 in needs_forward_decl
    assert 700 in scc_map


def test_validator_rejects_direct_self_reference():
    """Test that validator rejects non-sequence recursive reference."""
    config = Configuration(
        allow_recursive_structs=True,
        validators_fail=["struct.recursive_type_uses_sequence"],
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
        recursive_type_uses_sequence(config, cls=bad_node)


def test_validator_allows_sequence_self_reference():
    """Test that validator allows sequence recursive reference."""
    config = Configuration(
        allow_recursive_structs=True,
        validators_fail=["struct.recursive_type_uses_sequence"],
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
    recursive_type_uses_sequence(config, cls=good_node)


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
    recursive_type_uses_sequence(config, cls=bad_node)


def test_validator_only_checks_self_references():
    """Test that validator only checks self-references, not other types."""
    config = Configuration(
        allow_recursive_structs=True,
        validators_fail=["struct.recursive_type_uses_sequence"],
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
    recursive_type_uses_sequence(config, cls=struct_a)


def test_union_struct_circular_dependency():
    """Test that union ↔ struct circular dependencies are detected and allowed with sequences."""
    # Create a union that has struct members
    union_expr = ModelClass(
        name="Expression",
        object_id=2001,
        is_union=True,
        stereotypes=["union"],
        namespace=["cql"],
        attributes=[
            ModelAttribute(
                name="and_expr",
                type="AndExpression",
                is_collection=True,  # sequence<AndExpression>
                namespace=["cql"],
                attribute_id=1,
                guid="guid1",
                alias="and_expr",
            ),
            ModelAttribute(
                name="or_expr",
                type="OrExpression",
                is_collection=True,  # sequence<OrExpression>
                namespace=["cql"],
                attribute_id=2,
                guid="guid2",
                alias="or_expr",
            ),
        ],
    )
    # Create structs that have union members
    struct_and = ModelClass(
        name="AndExpression",
        object_id=2002,
        is_struct=True,
        stereotypes=["struct"],
        namespace=["cql"],
        attributes=[
            ModelAttribute(
                name="args",
                type="Expression",
                is_collection=True,  # sequence<Expression>
                namespace=["cql"],
                attribute_id=3,
                guid="guid3",
                alias="args",
            )
        ],
    )
    struct_or = ModelClass(
        name="OrExpression",
        object_id=2003,
        is_struct=True,
        stereotypes=["struct"],
        namespace=["cql"],
        attributes=[
            ModelAttribute(
                name="args",
                type="Expression",
                is_collection=True,  # sequence<Expression>
                namespace=["cql"],
                attribute_id=4,
                guid="guid4",
                alias="args",
            )
        ],
    )

    # Create package with all three
    package = ModelPackage(
        name="cql",
        package_id=200,
        object_id=200,
        guid="cql-guid",
    )
    package.classes = [union_expr, struct_and, struct_or]
    package.namespace = ["cql"]

    # This should detect the cycle
    needs_forward_decl, scc_map = detect_types_needing_forward_declarations([package])

    # All three should need forward declarations (they're in a cycle)
    assert len(needs_forward_decl) == 3
    assert union_expr.object_id in needs_forward_decl
    assert struct_and.object_id in needs_forward_decl
    assert struct_or.object_id in needs_forward_decl

    # All three should be in the same SCC
    assert union_expr.object_id in scc_map
    assert struct_and.object_id in scc_map
    assert struct_or.object_id in scc_map
    assert scc_map[union_expr.object_id] == scc_map[struct_and.object_id]
    assert scc_map[struct_and.object_id] == scc_map[struct_or.object_id]


def test_non_collection_circular_dependency_rejected():
    """Test that circular dependencies with NO sequence edges are rejected with helpful error."""
    # Create struct → struct cycle with NO sequences (all direct references)
    struct_a = ModelClass(
        name="StructA",
        object_id=3001,
        is_struct=True,
        stereotypes=["struct"],
        namespace=["test"],
        attributes=[
            ModelAttribute(
                name="b_ref",
                type="StructB",
                is_collection=False,  # Direct reference - no sequence
                namespace=["test"],
                attribute_id=1,
                guid="guid1",
                alias="b_ref",
            )
        ],
    )
    struct_b = ModelClass(
        name="StructB",
        object_id=3002,
        is_struct=True,
        stereotypes=["struct"],
        namespace=["test"],
        attributes=[
            ModelAttribute(
                name="a_ref",
                type="StructA",
                is_collection=False,  # Direct reference - no sequence
                namespace=["test"],
                attribute_id=2,
                guid="guid2",
                alias="a_ref",
            )
        ],
    )

    package = ModelPackage(
        name="test",
        package_id=300,
        object_id=300,
        guid="test-guid",
    )
    package.classes = [struct_a, struct_b]
    package.namespace = ["test"]

    # This should raise ValueError with helpful message when check is enabled
    with pytest.raises(ValueError) as exc_info:
        find_type_cycles([package], check_non_collection_cycles=True)

    error_msg = str(exc_info.value)
    assert "Circular dependency with no sequence edges" in error_msg
    assert "at least one sequence" in error_msg
    assert "IsCollection" in error_msg
    # Check that both structs are mentioned in the cycle
    assert "StructA" in error_msg
    assert "StructB" in error_msg


def test_mutual_recursion_with_one_sequence_allowed():
    """Test that mutual recursion with at least one sequence is allowed."""
    # Create struct → struct cycle where ONE edge uses a sequence
    struct_a = ModelClass(
        name="StructA",
        object_id=4001,
        is_struct=True,
        stereotypes=["struct"],
        namespace=["test"],
        attributes=[
            ModelAttribute(
                name="b_ref",
                type="StructB",
                is_collection=False,  # Direct reference - OK because other edge has sequence
                namespace=["test"],
                attribute_id=1,
                guid="guid1",
                alias="b_ref",
            )
        ],
    )
    struct_b = ModelClass(
        name="StructB",
        object_id=4002,
        is_struct=True,
        stereotypes=["struct"],
        namespace=["test"],
        attributes=[
            ModelAttribute(
                name="a_list",
                type="StructA",
                is_collection=True,  # SEQUENCE - this breaks the cycle!
                namespace=["test"],
                attribute_id=2,
                guid="guid2",
                alias="a_list",
            )
        ],
    )

    package = ModelPackage(
        name="test",
        package_id=400,
        object_id=400,
        guid="test-guid",
    )
    package.classes = [struct_a, struct_b]
    package.namespace = ["test"]

    # This should NOT raise - cycle has a sequence edge
    needs_forward_decl, scc_map = detect_types_needing_forward_declarations([package])

    # Both should need forward declarations (they're in a cycle)
    assert len(needs_forward_decl) == 2
    assert struct_a.object_id in needs_forward_decl
    assert struct_b.object_id in needs_forward_decl

    # Both should be in the same SCC
    assert struct_a.object_id in scc_map
    assert struct_b.object_id in scc_map
    assert scc_map[struct_a.object_id] == scc_map[struct_b.object_id]
