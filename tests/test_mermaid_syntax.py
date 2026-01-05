"""
Tests for validating Mermaid diagram syntax.

These tests validate that generated Mermaid diagrams are syntactically correct
and will render properly in Mermaid.js.
"""

import re
from typing import List, Set
import pytest
from eaidl.load import ModelParser
from eaidl.utils import load_config
from eaidl.mermaid_debug import get_mermaid_live_link
from eaidl.diagram_builder import ClassDiagramBuilder
from eaidl.renderers.factory import get_renderer


class MermaidSyntaxValidator:
    """Validates Mermaid class diagram syntax."""

    def __init__(self, diagram_code: str):
        self.diagram_code = diagram_code
        self.lines = diagram_code.split("\n")
        self.errors: List[str] = []

    def validate(self) -> List[str]:
        """
        Run all validation checks.

        :return: List of error messages (empty if valid)
        """
        self.errors = []
        self._validate_header()
        self._validate_balanced_braces()
        self._validate_class_definitions()
        self._validate_relationships()
        self._validate_click_handlers()
        self._validate_no_duplicate_classes()
        return self.errors

    def _validate_header(self):
        """Validate diagram starts with classDiagram."""
        if not self.lines or not self.lines[0].strip().startswith("classDiagram"):
            self.errors.append("Diagram must start with 'classDiagram'")

    def _validate_balanced_braces(self):
        """Validate all braces are balanced."""
        open_count = 0
        for i, line in enumerate(self.lines, 1):
            open_count += line.count("{")
            close_count = line.count("}")
            open_count -= close_count
            if open_count < 0:
                self.errors.append(f"Line {i}: Unbalanced braces - too many closing braces")
                return

        if open_count > 0:
            self.errors.append(f"Unbalanced braces - {open_count} unclosed opening brace(s)")

    def _validate_class_definitions(self):
        """Validate class definitions are syntactically correct."""
        class_pattern = re.compile(r"^\s*class\s+(\w+)(\s*\{)?$")
        # Attribute pattern: visibility + optional asterisk (for inherited) + name + optional? + space + type
        attribute_pattern = re.compile(r"^\s+[+\-#~]\*?\w+\??\s+.+$")
        in_class = False

        for i, line in enumerate(self.lines, 1):
            stripped = line.strip()

            # Skip empty lines and non-class lines
            if not stripped or stripped.startswith("click") or "--" in stripped:
                continue

            # Check class definition (match on original line to preserve indentation check)
            match = class_pattern.match(line)
            if match:
                class_name = match.group(1)
                # Validate class name is alphanumeric + underscore
                if not re.match(r"^[A-Za-z_]\w*$", class_name):
                    self.errors.append(
                        f"Line {i}: Invalid class name '{class_name}' - "
                        f"must start with letter/underscore and contain only alphanumeric/underscore"
                    )
                in_class = bool(match.group(2))  # Has opening brace
                continue

            # Check for closing brace
            if stripped == "}":
                in_class = False
                continue

            # If inside class definition, validate attribute format
            if in_class:
                # Allow ellipsis lines for truncated attributes
                if "..." in stripped:
                    continue

                # Validate attribute syntax (match on original line for indentation)
                if not attribute_pattern.match(line):
                    self.errors.append(
                        f"Line {i}: Invalid attribute syntax '{stripped}' - "
                        f"expected format: '+name type' or '+name? type'"
                    )

    def _validate_relationships(self):
        """Validate relationship syntax."""
        # Mermaid relationship patterns (label is optional after colon)
        relationship_patterns = [
            r"^\s*\w+\s+\|\|--o\{\s+\w+(\s*:\s*\S+)?$",  # Zero or more
            r"^\s*\w+\s+\|\|--\|\|\s+\w+(\s*:\s*\S+)?$",  # Exactly one
            r"^\s*\w+\s+}o--o\{\s+\w+(\s*:\s*\S+)?$",  # Zero or more to zero or more
            r'^\s*\w+\s+"[^"]*"\s+-->\s+"[^"]*"\s+\w+(\s*:\s*\S+)?$',  # Association with cardinality
            r"^\s*\w+\s+-->\s+\w+(\s*:\s*\S+)?$",  # Association
            r"^\s*\w+\s+\*--\s+\w+(\s*:\s*\S+)?$",  # Composition
            r"^\s*\w+\s+o--\s+\w+(\s*:\s*\S+)?$",  # Aggregation
            r"^\s*\w+\s+--\|>\s+\w+(\s*:\s*\S+)?$",  # Inheritance
            r"^\s*\w+\s+\.\.>\s+\w+(\s*:\s*\S+)?$",  # Dependency
        ]

        for i, line in enumerate(self.lines, 1):
            stripped = line.strip()

            # Check if line contains relationship arrow
            if any(arrow in stripped for arrow in ["-->", "--", "..", "*--", "o--", "--|>", "..>"]):
                # Skip click handlers
                if stripped.startswith("click"):
                    continue

                # Validate against known patterns
                is_valid = any(re.match(pattern, stripped) for pattern in relationship_patterns)
                if not is_valid:
                    self.errors.append(f"Line {i}: Invalid relationship syntax '{stripped}'")

    def _validate_click_handlers(self):
        """Validate click handler syntax."""
        click_pattern = re.compile(r'^click\s+(\w+)\s+href\s+"([^"]+)"\s+(_self|_blank)$')

        for i, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if stripped.startswith("click"):
                if not click_pattern.match(stripped):
                    self.errors.append(
                        f"Line {i}: Invalid click handler syntax '{stripped}' - "
                        f'expected: click ClassName href "url" _self'
                    )

    def _validate_no_duplicate_classes(self):
        """Validate no duplicate class definitions."""
        class_pattern = re.compile(r"^class\s+(\w+)")
        defined_classes: Set[str] = set()

        for i, line in enumerate(self.lines, 1):
            match = class_pattern.match(line.strip())
            if match:
                class_name = match.group(1)
                if class_name in defined_classes:
                    self.errors.append(f"Line {i}: Duplicate class definition '{class_name}'")
                defined_classes.add(class_name)


def validate_mermaid_syntax(diagram_code: str) -> List[str]:
    """
    Validate Mermaid diagram syntax.

    :param diagram_code: Mermaid diagram code
    :return: List of error messages (empty if valid)
    """
    validator = MermaidSyntaxValidator(diagram_code)
    return validator.validate()


class TestMermaidSyntaxValidation:
    """Tests for Mermaid syntax validation."""

    def test_valid_simple_diagram(self):
        """Test validation of a simple valid diagram."""
        diagram = """classDiagram
class Foo
class Bar
Foo --> Bar : uses
"""
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) == 0, f"Should be valid but got errors: {errors}"

    def test_valid_diagram_with_attributes(self):
        """Test validation of diagram with attributes."""
        diagram = """classDiagram
class Foo {
    +name string
    +age int
    +active? bool
}
class Bar {
    +id long
}
Foo --> Bar : references
"""
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) == 0, f"Should be valid but got errors: {errors}"

    def test_missing_header(self):
        """Test detection of missing classDiagram header."""
        diagram = """class Foo
class Bar
"""
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) > 0
        assert any("classDiagram" in err for err in errors)

    def test_unbalanced_braces_open(self):
        """Test detection of unclosed braces."""
        diagram = """classDiagram
class Foo {
    +name string
"""
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) > 0
        assert any("braces" in err.lower() for err in errors)

    def test_unbalanced_braces_close(self):
        """Test detection of extra closing braces."""
        diagram = """classDiagram
class Foo {
    +name string
}
}
"""
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) > 0
        assert any("braces" in err.lower() for err in errors)

    def test_invalid_class_name(self):
        """Test detection of invalid class names."""
        diagram = """classDiagram
class 123Invalid
"""
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) > 0
        assert any("class name" in err.lower() for err in errors)

    def test_invalid_attribute_syntax(self):
        """Test detection of invalid attribute syntax."""
        diagram = """classDiagram
class Foo {
    not-valid-attribute
}
"""
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) > 0
        assert any("attribute" in err.lower() for err in errors)

    def test_invalid_click_handler(self):
        """Test detection of invalid click handler syntax."""
        diagram = """classDiagram
class Foo
click Foo invalid syntax
"""
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) > 0
        assert any("click" in err.lower() for err in errors)

    def test_duplicate_class_definitions(self):
        """Test detection of duplicate class definitions."""
        diagram = """classDiagram
class Foo
class Bar
class Foo
"""
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) > 0
        assert any("duplicate" in err.lower() for err in errors)


class TestGeneratedDiagramsValidation:
    """Tests that validate generated diagrams from real EA models."""

    @pytest.fixture
    def config(self):
        """Load test configuration."""
        return load_config("config/sqlite.yaml")

    @pytest.fixture
    def parser(self, config):
        """Create model parser."""
        return ModelParser(config)

    @pytest.fixture
    def puppeteer_config(self, tmp_path):
        """Create puppeteer config file for mmdc."""
        import json

        config_file = tmp_path / "puppeteer-config.json"
        config_file.write_text(json.dumps({"args": ["--no-sandbox", "--disable-setuid-sandbox"]}))
        return str(config_file)

    def test_all_package_diagrams_valid_syntax(self, parser, config):
        """Test that all generated package diagrams have valid Mermaid syntax."""
        packages = parser.load()

        errors_by_package = {}

        def check_package(pkg):
            """Recursively check package and its children."""
            if pkg.classes:  # Only check packages with classes
                builder = ClassDiagramBuilder(pkg, config, packages)
                desc = builder.build()
                renderer = get_renderer(config)
                output = renderer.render_class_diagram(desc)
                diagram = output.content
                validation_errors = validate_mermaid_syntax(diagram)
                if validation_errors:
                    namespace_key = ".".join(pkg.namespace)
                    errors_by_package[namespace_key] = validation_errors

            for child_pkg in pkg.packages:
                check_package(child_pkg)

        for root_pkg in packages:
            check_package(root_pkg)

        # Report all errors
        if errors_by_package:
            error_report = []
            for namespace, errors in errors_by_package.items():
                error_report.append(f"\nPackage: {namespace}")
                for error in errors:
                    error_report.append(f"  - {error}")

                # Generate diagram for this package to include debug link
                # Find the package object
                def find_package(pkg, target_namespace_str):
                    if ".".join(pkg.namespace) == target_namespace_str:
                        return pkg
                    for child in pkg.packages:
                        result = find_package(child, target_namespace_str)
                        if result:
                            return result
                    return None

                target_pkg = None
                for root_pkg in packages:
                    target_pkg = find_package(root_pkg, namespace)
                    if target_pkg:
                        break

                if target_pkg:
                    builder = ClassDiagramBuilder(target_pkg, config, packages)
                    desc = builder.build()
                    renderer = get_renderer(config)
                    output = renderer.render_class_diagram(desc)
                    diagram = output.content
                    debug_link = get_mermaid_live_link(diagram)
                    error_report.append(f"  Debug link: {debug_link}")

            pytest.fail(f"Found Mermaid syntax errors in generated diagrams:{''.join(error_report)}")

    def test_specific_package_diagram_structure(self, parser, config):
        """Test specific package diagram has expected structure."""
        packages = parser.load()

        # Find a package with classes
        test_package = None
        for pkg in packages:
            if pkg.classes:
                test_package = pkg
                break
            for sub_pkg in pkg.packages:
                if sub_pkg.classes:
                    test_package = sub_pkg
                    break
            if test_package:
                break

        assert test_package is not None, "No packages with classes found in test model"

        builder = ClassDiagramBuilder(test_package, config, packages)
        desc = builder.build()
        renderer = get_renderer(config)
        output = renderer.render_class_diagram(desc)
        diagram = output.content

        # Validate syntax
        errors = validate_mermaid_syntax(diagram)
        assert len(errors) == 0, f"Diagram has syntax errors: {errors}"

        # Check expected structure
        assert "classDiagram" in diagram
        assert any(cls.name in diagram for cls in test_package.classes), "Class names should appear in diagram"

    def test_diagram_click_handlers_valid(self, parser, config):
        """Test that all click handlers in generated diagrams are valid."""
        packages = parser.load()

        # Find a package with classes
        test_package = None
        for pkg in packages:
            if pkg.classes:
                test_package = pkg
                break
            for sub_pkg in pkg.packages:
                if sub_pkg.classes:
                    test_package = sub_pkg
                    break
            if test_package:
                break

        assert test_package is not None, "No packages with classes found in test model"

        builder = ClassDiagramBuilder(test_package, config, packages)
        desc = builder.build()
        renderer = get_renderer(config)
        output = renderer.render_class_diagram(desc)
        diagram = output.content
        lines = diagram.split("\n")

        # Extract and validate click handlers
        click_pattern = re.compile(r'^click\s+(\w+)\s+href\s+"([^"]+)"\s+(_self|_blank)$')
        click_handlers = [line.strip() for line in lines if line.strip().startswith("click")]

        for handler in click_handlers:
            match = click_pattern.match(handler)
            assert match is not None, f"Invalid click handler syntax: {handler}"

            class_name = match.group(1)
            url = match.group(2)
            target = match.group(3)

            # Validate URL is not empty
            assert url, f"Empty URL in click handler for {class_name}"
            # Validate target is _self (we use same-tab navigation)
            assert target == "_self", f"Expected _self target, got {target}"

    def test_diagrams_render_with_mmdc(self, parser, config, puppeteer_config, tmp_path):
        """Test that generated diagrams can be rendered by Mermaid CLI (mmdc)."""
        import subprocess
        import shutil

        # Check if mmdc is available
        if not shutil.which("mmdc"):
            pytest.skip("mmdc (Mermaid CLI) not installed")

        packages = parser.load()

        # Test the three problematic packages mentioned in the issues
        test_packages = [
            (["core", "common", "types"], "types"),
            (["core", "data"], "data"),
            (["core", "message"], "message"),
        ]

        failed_diagrams = []

        for namespace, short_name in test_packages:
            # Find package
            def find_package(pkg, target_ns):
                if pkg.namespace == target_ns:
                    return pkg
                for child in pkg.packages:
                    result = find_package(child, target_ns)
                    if result:
                        return result
                return None

            target_pkg = None
            for root_pkg in packages:
                target_pkg = find_package(root_pkg, namespace)
                if target_pkg:
                    break

            if not target_pkg:
                continue

            # Generate diagram
            builder = ClassDiagramBuilder(target_pkg, config, packages)
            desc = builder.build()
            renderer = get_renderer(config)
            output = renderer.render_class_diagram(desc)
            diagram = output.content

            # Save to file
            diagram_file = tmp_path / f"{short_name}_diagram.mmd"
            diagram_file.write_text(diagram)

            # Try to render with mmdc
            output_file = tmp_path / f"{short_name}_diagram.svg"
            try:
                result = subprocess.run(
                    [
                        "mmdc",
                        "-i",
                        str(diagram_file),
                        "-o",
                        str(output_file),
                        "--puppeteerConfigFile",
                        puppeteer_config,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode != 0:
                    failed_diagrams.append(
                        {"package": ".".join(namespace), "error": result.stderr, "diagram_file": str(diagram_file)}
                    )
                else:
                    # Verify output file was created
                    assert output_file.exists(), f"mmdc did not create output file for {'.'.join(namespace)}"
                    assert output_file.stat().st_size > 0, f"mmdc created empty file for {'.'.join(namespace)}"

            except subprocess.TimeoutExpired:
                failed_diagrams.append(
                    {
                        "package": ".".join(namespace),
                        "error": "mmdc timed out after 30 seconds",
                        "diagram_file": str(diagram_file),
                    }
                )

        # Report all failures
        if failed_diagrams:
            error_report = ["\nFailed to render diagrams with mmdc:"]
            for failure in failed_diagrams:
                error_report.append(f"\nPackage: {failure['package']}")
                error_report.append(f"  Diagram file: {failure['diagram_file']}")
                error_report.append(f"  Error: {failure['error']}")

            pytest.fail("".join(error_report))
