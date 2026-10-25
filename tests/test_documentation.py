"""Completeness and identity checks for documentation-only diagram scope."""

import json
import sqlite3

import pytest
from pydantic import ValidationError

from eaidl.config import Configuration, DocumentationConfiguration
from eaidl.documentation import export_documentation, select_diagrams
from eaidl.html_export import create_html_env


@pytest.fixture
def model_rows():
    packages = [
        dict(Package_ID=1, Parent_ID=0, Name="model", ea_guid="{ROOT}"),
        dict(Package_ID=2, Parent_ID=1, Name="p5", ea_guid="{P5}"),
        dict(Package_ID=3, Parent_ID=0, Name="foreign", ea_guid="{FOREIGN}"),
    ]
    diagrams = [
        dict(
            Diagram_ID=i,
            Package_ID=package,
            Name="Same name",
            ea_guid=f"{{D{i}}}",
            Diagram_Type="Statechart",
            Notes="",
            StyleEx="",
        )
        for i, package in [(1, 2), (2, 2), (3, 1), (4, 3)]
    ]
    return packages, diagrams


def settings(**kwargs):
    return DocumentationConfiguration(
        root_packages=["{ROOT}"],
        sections={
            "behaviour": {"title": "Lifecycles", "views": ["P5"]},
        },
        **kwargs,
    )


def test_complete_scope_preserves_same_named_diagrams_and_unmapped_views(model_rows):
    entries = select_diagrams(*model_rows, settings())
    assert {e["guid"] for e in entries} == {"d1", "d2", "d3"}
    assert len({e["url"] for e in entries}) == 3
    assert {e["section"] for e in entries} == {"behaviour", "other"}


def test_profile_view_takes_precedence_over_package(model_rows):
    model_rows[1][0]["StyleEx"] = "MDGDgm=NAFv4::P7 - Physical Data Model;"
    entries = select_diagrams(*model_rows, settings())
    assert next(e for e in entries if e["guid"] == "d1")["view"] == "P7"
    assert next(e for e in entries if e["guid"] == "d1")["section"] == "other"


def test_exclusions_require_reason_and_scoped_guid(model_rows):
    entries = select_diagrams(*model_rows, settings(exclude_diagrams={"{D1}": "Withdrawn example"}))
    assert next(e for e in entries if e["guid"] == "d1")["status"] == "excluded"
    for exclusions in [{"d1": " "}, {"d4": "Outside scope"}]:
        with pytest.raises(ValueError):
            select_diagrams(*model_rows, settings(exclude_diagrams=exclusions))


def test_ambiguous_roots_and_duplicate_view_mappings_fail(model_rows):
    model_rows[0].append(dict(Package_ID=4, Parent_ID=0, Name="model", ea_guid="{OTHER}"))
    config = settings()
    config.root_packages = ["model"]
    with pytest.raises(ValueError, match="one package"):
        select_diagrams(*model_rows, config)
    config.root_packages = ["{ROOT}"]
    config.sections["duplicate"] = config.sections["behaviour"]
    with pytest.raises(ValueError, match="more than once"):
        select_diagrams(*model_rows, config)


def test_documentation_configuration_rejects_typos():
    with pytest.raises(ValidationError):
        DocumentationConfiguration(root_package=["core"])


def test_failed_render_is_reported_and_fails_build(tmp_path, monkeypatch):
    """A renderer error must not silently reduce catalogue completeness."""
    from eaidl.native_diagram_extractor import NativeDiagramExtractor

    database = tmp_path / "model.qea"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE t_package (Package_ID INTEGER PRIMARY KEY, Parent_ID INTEGER, Name TEXT, ea_guid TEXT);
            INSERT INTO t_package VALUES (1, 0, 'model', '{ROOT}');
            CREATE TABLE t_diagram (Diagram_ID INTEGER PRIMARY KEY, Package_ID INTEGER, Name TEXT,
                ea_guid TEXT, Diagram_Type TEXT, Notes TEXT, StyleEx TEXT);
            INSERT INTO t_diagram VALUES (1, 1, 'Broken diagram', '{D1}', 'Custom', '', '');
        """)
    config = Configuration(database_url=f"sqlite:///{database}", documentation=settings())

    def fail(*_args):
        raise ValueError("Broken layout")

    monkeypatch.setattr(NativeDiagramExtractor, "extract_by_id", fail)
    with pytest.raises(RuntimeError, match="1 documentation diagrams failed"):
        export_documentation(config, [], tmp_path, create_html_env(config))
    report = json.loads((tmp_path / "diagram-coverage.json").read_text())
    assert report["total"] == 1
    assert report["counts"] == {"failed": 1}
    assert "Broken layout" in (tmp_path / "diagrams.html").read_text()


def test_catalogue_links_search_and_refresh(tmp_path, monkeypatch):
    """Standalone pages link to type/package pages and refresh removes stale diagrams."""
    from eaidl.html_export import export_html
    from eaidl.model import ModelClass, ModelPackage
    from eaidl.native_diagram_extractor import NativeDiagramExtractor
    from eaidl.native_diagram_model import NativeDiagram, NativeDiagramNode
    from eaidl.config import NativeDiagramStyleConfig

    database = tmp_path / "model.qea"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE t_package (Package_ID INTEGER PRIMARY KEY, Parent_ID INTEGER, Name TEXT, ea_guid TEXT);
            INSERT INTO t_package VALUES (1, 0, 'model', '{ROOT}');
            CREATE TABLE t_diagram (Diagram_ID INTEGER PRIMARY KEY, Package_ID INTEGER, Name TEXT,
                ea_guid TEXT, Diagram_Type TEXT, Notes TEXT, StyleEx TEXT);
            INSERT INTO t_diagram VALUES (1, 1, 'Overview', '{D1}', 'Custom', '', '');
        """)
    package = ModelPackage(name="model", namespace=["model"], guid="root", package_id=1, object_id=1)
    cls = ModelClass(name="Example", namespace=["model"], guid="element", object_id=2, parent=package)
    package.classes = [cls]
    from eaidl.model import ModelDiagram

    package.diagrams = [ModelDiagram(diagram_id=1, package_id=1, name="Overview", guid="d1")]
    diagram = NativeDiagram(
        diagram_id=1,
        name="Overview",
        diagram_type="Custom",
        canvas_width=200,
        canvas_height=200,
        nodes=[
            NativeDiagramNode(
                object_id=2,
                name="Example",
                object_type="Class",
                ea_guid="{ELEMENT}",
                style={},
                rect_left=10,
                rect_top=-10,
                rect_right=190,
                rect_bottom=-190,
            )
        ],
    )
    monkeypatch.setattr(NativeDiagramExtractor, "extract_by_id", lambda *_args: diagram)
    config = Configuration(database_url=f"sqlite:///{database}", documentation=settings())
    config.diagrams.native_diagram_style = NativeDiagramStyleConfig(ea_detail_nodes=True, font_family="Carlito")
    export_html(config, [package], tmp_path)
    page = (tmp_path / "diagrams/d1.html").read_text()
    assert 'href="../packages/model/index.html"' in page
    assert 'href="../classes/model/Example.html"' in page
    assert "Carlito-Regular.ttf" in (tmp_path / "diagrams/d1.svg").read_text()
    assert (tmp_path / "assets/fonts/carlito/OFL.txt").exists()
    package_page = (tmp_path / "packages/model/index.html").read_text()
    assert 'href="../../diagrams/d1.html"' in package_page
    assert 'id="ea-page-frame"' not in package_page
    assert not (tmp_path / "packages/model/diagram.html").exists()
    assert any(e["type"] == "diagram" for e in json.loads((tmp_path / "search.json").read_text()))
    (tmp_path / "diagrams/old.svg").write_text("old")
    config.documentation.exclude_diagrams = {"d1": "Withdrawn"}
    export_html(config, [package], tmp_path)
    assert not (tmp_path / "diagrams/d1.html").exists()
    assert not (tmp_path / "diagrams/old.svg").exists()
    assert json.loads((tmp_path / "diagram-coverage.json").read_text())["counts"] == {"excluded": 1}


def test_same_view_can_be_split_by_package_and_overlap_is_rejected(model_rows):
    package_rows, diagram_rows = model_rows
    package_rows.append(dict(Package_ID=5, Parent_ID=1, Name="p5", ea_guid="{SECOND}"))
    diagram_rows.append(
        dict(
            Diagram_ID=5,
            Package_ID=5,
            Name="Second lifecycle",
            ea_guid="{D5}",
            Diagram_Type="Statechart",
            Notes="",
            StyleEx="",
        )
    )
    config = DocumentationConfiguration(
        root_packages=["{ROOT}"],
        sections={
            "first": {"title": "First AEP", "views": ["P5"], "root_packages": ["{P5}"]},
            "second": {"title": "Second AEP", "views": ["P5"], "root_packages": ["{SECOND}"]},
        },
    )
    entries = select_diagrams(package_rows, diagram_rows, config)
    assert next(e for e in entries if e["guid"] == "d1")["section"] == "first"
    assert next(e for e in entries if e["guid"] == "d5")["section"] == "second"
    config.sections["second"].root_packages = ["{ROOT}"]
    with pytest.raises(ValueError, match="multiple sections"):
        select_diagrams(package_rows, diagram_rows, config)


def test_site_title_is_configurable():
    config = Configuration(documentation={"title": "STANAG4817 documentation"})
    page = (
        create_html_env(config)
        .get_template("index.jinja2")
        .render(
            packages=[],
            stats=dict(packages=0, structs=0, enums=0, unions=0),
            current_namespace=None,
            index_link="index.html",
            assets_path="assets",
            search_index_path="search.json",
        )
    )
    assert "<title>STANAG4817 documentation - Home</title>" in page
    assert ">STANAG4817 documentation</a>" in page
    assert ">STANAG4817 documentation</h1>" in page


def test_navigation_groups_base_with_105_and_exposes_sections(tmp_path):
    from eaidl.html_export import export_html
    from eaidl.model import ModelPackage

    config = Configuration(
        documentation={
            "package_groups": {"AEP-105": ["base", "catl"], "AEP-109": ["aep109"]},
        }
    )
    packages = [
        ModelPackage(name=n, namespace=[n], guid=n, package_id=i, object_id=i)
        for i, n in enumerate(["base", "catl", "aep109"], 1)
    ]
    export_html(config, packages, tmp_path)
    page = (tmp_path / "index.html").read_text()
    from html.parser import HTMLParser

    class Groups(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.links = []

        def handle_starttag(self, tag, attrs):
            if tag == "details":
                self.stack.append([])
            if tag == "a":
                href = dict(attrs).get("href", "")
                if self.stack:
                    self.stack[-1].append(href)

        def handle_endtag(self, tag):
            if tag == "details":
                self.links.append(self.stack.pop())

    parser = Groups()
    parser.feed(page)
    assert ["packages/base/index.html", "packages/catl/index.html"] in parser.links
    assert ["packages/aep109/index.html"] in parser.links
    assert 'id="sidebar-toggle"' in page
    assert 'aria-controls="sidebar"' in page


def test_p7_navigation_is_listed_once_per_aep():
    config = Configuration(
        documentation={
            "root_packages": ["{ROOT}"],
            "sections": {
                "data105": {"title": "AEP-105 P7", "views": ["P7"], "root_packages": ["{105}"]},
                "data109": {"title": "AEP-109 P7", "views": ["P7"], "root_packages": ["{109}"]},
                "logical": {"title": "Logical models", "views": ["L7"]},
            },
            "package_groups": {"AEP-105": ["base", "catl"], "AEP-109": ["aep109"]},
            "package_group_sections": {"AEP-105": ["data105"], "AEP-109": ["data109"]},
        }
    )
    page = (
        create_html_env(config)
        .get_template("index.jinja2")
        .render(
            packages=[],
            all_packages=[],
            stats=dict(packages=0, structs=0, enums=0, unions=0),
            current_namespace=None,
            index_link="index.html",
            assets_path="assets",
            search_index_path="search.json",
        )
    )
    assert page.count('href="diagrams.html#data105"') == 0
    assert page.count('href="diagrams.html#data109"') == 0
    assert page.count('href="diagrams.html#logical"') == 2
    assert "assets/fonts/carlito/Carlito-Bold.ttf" in page
