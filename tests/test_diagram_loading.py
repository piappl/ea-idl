from eaidl.load import ModelParser
from eaidl.utils import load_config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.ext.automap import automap_base
import pytest


def test_load_diagrams_from_database():
    """Test that diagrams are loaded from EA database."""
    config = load_config("config/sqlite.yaml")
    parser = ModelParser(config)
    packages = parser.load()

    # Find any package with diagrams
    diagram_found = False
    test_diagram = None
    test_package = None

    def find_diagrams(pkg):
        nonlocal diagram_found, test_diagram, test_package
        if pkg.diagrams:
            diagram_found = True
            test_diagram = pkg.diagrams[0]
            test_package = pkg
            return True
        for child_pkg in pkg.packages:
            if find_diagrams(child_pkg):
                return True
        return False

    for pkg in packages:
        if find_diagrams(pkg):
            break

    # If no diagrams found, skip test (database might not have diagrams)
    if not diagram_found:
        pytest.skip("No diagrams found in test database")

    # Verify diagram structure
    assert test_diagram.diagram_id > 0
    assert test_diagram.name
    assert test_diagram.package_id == test_package.package_id


def test_diagram_objects_have_positions():
    """Test that diagram objects have coordinate data."""
    config = load_config("config/sqlite.yaml")
    parser = ModelParser(config)
    packages = parser.load()

    # Find a diagram with objects
    diagram = None

    def find_diagram_with_objects(pkg):
        nonlocal diagram
        for diag in pkg.diagrams:
            if diag.objects:
                diagram = diag
                return True
        for child_pkg in pkg.packages:
            if find_diagram_with_objects(child_pkg):
                return True
        return False

    for pkg in packages:
        if find_diagram_with_objects(pkg):
            break

    # If no diagrams with objects found, skip test
    if diagram is None or not diagram.objects:
        pytest.skip("No diagrams with objects found in test database")

    # Check first object has coordinates
    obj = diagram.objects[0]
    assert obj.object_id is not None
    assert obj.rect_top is not None
    assert obj.rect_left is not None
    assert obj.rect_right is not None
    assert obj.rect_bottom is not None
    assert obj.sequence is not None


def test_diagram_links_loaded():
    """Test that diagram links are loaded."""
    config = load_config("config/sqlite.yaml")
    parser = ModelParser(config)
    packages = parser.load()

    # Find a diagram with links
    diagram = None

    def find_diagram_with_links(pkg):
        nonlocal diagram
        for diag in pkg.diagrams:
            if diag.links:
                diagram = diag
                return True
        for child_pkg in pkg.packages:
            if find_diagram_with_links(child_pkg):
                return True
        return False

    for pkg in packages:
        if find_diagram_with_links(pkg):
            break

    # If no diagrams with links found, skip test
    if diagram is None or not diagram.links:
        pytest.skip("No diagrams with links found in test database")

    # Check first link has connector_id
    link = diagram.links[0]
    assert link.connector_id is not None
    assert link.diagram_id == diagram.diagram_id


def test_diagrams_table_exists():
    """Test that diagram tables exist in the database."""
    engine = create_engine("sqlite+pysqlite:///tests/data/nafv4.qea", echo=False)
    base = automap_base()
    base.prepare(autoload_with=engine)

    # Check if diagram tables exist
    assert hasattr(base.classes, "t_diagram")
    assert hasattr(base.classes, "t_diagramobjects")
    assert hasattr(base.classes, "t_diagramlinks")


def test_diagram_count():
    """Test diagram count in database."""
    engine = create_engine("sqlite+pysqlite:///tests/data/nafv4.qea", echo=False)
    base = automap_base()
    base.prepare(autoload_with=engine)
    session = Session(engine)

    TDiagram = base.classes.t_diagram
    diagram_count = session.query(TDiagram).count()

    # Just verify we can query diagrams (count might be 0 or more)
    assert diagram_count >= 0


def test_multiple_diagrams_per_package():
    """Test that packages can have multiple diagrams."""
    config = load_config("config/sqlite.yaml")
    parser = ModelParser(config)
    packages = parser.load()

    # Find any package with multiple diagrams
    multi_diagram_package = None

    def find_multi_diagram_package(pkg):
        nonlocal multi_diagram_package
        if len(pkg.diagrams) > 1:
            multi_diagram_package = pkg
            return True
        for child_pkg in pkg.packages:
            if find_multi_diagram_package(child_pkg):
                return True
        return False

    for pkg in packages:
        if find_multi_diagram_package(pkg):
            break

    # If no package with multiple diagrams, just verify structure works
    if multi_diagram_package is None:
        pytest.skip("No packages with multiple diagrams found")

    # Verify all diagrams have unique IDs
    diagram_ids = [d.diagram_id for d in multi_diagram_package.diagrams]
    assert len(diagram_ids) == len(set(diagram_ids)), "Diagram IDs should be unique"


def test_diagram_parse_error_handling():
    """Test that diagram parsing handles errors gracefully."""
    config = load_config("config/sqlite.yaml")
    parser = ModelParser(config)

    # Test with invalid package_id
    diagrams = parser.load_package_diagrams(-9999)
    assert isinstance(diagrams, list)
    assert len(diagrams) == 0
