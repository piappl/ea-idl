# type: ignore
# Ignore types because we are calling methods on jinja2 modules.
# Those don't have types.

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
) -> ModelAttribute:
    return ModelAttribute(
        name=name,
        attribute_id=attribute_id,
        namespace=namespace,
        type=type,
        guid=str(uuid.uuid4),
        notes=notes,
        union_key=union_key,
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
        mode::name::One a_one;
    case UnionTypeEnum_STRING:
        string a_string;
};"""
UNION_ENUM_NOTES = """/**
    A struct.
*/
union ClassName switch (mod::name::UnionTypeEnum) {
    case UnionTypeEnum_ONE:
        /**
            An attribute 1.
        */
        mode::name::One a_one;
    case UnionTypeEnum_STRING:
        /**
            An attribute 2.
            nice.
        */
        string a_string;
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
            name="a_one",
            namespace=["mode", "name"],
            type="One",
            union_key="UnionTypeEnum_ONE",
        ),
        m_attr(name="a_string", type="string", union_key="UnionTypeEnum_STRING"),
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
            name="a_one",
            namespace=["mode", "name"],
            type="One",
            union_key="UnionTypeEnum_ONE",
        ),
        m_attr(name="a_string", type="string", union_key="UnionTypeEnum_STRING"),
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


def test_gen_annotations() -> None:
    idl = template("idl/gen_annotations.jinja2")
    ret = idl.module.gen_annotations({})
    assert ret == ""  # No properties
    ret = idl.module.gen_annotations({"name": ModelAnnotation(note="A note", value_type="str", value="value")})
    assert ret == "@name(value)\n"
    ret = idl.module.gen_annotations(
        {
            "name": ModelAnnotation(note="A note", value_type="str", value="value"),
            "optional": ModelAnnotation(value_type="none"),
        }
    )
    assert ret == "@name(value)\n@optional\n"


def test_gen_notes() -> None:
    idl = template("idl/gen_notes.jinja2")
    ret = idl.module.gen_notes(cls=m_class())
    assert ret == ""  # None return empty string
    ret = idl.module.gen_notes(cls=m_class(notes=""))
    assert ret == ""  # Empty notes return empty string
    ret = idl.module.gen_notes(cls=m_class(notes="A line."))
    assert ret == """/**\n    A line.\n*/\n"""
