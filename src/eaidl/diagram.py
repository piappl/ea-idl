from typing import List, Dict, Set, Callable, Optional
import logging

from eaidl.model import ModelPackage

log = logging.getLogger(__name__)


class PackageDiagramGenerator:
    """
    Generates package structure diagrams showing containment and dependency relationships.
    """

    def __init__(
        self,
        packages: List[ModelPackage],
        get_all_depends_on: Callable[[ModelPackage], List[int]],
        get_all_class_id: Callable[[ModelPackage], List[int]],
        max_depth: Optional[int] = None,
        show_empty: bool = True,
    ):
        """
        Initialize the diagram generator.

        :param packages: List of ModelPackage objects to visualize
        :param get_all_depends_on: Callable that returns all dependency IDs for a package
        :param get_all_class_id: Callable that returns all class IDs contained in a package
        :param max_depth: Maximum depth of package nesting to show (None = unlimited)
        :param show_empty: Whether to include packages with no classes
        """
        self.packages = packages
        self.get_all_depends_on = get_all_depends_on
        self.get_all_class_id = get_all_class_id
        self.max_depth = max_depth
        self.show_empty = show_empty
        self.package_dependencies: Dict[int, Set[int]] = {}

    def _is_ancestor(self, potential_ancestor: ModelPackage, pkg: ModelPackage) -> bool:
        """
        Check if potential_ancestor is an ancestor (parent, grandparent, etc.) of pkg.
        """
        current = pkg.parent
        while current is not None:
            if current.package_id == potential_ancestor.package_id:
                return True
            current = current.parent
        return False

    def _is_descendant(self, potential_descendant: ModelPackage, pkg: ModelPackage) -> bool:
        """
        Check if potential_descendant is a descendant (child, grandchild, etc.) of pkg.
        """
        return self._is_ancestor(pkg, potential_descendant)

    def build_dependency_graph(self) -> Dict[int, Set[int]]:
        """
        Build a graph of package dependencies.
        Returns a dictionary mapping package_id -> set of package_ids it depends on.
        Excludes dependencies on ancestor/descendant packages to avoid cluttering the diagram.
        """
        dependencies: Dict[int, Set[int]] = {pkg.package_id: set() for pkg in self.packages}

        # Build the dependency graph (similar to topological_sort_packages logic)
        for u_pkg in self.packages:
            u_depends_on = set(self.get_all_depends_on(u_pkg))
            for v_pkg in self.packages:
                if u_pkg.package_id == v_pkg.package_id:
                    continue

                # Skip if v_pkg is an ancestor or descendant of u_pkg
                # (containment relationship is already shown in the hierarchy)
                if self._is_ancestor(v_pkg, u_pkg) or self._is_descendant(v_pkg, u_pkg):
                    continue

                v_class_ids = set(self.get_all_class_id(v_pkg))
                if u_depends_on.intersection(v_class_ids):
                    # u_pkg depends on v_pkg
                    dependencies[u_pkg.package_id].add(v_pkg.package_id)

        self.package_dependencies = dependencies
        return dependencies

    def _sanitize_name(self, name: str) -> str:
        """
        Sanitize package names for PlantUML syntax.

        Delegates to mermaid_utils.sanitize_id with for_plantuml=True
        to eliminate code duplication.
        """
        from eaidl.mermaid_utils import sanitize_id

        return sanitize_id(name, for_plantuml=True)

    def _get_package_depth(self, pkg: ModelPackage) -> int:
        """
        Calculate the depth of a package in the hierarchy (0 = root).
        """
        depth = 0
        current = pkg.parent
        while current is not None:
            depth += 1
            current = current.parent
        return depth

    def _should_include_package(self, pkg: ModelPackage) -> bool:
        """
        Determine if a package should be included in the diagram.
        """
        # Check depth limit
        if self.max_depth is not None and self._get_package_depth(pkg) > self.max_depth:
            return False

        # Check if empty packages should be shown
        if not self.show_empty:
            has_content = len(pkg.classes) > 0 or len(pkg.packages) > 0
            if not has_content:
                return False

        return True

    def _generate_plantuml_package(self, pkg: ModelPackage, indent: int = 0, processed: Set[int] = None) -> List[str]:
        """
        Recursively generate PlantUML syntax for a package and its children.

        :param pkg: Package to generate
        :param indent: Current indentation level
        :param processed: Set of package IDs already processed
        :return: List of lines of PlantUML syntax
        """
        if processed is None:
            processed = set()

        if pkg.package_id in processed or not self._should_include_package(pkg):
            return []

        processed.add(pkg.package_id)
        lines = []
        indent_str = "  " * indent

        # Sanitize package name
        pkg_name = self._sanitize_name(pkg.name)
        pkg_id = f"pkg_{pkg.package_id}"

        # Add class count as metadata if package has classes
        metadata = ""
        if len(pkg.classes) > 0:
            metadata = f" <<{len(pkg.classes)} class{'es' if len(pkg.classes) != 1 else ''}>>"

        # Open package block
        lines.append(f'{indent_str}package "{pkg_name}" as {pkg_id}{metadata} {{')

        # Process child packages recursively
        for child_pkg in sorted(pkg.packages, key=lambda p: p.name):
            child_lines = self._generate_plantuml_package(child_pkg, indent + 1, processed)
            lines.extend(child_lines)

        # Close package block
        lines.append(f"{indent_str}}}")

        return lines

    def generate_plantuml(self) -> str:
        """
        Generate a complete PlantUML diagram showing package structure and dependencies.

        :return: PlantUML diagram as a string
        """
        # Build the dependency graph
        self.build_dependency_graph()

        lines = ["@startuml"]
        lines.append("!theme plain")
        lines.append("")

        # Find root packages (those without parents or whose parents are not in the list)
        package_ids = {pkg.package_id for pkg in self.packages}
        root_packages = [pkg for pkg in self.packages if pkg.parent is None or pkg.parent.package_id not in package_ids]

        # Generate package hierarchy
        processed: Set[int] = set()
        for root_pkg in sorted(root_packages, key=lambda p: p.name):
            pkg_lines = self._generate_plantuml_package(root_pkg, 0, processed)
            lines.extend(pkg_lines)
            lines.append("")

        # Generate dependency arrows
        lines.append("' Package dependencies")
        for pkg_id, dep_ids in sorted(self.package_dependencies.items()):
            if dep_ids:
                pkg_id_str = f"pkg_{pkg_id}"
                for dep_id in sorted(dep_ids):
                    # Only show dependencies between packages that were included
                    if pkg_id in processed and dep_id in processed:
                        dep_id_str = f"pkg_{dep_id}"
                        lines.append(f"{pkg_id_str} --> {dep_id_str}")

        lines.append("")
        lines.append("@enduml")

        return "\n".join(lines)
