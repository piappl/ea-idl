"""Tests for model_markdown.py — Markdown renderer for model export dicts."""

from eaidl.model_markdown import render_markdown


def _minimal_data(**overrides):
    """Build a minimal export dict with optional overrides."""
    data = {
        "metadata": {
            "database_url": "sqlite:///test.qea",
            "export_date": "2026-01-01T00:00:00+00:00",
            "root_packages": [],
        },
        "packages": [],
    }
    data.update(overrides)
    return data


def test_render_empty_model():
    """Empty model produces header and metadata only."""
    md = render_markdown(_minimal_data())
    assert "# Model Documentation" in md
    assert "sqlite:///test.qea" in md
    assert "2026-01-01" in md


def test_render_package_heading_depth():
    """Top-level packages get ##, children get ###."""
    data = _minimal_data(
        packages=[
            {
                "name": "Parent",
                "stereotypes": None,
                "notes": None,
                "packages": [
                    {
                        "name": "Child",
                        "stereotypes": None,
                        "notes": None,
                    }
                ],
            }
        ]
    )
    md = render_markdown(data)
    assert "\n## Parent\n" in md
    assert "\n### Child\n" in md


def test_render_package_stereotypes():
    """Package stereotypes rendered in italics."""
    data = _minimal_data(
        packages=[
            {
                "name": "Pkg",
                "stereotypes": ["DataModel", "Extra"],
                "notes": None,
            }
        ]
    )
    md = render_markdown(data)
    assert "*Stereotypes: DataModel, Extra*" in md


def test_render_package_notes():
    """Package notes rendered as plain text."""
    data = _minimal_data(
        packages=[
            {
                "name": "Pkg",
                "stereotypes": None,
                "notes": "This is a description.",
            }
        ]
    )
    md = render_markdown(data)
    assert "This is a description." in md


def test_render_class_with_kind():
    """Class heading includes kind in parentheses."""
    data = _minimal_data(
        packages=[
            {
                "name": "Pkg",
                "stereotypes": None,
                "notes": None,
                "classes": [
                    {
                        "name": "MyEnum",
                        "kind": "enum",
                        "stereotypes": None,
                        "notes": None,
                    }
                ],
            }
        ]
    )
    md = render_markdown(data)
    assert "### MyEnum (enum)" in md


def test_render_class_stereotypes_and_notes():
    """Class stereotypes and notes are rendered."""
    data = _minimal_data(
        packages=[
            {
                "name": "Pkg",
                "stereotypes": None,
                "notes": None,
                "classes": [
                    {
                        "name": "Foo",
                        "kind": "struct",
                        "stereotypes": ["idlStruct"],
                        "notes": "A struct.",
                    }
                ],
            }
        ]
    )
    md = render_markdown(data)
    assert "*Stereotypes: idlStruct*" in md
    assert "A struct." in md


def test_render_diagrams_table():
    """Diagrams rendered as a markdown table."""
    data = _minimal_data(
        packages=[
            {
                "name": "Pkg",
                "stereotypes": None,
                "notes": None,
                "diagrams": [
                    {
                        "name": "Overview",
                        "diagram_type": "Class",
                        "file_path": "root/Pkg/Overview",
                    }
                ],
            }
        ]
    )
    md = render_markdown(data)
    assert "| Name | Type | Path |" in md
    assert "| Overview | Class | root/Pkg/Overview |" in md


def test_render_attributes_table():
    """Attributes rendered as a markdown table with correct columns."""
    data = _minimal_data(
        packages=[
            {
                "name": "Pkg",
                "stereotypes": None,
                "notes": None,
                "classes": [
                    {
                        "name": "Foo",
                        "kind": "struct",
                        "stereotypes": None,
                        "notes": None,
                        "attributes": [
                            {
                                "name": "field1",
                                "type": "string",
                                "is_collection": True,
                                "is_optional": False,
                                "is_map": False,
                                "lower_bound": "0",
                                "upper_bound": "*",
                                "stereotypes": ["key"],
                                "notes": None,
                            }
                        ],
                    }
                ],
            }
        ]
    )
    md = render_markdown(data)
    assert "| field1 | string | yes | no | no | 0..* | key |" in md


def test_render_attribute_notes():
    """Attribute notes rendered as inline row."""
    data = _minimal_data(
        packages=[
            {
                "name": "Pkg",
                "stereotypes": None,
                "notes": None,
                "classes": [
                    {
                        "name": "Foo",
                        "kind": "struct",
                        "stereotypes": None,
                        "notes": None,
                        "attributes": [
                            {
                                "name": "x",
                                "type": "int",
                                "is_collection": False,
                                "is_optional": False,
                                "is_map": False,
                                "lower_bound": "1",
                                "upper_bound": "1",
                                "stereotypes": None,
                                "notes": "Important field",
                            }
                        ],
                    }
                ],
            }
        ]
    )
    md = render_markdown(data)
    assert "> Important field" in md


def test_render_relations_table():
    """Relations rendered as a markdown table."""
    data = _minimal_data(
        packages=[
            {
                "name": "Pkg",
                "stereotypes": None,
                "notes": None,
                "classes": [
                    {
                        "name": "Foo",
                        "kind": "struct",
                        "stereotypes": None,
                        "notes": None,
                        "relations": [
                            {
                                "type": "Generalization",
                                "target": "Base",
                                "stereotype": None,
                                "direction": "Source -> Destination",
                                "source_cardinality": "",
                                "target_cardinality": "",
                            }
                        ],
                    }
                ],
            }
        ]
    )
    md = render_markdown(data)
    assert "| Type | Target | Stereotype | Direction | Cardinality |" in md
    assert "| Generalization | Base |" in md


def test_render_no_attributes_no_table():
    """Class without attributes doesn't produce an Attributes heading."""
    data = _minimal_data(
        packages=[
            {
                "name": "Pkg",
                "stereotypes": None,
                "notes": None,
                "classes": [
                    {
                        "name": "Empty",
                        "kind": "typedef",
                        "stereotypes": None,
                        "notes": None,
                    }
                ],
            }
        ]
    )
    md = render_markdown(data)
    assert "Empty (typedef)" in md
    assert "Attributes" not in md


def test_render_deeply_nested_packages():
    """Heading depth increases with nesting."""
    data = _minimal_data(
        packages=[
            {
                "name": "L1",
                "stereotypes": None,
                "notes": None,
                "packages": [
                    {
                        "name": "L2",
                        "stereotypes": None,
                        "notes": None,
                        "packages": [
                            {
                                "name": "L3",
                                "stereotypes": None,
                                "notes": None,
                                "classes": [
                                    {
                                        "name": "Deep",
                                        "kind": "struct",
                                        "stereotypes": None,
                                        "notes": None,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    )
    md = render_markdown(data)
    assert "\n## L1\n" in md
    assert "\n### L2\n" in md
    assert "\n#### L3\n" in md
    assert "##### Deep (struct)" in md
