from typing import List

from eaidl.model import ModelClass, ModelPackage, ModelPackageInfo
from eaidl.diagram import PackageDiagramGenerator


# Helper function to create dummy ModelClass objects for testing
def create_dummy_class(object_id: int, name: str, depends_on: List[int] = None) -> ModelClass:
    if depends_on is None:
        depends_on = []
    return ModelClass(object_id=object_id, name=name, depends_on=depends_on)


# Helper function to create dummy ModelPackage objects for testing
def create_dummy_package(
    package_id: int,
    object_id: int,
    name: str,
    classes: List[ModelClass] = None,
    packages: List[ModelPackage] = None,
    parent: ModelPackage = None,
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
        parent=parent,
        info=ModelPackageInfo(),
    )


# Dummy get_all_depends_on and get_all_class_id for diagram tests
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


class TestPackageDiagramGenerator:
    def test_empty_packages(self):
        """Test diagram generation with no packages."""
        generator = PackageDiagramGenerator(
            packages=[],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()
        assert "@startuml" in diagram
        assert "@enduml" in diagram

    def test_single_package_no_classes(self):
        """Test diagram with a single package containing no classes."""
        p1 = create_dummy_package(1, 101, "PackageA")
        generator = PackageDiagramGenerator(
            packages=[p1],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()
        assert "@startuml" in diagram
        assert "@enduml" in diagram
        assert "PackageA" in diagram
        assert "pkg_1" in diagram

    def test_single_package_with_classes(self):
        """Test diagram with a single package containing classes."""
        c1 = create_dummy_class(1, "ClassA")
        c2 = create_dummy_class(2, "ClassB")
        p1 = create_dummy_package(1, 101, "PackageA", classes=[c1, c2])
        generator = PackageDiagramGenerator(
            packages=[p1],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()
        assert "PackageA" in diagram
        assert "<<2 classes>>" in diagram

    def test_multiple_packages_no_dependencies(self):
        """Test diagram with multiple packages but no dependencies."""
        p1 = create_dummy_package(1, 101, "PackageA")
        p2 = create_dummy_package(2, 102, "PackageB")
        generator = PackageDiagramGenerator(
            packages=[p1, p2],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()
        assert "PackageA" in diagram
        assert "PackageB" in diagram
        # Should not have any dependency arrows
        lines = diagram.split("\n")
        dependency_lines = [line for line in lines if "-->" in line and not line.strip().startswith("'")]
        assert len(dependency_lines) == 0

    def test_packages_with_dependencies(self):
        """Test diagram with packages that have dependencies."""
        c1 = create_dummy_class(1, "ClassA")
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])
        p1 = create_dummy_package(1, 101, "PackageA", classes=[c1])
        p2 = create_dummy_package(2, 102, "PackageB", classes=[c2])
        generator = PackageDiagramGenerator(
            packages=[p1, p2],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()
        assert "PackageA" in diagram
        assert "PackageB" in diagram
        # Should have dependency arrow from PackageB to PackageA
        assert "pkg_2 --> pkg_1" in diagram

    def test_nested_packages(self):
        """Test diagram with nested packages."""
        p1 = create_dummy_package(1, 101, "ParentPackage")
        p2 = create_dummy_package(2, 102, "ChildPackage", parent=p1)
        p1.packages = [p2]
        generator = PackageDiagramGenerator(
            packages=[p1, p2],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()
        assert "ParentPackage" in diagram
        assert "ChildPackage" in diagram
        # Check for proper nesting structure
        lines = diagram.split("\n")
        parent_idx = None
        child_idx = None
        for i, line in enumerate(lines):
            if "ParentPackage" in line and "package" in line:
                parent_idx = i
            if "ChildPackage" in line and "package" in line:
                child_idx = i
        assert parent_idx is not None
        assert child_idx is not None
        # Child should appear after parent in the diagram
        assert child_idx > parent_idx

    def test_no_dependency_on_parent_package(self):
        """Test that child packages don't show dependency arrows to parent packages."""
        c1 = create_dummy_class(1, "ClassInParent")
        c2 = create_dummy_class(2, "ClassInChild", depends_on=[1])
        p1 = create_dummy_package(1, 101, "ParentPackage", classes=[c1])
        p2 = create_dummy_package(2, 102, "ChildPackage", classes=[c2], parent=p1)
        p1.packages = [p2]
        generator = PackageDiagramGenerator(
            packages=[p1, p2],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()
        # Should NOT have dependency arrow from child to parent (it's implicit in containment)
        assert "pkg_2 --> pkg_1" not in diagram

    def test_no_dependency_on_descendant_package(self):
        """Test that parent packages don't show dependency arrows to descendant packages."""
        c1 = create_dummy_class(1, "ClassInChild")
        c2 = create_dummy_class(2, "ClassInParent", depends_on=[1])
        p1 = create_dummy_package(1, 101, "ParentPackage", classes=[c2])
        p2 = create_dummy_package(2, 102, "ChildPackage", classes=[c1], parent=p1)
        p1.packages = [p2]
        generator = PackageDiagramGenerator(
            packages=[p1, p2],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()
        # Should NOT have dependency arrow from parent to child (it's implicit in containment)
        assert "pkg_1 --> pkg_2" not in diagram

    def test_max_depth_limit(self):
        """Test max_depth parameter limits nesting levels."""
        p1 = create_dummy_package(1, 101, "Level0")
        p2 = create_dummy_package(2, 102, "Level1", parent=p1)
        p3 = create_dummy_package(3, 103, "Level2", parent=p2)
        p1.packages = [p2]
        p2.packages = [p3]

        # With max_depth=1, should only show Level0 and Level1
        generator = PackageDiagramGenerator(
            packages=[p1, p2, p3],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
            max_depth=1,
        )
        diagram = generator.generate_plantuml()
        assert "Level0" in diagram
        assert "Level1" in diagram
        assert "Level2" not in diagram

    def test_show_empty_false(self):
        """Test show_empty=False excludes packages with no classes."""
        c1 = create_dummy_class(1, "ClassA")
        p1 = create_dummy_package(1, 101, "PackageWithClasses", classes=[c1])
        p2 = create_dummy_package(2, 102, "EmptyPackage", classes=[])
        generator = PackageDiagramGenerator(
            packages=[p1, p2],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
            show_empty=False,
        )
        diagram = generator.generate_plantuml()
        assert "PackageWithClasses" in diagram
        assert "EmptyPackage" not in diagram

    def test_show_empty_true(self):
        """Test show_empty=True includes packages with no classes."""
        c1 = create_dummy_class(1, "ClassA")
        p1 = create_dummy_package(1, 101, "PackageWithClasses", classes=[c1])
        p2 = create_dummy_package(2, 102, "EmptyPackage", classes=[])
        generator = PackageDiagramGenerator(
            packages=[p1, p2],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
            show_empty=True,
        )
        diagram = generator.generate_plantuml()
        assert "PackageWithClasses" in diagram
        assert "EmptyPackage" in diagram

    def test_sanitize_name(self):
        """Test name sanitization for special characters."""
        p1 = create_dummy_package(1, 101, 'Package"With"Quotes')
        generator = PackageDiagramGenerator(
            packages=[p1],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()
        # Quotes should be escaped
        assert 'Package\\"With\\"Quotes' in diagram

    def test_complex_dependency_graph(self):
        """Test complex dependency graph with multiple packages."""
        c1 = create_dummy_class(1, "ClassA")
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])
        c3 = create_dummy_class(3, "ClassC", depends_on=[1])
        c4 = create_dummy_class(4, "ClassD", depends_on=[2, 3])

        p1 = create_dummy_package(1, 101, "PackageA", classes=[c1])
        p2 = create_dummy_package(2, 102, "PackageB", classes=[c2])
        p3 = create_dummy_package(3, 103, "PackageC", classes=[c3])
        p4 = create_dummy_package(4, 104, "PackageD", classes=[c4])

        generator = PackageDiagramGenerator(
            packages=[p1, p2, p3, p4],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )
        diagram = generator.generate_plantuml()

        # Verify all packages are present
        assert "PackageA" in diagram
        assert "PackageB" in diagram
        assert "PackageC" in diagram
        assert "PackageD" in diagram

        # Verify dependencies
        assert "pkg_2 --> pkg_1" in diagram  # B depends on A
        assert "pkg_3 --> pkg_1" in diagram  # C depends on A
        assert "pkg_4 --> pkg_2" in diagram  # D depends on B
        assert "pkg_4 --> pkg_3" in diagram  # D depends on C

    def test_build_dependency_graph(self):
        """Test the dependency graph building method."""
        c1 = create_dummy_class(1, "ClassA")
        c2 = create_dummy_class(2, "ClassB", depends_on=[1])
        p1 = create_dummy_package(1, 101, "PackageA", classes=[c1])
        p2 = create_dummy_package(2, 102, "PackageB", classes=[c2])

        generator = PackageDiagramGenerator(
            packages=[p1, p2],
            get_all_depends_on=dummy_get_all_depends_on,
            get_all_class_id=dummy_get_all_class_id,
        )

        dep_graph = generator.build_dependency_graph()

        # PackageB (id=2) should depend on PackageA (id=1)
        assert 1 in dep_graph[2]
        # PackageA should not depend on anything
        assert len(dep_graph[1]) == 0
