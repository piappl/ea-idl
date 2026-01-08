import pytest
from typing import List

from eaidl.model import ModelClass, ModelPackage, ModelPackageInfo, ModelAttribute
from eaidl.sorting import topological_sort_classes, topological_sort_packages, CircularDependencyError


# Helper function to create dummy ModelClass objects for testing
def create_dummy_class(object_id: int, name: str, depends_on: List[int] = None) -> ModelClass:
    if depends_on is None:
        depends_on = []
    return ModelClass(object_id=object_id, name=name, depends_on=depends_on)


# Helper function to create dummy ModelPackage objects for testing
def create_dummy_package(
    package_id: int, object_id: int, name: str, classes: List[ModelClass] = None, packages: List[ModelPackage] = None
) -> ModelPackage:
    if classes is None:
        classes = []
    if packages is None:
        packages = []
    return ModelPackage(
        package_id=package_id,
        object_id=object_id,
        name=name,
        guid=f"guid-{name}",
        classes=classes,
        packages=packages,
        info=ModelPackageInfo(),
    )


# Dummy get_all_depends_on and get_all_class_id for package sorting tests
def dummy_get_all_depends_on(pkg: ModelPackage) -> List[int]:
    all_deps = set(pkg.depends_on)
    for cls in pkg.classes:
        all_deps.update(cls.depends_on)
    for sub_pkg in pkg.packages:
        all_deps.update(dummy_get_all_depends_on(sub_pkg))
    return sorted(list(all_deps))


def dummy_get_all_class_id(pkg: ModelPackage) -> List[int]:
    all_class_ids = set()
    for cls in pkg.classes:
        all_class_ids.add(cls.object_id)
    for sub_pkg in pkg.packages:
        all_class_ids.update(dummy_get_all_class_id(sub_pkg))
    return sorted(list(all_class_ids))


class TestTopologicalSortClasses:
    def test_empty_list(self):
        assert topological_sort_classes([]) == []

    def test_no_dependencies(self):
        c1 = create_dummy_class(1, "ClassA")
        c2 = create_dummy_class(2, "ClassB")
        c3 = create_dummy_class(3, "ClassC")
        classes = [c3, c1, c2]
        # Expected order should be sorted by object_id if no dependencies
        sorted_classes = topological_sort_classes(classes)
        assert [c.object_id for c in sorted_classes] == [1, 2, 3]

    def test_linear_dependencies(self):
        c1 = create_dummy_class(1, "ClassA")
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])
        c3 = create_dummy_class(3, "ClassC", depends_on=[2])
        classes = [c3, c1, c2]
        sorted_classes = topological_sort_classes(classes)
        assert [c.object_id for c in sorted_classes] == [1, 2, 3]

    def test_complex_dependencies(self):
        c1 = create_dummy_class(1, "ClassA")
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])
        c3 = create_dummy_class(3, "ClassC", depends_on=[1])
        c4 = create_dummy_class(4, "ClassD", depends_on=[2, 3])
        c5 = create_dummy_class(5, "ClassE", depends_on=[3])
        classes = [c5, c4, c3, c2, c1]
        sorted_classes = topological_sort_classes(classes)
        # Multiple valid topological sorts exist, but our implementation should be deterministic
        # based on sorting nodes with 0 in-degree by their object_id.
        # Expected: 1, 2, 3, 4, 5 (or 1, 3, 2, 4, 5 or 1, 2, 3, 5, 4 etc.)
        # Let's verify the specific deterministic output of our algorithm
        expected_order_ids = [1, 2, 3, 4, 5]
        actual_order_ids = [c.object_id for c in sorted_classes]
        assert actual_order_ids == expected_order_ids

    def test_circular_dependency(self):
        c1 = create_dummy_class(1, "ClassA", depends_on=[2])
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])
        classes = [c1, c2]
        with pytest.raises(CircularDependencyError) as excinfo:
            topological_sort_classes(classes)
        error_msg = str(excinfo.value)
        # Check that both classes are mentioned in the error
        assert "Circular dependency detected in classes:" in error_msg
        assert "ClassA" in error_msg
        assert "ClassB" in error_msg
        # Check for the improved formatting
        assert "Example cycle path:" in error_msg or "All classes in cycle" in error_msg

    def test_circular_dependency_with_other_classes(self):
        c1 = create_dummy_class(1, "ClassA", depends_on=[2])
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])
        c3 = create_dummy_class(3, "ClassC", depends_on=[1])
        c4 = create_dummy_class(4, "ClassD")
        classes = [c1, c2, c3, c4]
        with pytest.raises(CircularDependencyError) as excinfo:
            topological_sort_classes(classes)
        error_msg = str(excinfo.value)
        # The exact message might vary based on which nodes are left in the cycle,
        # but it should indicate a circular dependency and include all involved classes.
        # In this specific case, C3 depends on C1, which is part of the C1-C2 cycle,
        # so C3 also becomes part of the detected cycle.
        assert "Circular dependency detected in classes:" in error_msg
        assert "ClassA" in error_msg
        assert "ClassB" in error_msg
        assert "ClassC" in error_msg
        # ClassD should be sorted successfully
        assert "ClassD" not in error_msg or "All classes in cycle (3)" in error_msg

    def test_dependencies_outside_list_are_ignored(self):
        c1 = create_dummy_class(1, "ClassA", depends_on=[99])  # 99 is not in the list
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])
        classes = [c2, c1]
        sorted_classes = topological_sort_classes(classes)
        assert [c.object_id for c in sorted_classes] == [1, 2]

    def test_typedef_sequence_circular_dependency_allowed(self):
        """Test that circular dependency via typedef sequence<> is allowed in topological sort."""
        # Create a struct Node that depends on typedef Children
        node_struct = ModelClass(
            name="Node",
            object_id=1001,
            is_struct=True,
            depends_on=[1002],  # Depends on Children typedef
            attributes=[
                ModelAttribute(
                    name="other_children",
                    type="Children",
                    is_collection=False,
                    attribute_id=1,
                    guid="guid1",
                    alias="other_children",
                )
            ],
        )

        # Create a typedef Children = sequence<Node> that depends on Node
        children_typedef = ModelClass(
            name="Children",
            object_id=1002,
            is_typedef=True,
            depends_on=[1001],  # Depends on Node
            parent_type="sequence<Node>",  # This makes it a soft dependency
        )

        # Create SCC map showing they're in the same cycle
        scc_map = {
            1001: {1001, 1002},
            1002: {1001, 1002},
        }

        # This should NOT raise because typedef with sequence<> is a soft dependency
        classes = [node_struct, children_typedef]
        sorted_classes = topological_sort_classes(classes, scc_map=scc_map)

        # Should successfully sort (order depends on which breaks the soft dependency)
        assert len(sorted_classes) == 2
        # Both classes should be in the result
        sorted_ids = {c.object_id for c in sorted_classes}
        assert sorted_ids == {1001, 1002}


class TestTopologicalSortPackages:
    def test_empty_list(self):
        assert topological_sort_packages([], dummy_get_all_depends_on, dummy_get_all_class_id) == []

    def test_no_dependencies(self):
        p1 = create_dummy_package(1, 101, "PackageA")
        p2 = create_dummy_package(2, 102, "PackageB")
        p3 = create_dummy_package(3, 103, "PackageC")
        packages = [p3, p1, p2]
        sorted_packages = topological_sort_packages(packages, dummy_get_all_depends_on, dummy_get_all_class_id)
        assert [p.package_id for p in sorted_packages] == [1, 2, 3]

    def test_linear_dependencies(self):
        c1 = create_dummy_class(1, "ClassA")
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])

        p1 = create_dummy_package(1, 101, "PackageA", classes=[c1])
        p2 = create_dummy_package(2, 102, "PackageB", classes=[c2])  # P2 depends on P1 because C2 depends on C1

        packages = [p2, p1]
        sorted_packages = topological_sort_packages(packages, dummy_get_all_depends_on, dummy_get_all_class_id)
        assert [p.package_id for p in sorted_packages] == [1, 2]

    def test_complex_dependencies(self):
        c1 = create_dummy_class(1, "ClassA")
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])
        c3 = create_dummy_class(3, "ClassC", depends_on=[1])
        c4 = create_dummy_class(4, "ClassD", depends_on=[2, 3])

        p1 = create_dummy_package(1, 101, "PackageA", classes=[c1])
        p2 = create_dummy_package(2, 102, "PackageB", classes=[c2])  # P2 depends on P1
        p3 = create_dummy_package(3, 103, "PackageC", classes=[c3])  # P3 depends on P1
        p4 = create_dummy_package(4, 104, "PackageD", classes=[c4])  # P4 depends on P2 and P3

        packages = [p4, p3, p2, p1]
        sorted_packages = topological_sort_packages(packages, dummy_get_all_depends_on, dummy_get_all_class_id)
        expected_order_ids = [1, 2, 3, 4]
        actual_order_ids = [p.package_id for p in sorted_packages]
        assert actual_order_ids == expected_order_ids

    def test_circular_dependency(self):
        c1 = create_dummy_class(1, "ClassA", depends_on=[2])
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])

        _p1 = create_dummy_package(1, 101, "PackageA", classes=[c1])
        _p2 = create_dummy_package(2, 102, "PackageB", classes=[c2])

        # If P1 contains C1 which depends on C2 (in P2), and P2 contains C2 which depends on C1 (in P1)
        # This creates a package-level circular dependency.
        # For this test, we need to ensure that the dummy_get_all_depends_on and dummy_get_all_class_id
        # correctly reflect these cross-package dependencies.
        # Let's simulate a direct package dependency for simplicity in this test.
        # A more realistic scenario would involve classes within packages creating the cycle.

        # To create a package circular dependency, let's make P1 depend on P2, and P2 depend on P1.
        # This is done by having a class in P1 depend on a class in P2, and vice-versa.
        # For the purpose of this test, let's assume C1 is in P1 and C2 is in P2.
        # If C1 depends on C2, then P1 depends on P2.
        # If C2 depends on C1, then P2 depends on P1.

        # Redefine classes to be in specific packages
        c_in_p1 = create_dummy_class(1, "ClassInP1", depends_on=[2])
        c_in_p2 = create_dummy_class(2, "ClassInP2", depends_on=[1])

        p1_circular = create_dummy_package(1, 101, "PackageA", classes=[c_in_p1])
        p2_circular = create_dummy_package(2, 102, "PackageB", classes=[c_in_p2])

        packages = [p1_circular, p2_circular]

        with pytest.raises(CircularDependencyError) as excinfo:
            topological_sort_packages(packages, dummy_get_all_depends_on, dummy_get_all_class_id)
        error_msg = str(excinfo.value)
        assert "Circular dependency detected in packages:" in error_msg
        assert "PackageA" in error_msg
        assert "PackageB" in error_msg
        assert "Inter-package dependencies (showing which classes cause the cycle):" in error_msg
        # Should show the actual class names
        assert "ClassInP1" in error_msg or "ClassInP2" in error_msg
