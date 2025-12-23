# type: ignore
# Ignore types because we are calling methods on jinja2 modules.
# Those don't have types.

import pytest
from eaidl.generate import create_env
from eaidl.model import ModelClass, ModelAttribute, ModelPackage, ModelAnnotation
from jinja2 import Template
from typing import Optional, List
import uuid


def template(template: str) -> Template:
    env = create_env()
    return env.get_template(template)


def m_class(name: str = "ClassName", object_id: int = 0, notes: Optional[str] = None) -> ModelClass:
    return ModelClass(name=name, object_id=object_id, notes=notes)


def m_module(name: str = "module_name", object_id: int = 0, notes: Optional[str] = None) -> ModelPackage:
    return ModelPackage(name=name, object_id=object_id, package_id=0, notes=notes, guid=str(uuid.uuid4))


def m_attr(
    name: str = "attr",
    attribute_id: int = 0,
    type: Optional[str] = None,
    notes: Optional[str] = None,
    namespace: List[str] = [],
    union_key: Optional[str] = None,
    union_namespace: Optional[List[str]] = None,
) -> ModelAttribute:
    return ModelAttribute(
        name=name,
        alias=name,
        attribute_id=attribute_id,
        namespace=namespace,
        type=type,
        guid=str(uuid.uuid4),
        notes=notes,
        union_key=union_key,
        union_namespace=union_namespace,
    )


TYPEDEF = "typedef string ClassName;"
TYPEDEF_NOTES = """/**
    A typedef.
*/
typedef string ClassName;"""
ENUM = """enum ClassName {
    @value(0) one,
    @value(1) two
};"""
ENUM_NOTES = """/**
    An enum.
*/
enum ClassName {
    @value(0) one,
    @value(1) two
};"""
ENUM_ATTR_NOTES = """/**
    An enum.
*/
enum ClassName {
    /**
        An attribute 1.
    */
    @value(0) one,
    /**
        An attribute 2.
        nice.
    */
    @value(1) two
};"""
STRUCT_DECLARATION = "struct ClassName;"
STRUCT = """struct ClassName {
    string one;
    int two;
};"""
STRUCT_NOTES = """/**
    A struct.
*/
struct ClassName {
    string one;
    int two;
};"""
STRUCT_ATTR_NOTES = """/**
    A struct.
*/
struct ClassName {
    /**
        An attribute 1.
    */
    string one;
    /**
        An attribute 2.
        nice.
    */
    int two;
};"""
UNION_DECLARATION = "union ClassName;"
UNION = """union ClassName switch (int8) {
};"""
UNION_ENUM = """union ClassName switch (mod::name::UnionTypeEnum) {
    case UnionTypeEnum_ONE:
        mode::name::One one;
    case UnionTypeEnum_STRING:
        string string;
};"""
UNION_ENUM_NOTES = """/**
    A struct.
*/
union ClassName switch (mod::name::UnionTypeEnum) {
    case UnionTypeEnum_ONE:
        /**
            An attribute 1.
        */
        mode::name::One one;
    case UnionTypeEnum_STRING:
        /**
            An attribute 2.
            nice.
        */
        string string;
};"""


def test_empty_class() -> None:
    idl = template("idl/gen_class.jinja2")
    cls = m_class()
    # We don't set any of is_* to true, we should get nothing
    mod = m_module()
    mod.classes = [cls]
    ret = idl.module.gen_class_definition(mod, cls)
    assert ret == ""
    ret = idl.module.gen_class_declaration(mod, cls)
    assert ret == ""
    ret = idl.module.gen_class_definition_full(mod, cls)
    assert ret == ""


def test_gen_union() -> None:
    idl = template("idl/gen_union.jinja2")
    cls = m_class()
    cls.is_union = True
    ret = idl.module.gen_union_declaration(cls)
    assert ret == UNION_DECLARATION
    ret = idl.module.gen_union_definition(cls)
    print(ret)
    assert ret == UNION
    cls.union_enum = "mod::name::UnionTypeEnum"
    cls.attributes = [
        m_attr(
            name="one",
            namespace=["mode", "name"],
            type="One",
            union_key="UnionTypeEnum_ONE",
        ),
        m_attr(name="string", type="string", union_key="UnionTypeEnum_STRING"),
    ]
    ret = idl.module.gen_union_definition(cls)
    print(ret)
    assert ret == UNION_ENUM
    cls.notes = "A struct."
    cls.attributes[0].notes = "An attribute 1."
    cls.attributes[1].notes = "An attribute 2.\nnice."
    ret = idl.module.gen_union_definition(cls)
    print(ret)
    assert ret == UNION_ENUM_NOTES


def test_gen_union_class() -> None:
    idl = template("idl/gen_class.jinja2")
    cls = m_class()
    cls.is_union = True

    cls.union_enum = "mod::name::UnionTypeEnum"
    cls.attributes = [
        m_attr(
            name="one",
            namespace=["mode", "name"],
            type="One",
            union_key="UnionTypeEnum_ONE",
        ),
        m_attr(name="string", type="string", union_key="UnionTypeEnum_STRING"),
    ]
    mod = m_module()
    mod.classes = [cls]
    ret = idl.module.gen_class_definition(mod, cls)
    assert ret == UNION_ENUM


def test_gen_struct() -> None:
    idl = template("idl/gen_struct.jinja2")
    cls = m_class()
    cls.attributes = [m_attr(name="one", type="string"), m_attr(name="two", type="int")]
    mod = m_module()
    mod.classes = [cls]
    ret = idl.module.gen_struct_declaration(mod, cls)
    assert ret == STRUCT_DECLARATION
    ret = idl.module.gen_struct_definition(mod, cls)
    assert ret == STRUCT
    cls.notes = "A struct."
    ret = idl.module.gen_struct_declaration(mod, cls)
    assert ret == STRUCT_DECLARATION
    ret = idl.module.gen_struct_definition(mod, cls)
    assert ret == STRUCT_NOTES
    cls.attributes[0].notes = "An attribute 1."
    cls.attributes[1].notes = "An attribute 2.\nnice."
    ret = idl.module.gen_struct_definition(mod, cls)
    assert ret == STRUCT_ATTR_NOTES


def test_gen_struct_class() -> None:
    idl = template("idl/gen_class.jinja2")
    cls = m_class()
    cls.is_struct = True
    cls.notes = "A struct."
    cls.attributes = [m_attr(name="one", type="string"), m_attr(name="two", type="int")]
    mod = m_module()
    mod.classes = [cls]
    ret = idl.module.gen_class_definition(mod, cls)
    assert ret == STRUCT_NOTES
    ret = idl.module.gen_class_declaration(mod, cls)
    assert ret == STRUCT_DECLARATION
    ret = idl.module.gen_class_definition_full(mod, cls)
    assert ret == STRUCT_NOTES


def test_gen_typedef() -> None:
    idl = template("idl/gen_typedef.jinja2")
    cls = m_class()
    cls.parent_type = "string"
    cls.is_typedef = True
    ret = idl.module.gen_typedef(cls)
    assert ret == TYPEDEF


def test_gen_typedef_class() -> None:
    # Typedef is generated for class definition (and when we generate full)
    cls = m_class()
    cls.parent_type = "string"
    cls.is_typedef = True
    mod = m_module()
    mod.classes = [cls]
    idl = template("idl/gen_class.jinja2")
    ret = idl.module.gen_class_definition(mod, cls)
    assert ret == ""
    ret = idl.module.gen_class_declaration(mod, cls)
    assert ret == TYPEDEF
    ret = idl.module.gen_class_definition_full(mod, cls)
    assert ret == TYPEDEF
    cls.notes = "A typedef."
    ret = idl.module.gen_class_definition(mod, cls)
    assert ret == ""
    ret = idl.module.gen_class_declaration(mod, cls)
    assert ret == TYPEDEF_NOTES
    ret = idl.module.gen_class_definition_full(mod, cls)
    assert ret == TYPEDEF_NOTES


def test_gen_enum() -> None:
    idl = template("idl/gen_enum.jinja2")
    ret = idl.module.gen_enum(m_class())
    assert ret == "enum ClassName {\n};"
    ret = idl.module.gen_enum(m_class(notes="An enum."))
    assert ret == "/**\n    An enum.\n*/\nenum ClassName {\n};"
    cls = m_class()
    cls.attributes.append(m_attr(name="one"))
    cls.attributes.append(m_attr(name="two"))
    cls.is_enum = True
    mod = m_module()
    mod.classes = [cls]
    ret = idl.module.gen_enum(cls)
    assert ret == ENUM
    cls.notes = "An enum."
    cls.attributes[0].notes = "An attribute 1."
    cls.attributes[1].notes = "An attribute 2.\nnice."
    ret = idl.module.gen_enum(cls)
    assert ret == ENUM_ATTR_NOTES


def test_gen_enum_class() -> None:
    cls = m_class()
    cls.attributes.append(m_attr(name="one"))
    cls.attributes.append(m_attr(name="two"))
    cls.is_enum = True
    mod = m_module()
    mod.classes = [cls]
    idl = template("idl/gen_class.jinja2")
    ret = idl.module.gen_class_definition(mod, cls)
    assert ret == ""
    ret = idl.module.gen_class_declaration(mod, cls)
    assert ret == ENUM
    ret = idl.module.gen_class_definition_full(mod, cls)
    assert ret == ENUM
    cls.notes = "An enum."
    ret = idl.module.gen_class_definition(mod, cls)
    assert ret == ""
    ret = idl.module.gen_class_declaration(mod, cls)
    assert ret == ENUM_NOTES
    ret = idl.module.gen_class_definition_full(mod, cls)
    assert ret == ENUM_NOTES


@pytest.mark.parametrize(
    "annotations,expected",
    [
        ({}, ""),  # No properties
        ({"name": ModelAnnotation(note="A note", value_type="str", value="value")}, "@name(value)\n"),
        (
            {
                "name": ModelAnnotation(note="A note", value_type="str", value="value"),
                "optional": ModelAnnotation(value_type="none"),
            },
            "@name(value)\n@optional\n",
        ),
    ],
)
def test_gen_annotations(annotations, expected) -> None:
    """Test annotation generation with various inputs."""
    idl = template("idl/gen_annotations.jinja2")
    ret = idl.module.gen_annotations(annotations)
    assert ret == expected


@pytest.mark.parametrize(
    "notes,expected",
    [
        (None, ""),  # None returns empty string
        ("", ""),  # Empty notes return empty string
        ("A line.", """/**\n    A line.\n*/\n"""),  # Notes with text
    ],
)
def test_gen_notes(notes, expected) -> None:
    """Test note generation with various inputs."""
    idl = template("idl/gen_notes.jinja2")
    ret = idl.module.gen_notes(cls=m_class(notes=notes))
    assert ret == expected


@pytest.mark.parametrize(
    "entity_type,notes,expected_declaration,expected_definition",
    [
        # Typedef without notes
        ("typedef", None, TYPEDEF, TYPEDEF),
        # Typedef with notes
        ("typedef", "A typedef.", TYPEDEF_NOTES, TYPEDEF_NOTES),
        # Enum without notes
        ("enum", None, ENUM, ENUM),
        # Enum with notes
        ("enum", "An enum.", ENUM_NOTES, ENUM_NOTES),
        # Struct without notes (declaration only, no definition for this test)
        ("struct", None, STRUCT_DECLARATION, None),
        # Struct with notes (declaration only)
        ("struct", "A struct.", STRUCT_DECLARATION, None),
    ],
)
def test_gen_class_declaration_with_notes(entity_type, notes, expected_declaration, expected_definition) -> None:
    """Test class declaration/definition generation with and without notes."""
    idl = template("idl/gen_class.jinja2")
    mod = m_module()

    if entity_type == "typedef":
        cls = m_class(notes=notes)
        cls.parent_type = "string"
        cls.is_typedef = True
        mod.classes = [cls]

        assert idl.module.gen_class_declaration(mod, cls) == expected_declaration
        assert idl.module.gen_class_definition_full(mod, cls) == expected_definition

    elif entity_type == "enum":
        cls = m_class(notes=notes)
        cls.attributes.append(m_attr(name="one"))
        cls.attributes.append(m_attr(name="two"))
        cls.is_enum = True
        mod.classes = [cls]

        assert idl.module.gen_class_declaration(mod, cls) == expected_declaration
        assert idl.module.gen_class_definition_full(mod, cls) == expected_definition

    elif entity_type == "struct":
        cls = m_class(notes=notes)
        cls.is_struct = True
        cls.attributes = [m_attr(name="one", type="string"), m_attr(name="two", type="int")]
        mod.classes = [cls]

        assert idl.module.gen_class_declaration(mod, cls) == expected_declaration


@pytest.mark.parametrize(
    "template_name,setup_fn,expected_empty",
    [
        ("idl/gen_enum.jinja2", lambda cls: setattr(cls, "is_enum", True), "enum ClassName {\n};"),
        ("idl/gen_union.jinja2", lambda cls: setattr(cls, "is_union", True), UNION),
    ],
)
def test_gen_template_empty(template_name, setup_fn, expected_empty) -> None:
    """Test template generation for empty entities."""
    idl = template(template_name)
    cls = m_class()
    setup_fn(cls)

    if "enum" in template_name:
        ret = idl.module.gen_enum(cls)
    elif "union" in template_name:
        ret = idl.module.gen_union_definition(cls)

    assert ret == expected_empty
