import uuid
import pytest
from eaidl.transforms import (
    convert_map_stereotype,
    filter_stereotypes,
    filter_empty_unions,
    find_class,
    find_unused_classes,
    filter_unused_classes,
    flatten_abstract_classes,
    resolve_typedef_defaults,
)
from eaidl.model import ModelClass, ModelPackage, ModelAttribute, ModelConnection, ModelAnnotation
from eaidl.config import Configuration
from eaidl.generate import render


def test_convert_map_stereotype() -> None:
    config = Configuration(template="idl_just_defs.jinja2")
    mod = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))
    # Create three classes:
    # * struct (ClassName) - it has a field that is of type ClassMap
    # * map (ClassMap)
    # * typedef (ClassTypedef)
    # All are in module root,
    cls_1 = ModelClass(
        name="ClassName",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=1,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )
    cls_2 = ModelClass(
        name="ClassMap",
        stereotypes=[config.stereotypes.idl_map],
        object_id=2,
        namespace=["root"],
        is_map=True,
        parent=mod,
    )
    cls_3 = ModelClass(
        name="ClassTypedef",
        parent_type="string",
        stereotypes=[config.stereotypes.idl_typedef],
        object_id=3,
        namespace=["root"],
        is_typedef=True,
        parent=mod,
    )
    # It normally will be ordered after load
    mod.classes = [cls_3, cls_2, cls_1]
    map_attr = ModelAttribute(
        name="mapped",
        alias="mapped",
        parent=cls_1,
        type="ClassMap",
        guid=str(uuid.uuid4()),
        attribute_id=10,
        namespace=["root"],
        connector=ModelConnection(
            connector_id=0,
            connector_type="Association",
            start_object_id=1,
            end_object_id=2,
        ),
    )
    cls_1.attributes.append(map_attr)
    cls_2.attributes.append(
        ModelAttribute(
            name="key",
            alias="key",
            parent=cls_2,
            type="string",
            guid=str(uuid.uuid4()),
            attribute_id=12,
            namespace=[],
        )
    )
    cls_2.attributes.append(
        ModelAttribute(
            name="value",
            alias="value",
            parent=cls_2,
            type="ClassTypedef",
            guid=str(uuid.uuid4()),
            attribute_id=12,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=0,
                connector_type="Association",
                start_object_id=2,
                end_object_id=3,
            ),
        )
    )
    convert_map_stereotype([mod], config)
    # This produces something like this:
    # module ext {
    # }; /* ext */
    # module root {
    #     typedef string ClassTypedef;
    #     struct ClassName {
    #         map<string, root::ClassTypedef>;
    #         string name;
    #     };
    # }; /* root */
    assert "map<string, root::ClassTypedef>" in render(config, [mod])
    # After processing those are added to attribute
    assert map_attr.is_map is True
    assert map_attr.map_key_type == "string"
    assert map_attr.map_value_type == "root::ClassTypedef"


def test_filter_stereotypes() -> None:
    config = Configuration(template="idl_just_defs.jinja2")
    config.filter_stereotypes = ["lobw"]
    mod = ModelPackage(name="root", package_id=0, object_id=1, guid=str(uuid.uuid4()))
    cls_1 = ModelClass(
        name="ClassName",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=2,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )
    mod.classes = [cls_1]
    cls_1.attributes.append(
        ModelAttribute(
            name="attr_1",
            alias="attr_1",
            parent=cls_1,
            type="string",
            guid=str(uuid.uuid4()),
            attribute_id=12,
            stereotypes=["lobw"],
            namespace=[],
        )
    )
    cls_1.attributes.append(
        ModelAttribute(
            name="attr_2",
            alias="attr_2",
            parent=cls_1,
            type="ClassTypedef",
            guid=str(uuid.uuid4()),
            attribute_id=12,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=0,
                connector_type="Association",
                start_object_id=1,
                end_object_id=3,
            ),
        )
    )
    filter_stereotypes([mod], config)
    assert "attr_1" not in render(config, [mod])
    assert "attr_2" in render(config, [mod])


def build_union_structure(config: Configuration) -> ModelPackage:
    mod = ModelPackage(name="root", package_id=0, object_id=10, guid=str(uuid.uuid4()))
    cls_1 = ModelClass(
        name="ClassUnion",
        stereotypes=[config.stereotypes.idl_union],
        object_id=1,
        namespace=["root"],
        is_union=True,
        parent=mod,
    )
    cls_2 = ModelClass(
        name="ClassName2",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=2,
        namespace=["root"],
        is_struct=True,
        parent=mod,
        attributes=[
            ModelAttribute(
                name="attr_1",
                alias="attr_1",
                type="ClassUnion",
                attribute_id=22,
                guid=str(uuid.uuid4()),
                connector=ModelConnection(
                    connector_id=2,
                    connector_type="Association",
                    start_object_id=2,
                    end_object_id=1,
                ),
            )
        ],
    )
    cls_3 = ModelClass(
        name="ClassName3",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=3,
        namespace=["root", "child_1"],
        is_struct=True,
        parent=mod,
        attributes=[
            ModelAttribute(
                name="attr_1",
                alias="attr_1",
                type="ClassUnion",
                attribute_id=23,
                guid=str(uuid.uuid4()),
                connector=ModelConnection(
                    connector_id=3,
                    connector_type="Association",
                    start_object_id=3,
                    end_object_id=1,
                ),
            )
        ],
    )
    cls_4 = ModelClass(
        name="ClassName4",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=4,
        namespace=["root", "child_1"],
        is_struct=True,
        parent=mod,
        attributes=[
            ModelAttribute(
                name="attr_1",
                alias="attr_1",
                type="ClassUnion",
                attribute_id=24,
                guid=str(uuid.uuid4()),
                connector=ModelConnection(
                    connector_id=4,
                    connector_type="Association",
                    start_object_id=4,
                    end_object_id=1,
                ),
            )
        ],
    )
    mod1 = ModelPackage(name="child_1", package_id=1, object_id=11, guid=str(uuid.uuid4()))
    mod2 = ModelPackage(name="child_2", package_id=2, object_id=12, guid=str(uuid.uuid4()))
    # Note that order here matters (as we are not running sorting of deps in this test)
    mod.classes = [cls_2]
    mod.packages = [mod1, mod2]
    mod1.classes = [cls_1, cls_3]
    mod2.classes = [cls_4]
    return mod


def test_filter_empty_unions() -> None:
    config = Configuration(template="idl_just_defs.jinja2")
    mod = build_union_structure(config)
    # print(render(config, mod))
    # module root {
    #     module child_1 {
    #         union ClassUnion switch (int8) {
    #         };
    #         struct ClassName3 {
    #             ClassUnion attr_1;
    #         };
    #     }; /* child_1 */
    #     module child_2 {
    #         struct ClassName4 {
    #             ClassUnion attr_1;
    #         };
    #     }; /* child_2 */
    #     struct ClassName2 {
    #         ClassUnion attr_1;
    #     };
    # }; /* root */
    # All attributes should be removed - as union is empty
    filter_empty_unions([mod], config)
    assert "attr_1" not in render(config, [mod])
    assert "ClassUnion" not in render(config, [mod])


def test_filter_one_union_member() -> None:
    config = Configuration(template="idl_just_defs.jinja2")
    mod = build_union_structure(config)
    # This is similar to test for removing empty unions, but we add one member
    un = find_class([mod], lambda c: c.object_id == 1)
    assert un is not None
    assert un.attributes is not None
    un.attributes = [
        ModelAttribute(name="member", alias="member", type="string", attribute_id=123, guid=str(uuid.uuid4()))
    ]
    print(render(config, [mod]))
    filter_empty_unions([mod], config)
    assert "ClassUnion" not in render(config, [mod])
    print(render(config, [mod]))


def test_find_unused_classes() -> None:
    """Test finding unused classes based on root property."""
    config = Configuration(template="idl_just_defs.jinja2")
    mod = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create a root class marked with ext::interface
    root_cls = ModelClass(
        name="RootClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=1,
        namespace=["root"],
        is_struct=True,
        parent=mod,
        properties={"ext::interface": ModelAnnotation(value_type="none", value=None)},
    )

    # Create a used class (referenced by root)
    used_cls = ModelClass(
        name="UsedClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=2,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    # Create an unused class (not referenced by anyone)
    unused_cls = ModelClass(
        name="UnusedClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=3,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    # Root class has an attribute referencing UsedClass
    root_cls.attributes.append(
        ModelAttribute(
            name="used_field",
            alias="used_field",
            parent=root_cls,
            type="UsedClass",
            guid=str(uuid.uuid4()),
            attribute_id=10,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=0,
                connector_type="Association",
                start_object_id=1,
                end_object_id=2,
            ),
        )
    )

    mod.classes = [root_cls, used_cls, unused_cls]

    # Find unused classes
    unused = find_unused_classes([mod], config, "ext::interface")

    # Should find only UnusedClass
    assert len(unused) == 1
    assert unused[0].name == "UnusedClass"


def test_find_unused_classes_with_inheritance() -> None:
    """Test that classes referenced via inheritance are marked as used."""
    config = Configuration(template="idl_just_defs.jinja2")
    mod = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create a root class marked with ext::interface
    root_cls = ModelClass(
        name="RootClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=1,
        namespace=["root"],
        is_struct=True,
        parent=mod,
        properties={"ext::interface": ModelAnnotation(value_type="none", value=None)},
        generalization=["root", "BaseClass"],
    )

    # Create a base class (used via inheritance)
    base_cls = ModelClass(
        name="BaseClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=2,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    # Create an unused class
    unused_cls = ModelClass(
        name="UnusedClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=3,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    mod.classes = [root_cls, base_cls, unused_cls]

    # Find unused classes
    unused = find_unused_classes([mod], config, "ext::interface")

    # Should find only UnusedClass (BaseClass is used via inheritance)
    assert len(unused) == 1
    assert unused[0].name == "UnusedClass"


def test_filter_unused_classes() -> None:
    """Test removing unused classes from the model."""
    config = Configuration(template="idl_just_defs.jinja2")
    mod = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create a root class marked with ext::interface
    root_cls = ModelClass(
        name="RootClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=1,
        namespace=["root"],
        is_struct=True,
        parent=mod,
        properties={"ext::interface": ModelAnnotation(value_type="none", value=None)},
    )

    # Create a used class
    used_cls = ModelClass(
        name="UsedClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=2,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    # Create an unused class
    unused_cls = ModelClass(
        name="UnusedClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=3,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    # Root class references UsedClass
    root_cls.attributes.append(
        ModelAttribute(
            name="used_field",
            alias="used_field",
            parent=root_cls,
            type="UsedClass",
            guid=str(uuid.uuid4()),
            attribute_id=10,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=0,
                connector_type="Association",
                start_object_id=1,
                end_object_id=2,
            ),
        )
    )

    mod.classes = [root_cls, used_cls, unused_cls]

    # Filter unused classes (remove=True)
    unused = filter_unused_classes([mod], config, "ext::interface", remove=True)

    # Should have found and removed UnusedClass
    assert len(unused) == 1
    assert unused[0].name == "UnusedClass"

    # Check that it was actually removed from the model
    assert len(mod.classes) == 2
    assert "UnusedClass" not in [cls.name for cls in mod.classes]
    assert "RootClass" in [cls.name for cls in mod.classes]
    assert "UsedClass" in [cls.name for cls in mod.classes]

    # Verify output doesn't contain UnusedClass
    output = render(config, [mod])
    assert "UnusedClass" not in output
    assert "RootClass" in output
    assert "UsedClass" in output


def test_find_unused_classes_transitive_dependencies() -> None:
    """Test that transitive dependencies are correctly tracked."""
    config = Configuration(template="idl_just_defs.jinja2")
    mod = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create root -> A -> B -> C chain
    root_cls = ModelClass(
        name="Root",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=1,
        namespace=["root"],
        is_struct=True,
        parent=mod,
        properties={"ext::interface": ModelAnnotation(value_type="none", value=None)},
    )

    cls_a = ModelClass(
        name="ClassA",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=2,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    cls_b = ModelClass(
        name="ClassB",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=3,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    cls_c = ModelClass(
        name="ClassC",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=4,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    unused_cls = ModelClass(
        name="Unused",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=5,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    # Root -> A
    root_cls.attributes.append(
        ModelAttribute(
            name="field_a",
            alias="field_a",
            parent=root_cls,
            type="ClassA",
            guid=str(uuid.uuid4()),
            attribute_id=10,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=10,
                connector_type="Association",
                start_object_id=1,
                end_object_id=2,
            ),
        )
    )

    # A -> B
    cls_a.attributes.append(
        ModelAttribute(
            name="field_b",
            alias="field_b",
            parent=cls_a,
            type="ClassB",
            guid=str(uuid.uuid4()),
            attribute_id=11,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=11,
                connector_type="Association",
                start_object_id=2,
                end_object_id=3,
            ),
        )
    )

    # B -> C
    cls_b.attributes.append(
        ModelAttribute(
            name="field_c",
            alias="field_c",
            parent=cls_b,
            type="ClassC",
            guid=str(uuid.uuid4()),
            attribute_id=12,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=12,
                connector_type="Association",
                start_object_id=3,
                end_object_id=4,
            ),
        )
    )

    mod.classes = [root_cls, cls_a, cls_b, cls_c, unused_cls]

    # Find unused classes
    unused = find_unused_classes([mod], config, "ext::interface")

    # Only Unused should be unused; A, B, C are all transitively used
    assert len(unused) == 1
    assert unused[0].name == "Unused"


def test_find_unused_classes_union_enum_preserved() -> None:
    """Test that enums linked to unions are preserved as used."""
    config = Configuration(template="idl_just_defs.jinja2")
    mod = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create a root class marked with ext::interface that uses a union
    root_cls = ModelClass(
        name="RootClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=1,
        namespace=["root"],
        is_struct=True,
        parent=mod,
        properties={"ext::interface": ModelAnnotation(value_type="none", value=None)},
    )

    # Create a union class
    union_cls = ModelClass(
        name="MyUnion",
        stereotypes=[config.stereotypes.idl_union],
        object_id=2,
        namespace=["root"],
        is_union=True,
        parent=mod,
        union_enum="root::MyUnionTypeEnum",  # Full qualified name
    )

    # Create the enum used by the union
    enum_cls = ModelClass(
        name="MyUnionTypeEnum",
        stereotypes=[config.stereotypes.idl_enum],
        object_id=3,
        namespace=["root"],
        is_enum=True,
        parent=mod,
    )

    # Create an unused class
    unused_cls = ModelClass(
        name="UnusedClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=4,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    # Root references the union
    root_cls.attributes.append(
        ModelAttribute(
            name="union_field",
            alias="union_field",
            parent=root_cls,
            type="MyUnion",
            guid=str(uuid.uuid4()),
            attribute_id=10,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=0,
                connector_type="Association",
                start_object_id=1,
                end_object_id=2,
            ),
        )
    )

    mod.classes = [root_cls, union_cls, enum_cls, unused_cls]

    # Find unused classes
    unused = find_unused_classes([mod], config, "ext::interface")

    # Only UnusedClass should be unused
    # The enum should be preserved because it's linked to the union via union_enum
    assert len(unused) == 1
    assert unused[0].name == "UnusedClass"

    # Verify the enum is NOT in the unused list
    assert "MyUnionTypeEnum" not in [cls.name for cls in unused]


def test_find_unused_classes_values_enum_preserved() -> None:
    """Test that enums linked via <<values>> are preserved as used."""
    config = Configuration(template="idl_just_defs.jinja2")
    mod = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create a root class marked with ext::interface
    root_cls = ModelClass(
        name="RootClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=1,
        namespace=["root"],
        is_struct=True,
        parent=mod,
        properties={"ext::interface": ModelAnnotation(value_type="none", value=None)},
    )

    # Create a struct class with a <<values>> relationship
    struct_with_values = ModelClass(
        name="FlexibleName",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=2,
        namespace=["root"],
        is_struct=True,
        parent=mod,
        values_enums=["root::FlexibleNameValues"],  # Full qualified name
    )

    # Create the enum used for values
    values_enum_cls = ModelClass(
        name="FlexibleNameValues",
        stereotypes=[config.stereotypes.idl_enum],
        object_id=3,
        namespace=["root"],
        is_enum=True,
        parent=mod,
    )

    # Create an unused class
    unused_cls = ModelClass(
        name="UnusedClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=4,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )

    # Root references the struct with values
    root_cls.attributes.append(
        ModelAttribute(
            name="flexible_field",
            alias="flexible_field",
            parent=root_cls,
            type="FlexibleName",
            guid=str(uuid.uuid4()),
            attribute_id=10,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=0,
                connector_type="Association",
                start_object_id=1,
                end_object_id=2,
            ),
        )
    )

    mod.classes = [root_cls, struct_with_values, values_enum_cls, unused_cls]

    # Find unused classes
    unused = find_unused_classes([mod], config, "ext::interface")

    # Only UnusedClass should be unused
    # The values enum should be preserved because it's linked via values_enums
    assert len(unused) == 1
    assert unused[0].name == "UnusedClass"

    # Verify the values enum is NOT in the unused list
    assert "FlexibleNameValues" not in [cls.name for cls in unused]


def test_flatten_simple_abstract_inheritance(test_config, create_package, struct_class, create_attribute) -> None:
    """Test flattening a single level of abstract inheritance."""
    Configuration(template="idl_just_defs.jinja2")
    mod = create_package(name="root", package_id=0, object_id=0)

    # Create abstract parent
    abstract_parent = struct_class(
        name="AbstractMessageHeader",
        object_id=1,
        is_abstract=True,
        parent=mod,
    )
    abstract_parent.attributes.append(
        create_attribute(
            name="timestamp",
            parent=abstract_parent,
            type="Time",
            attribute_id=10,
            namespace=["root"],
        )
    )

    # Create concrete child
    concrete_child = struct_class(
        name="MessageHeader",
        object_id=2,
        is_abstract=False,
        parent=mod,
        generalization=["root", "AbstractMessageHeader"],
    )
    concrete_child.attributes.append(
        create_attribute(
            name="message_type",
            parent=concrete_child,
            type="MessageTypeEnum",
            attribute_id=11,
            namespace=["root"],
        )
    )

    mod.classes = [abstract_parent, concrete_child]

    # Flatten
    flatten_abstract_classes([mod])

    # Verify abstract parent was removed
    assert len(mod.classes) == 1
    assert mod.classes[0].name == "MessageHeader"

    # Verify concrete child has both attributes in correct order
    child = mod.classes[0]
    assert len(child.attributes) == 2
    assert child.attributes[0].name == "timestamp"
    assert child.attributes[1].name == "message_type"

    # Verify generalization was removed
    assert child.generalization is None

    # Verify abstract parent is NOT in depends_on (since it won't exist in output)
    assert abstract_parent.object_id not in child.depends_on


def test_flatten_multi_level_abstract_inheritance(test_config, create_package, struct_class, create_attribute) -> None:
    """Test flattening multiple levels of abstract inheritance."""
    Configuration(template="idl_just_defs.jinja2")
    mod = create_package(name="root", package_id=0, object_id=0)

    # Create abstract grandparent
    abstract_grandparent = struct_class(
        name="AbstractBase",
        object_id=1,
        is_abstract=True,
        parent=mod,
    )
    abstract_grandparent.attributes.append(
        create_attribute(
            name="base_field",
            parent=abstract_grandparent,
            type="string",
            attribute_id=10,
            namespace=["root"],
        )
    )

    # Create abstract parent
    abstract_parent = struct_class(
        name="AbstractMiddle",
        object_id=2,
        is_abstract=True,
        parent=mod,
        generalization=["root", "AbstractBase"],
    )
    abstract_parent.attributes.append(
        create_attribute(
            name="middle_field",
            parent=abstract_parent,
            type="string",
            attribute_id=11,
            namespace=["root"],
        )
    )

    # Create concrete child
    concrete_child = struct_class(
        name="ConcreteClass",
        object_id=3,
        is_abstract=False,
        parent=mod,
        generalization=["root", "AbstractMiddle"],
    )
    concrete_child.attributes.append(
        create_attribute(
            name="concrete_field",
            parent=concrete_child,
            type="string",
            attribute_id=12,
            namespace=["root"],
        )
    )

    mod.classes = [abstract_grandparent, abstract_parent, concrete_child]

    # Flatten
    flatten_abstract_classes([mod])

    # Verify all abstract classes removed
    assert len(mod.classes) == 1
    assert mod.classes[0].name == "ConcreteClass"

    # Verify concrete child has all attributes from chain in correct order
    child = mod.classes[0]
    assert len(child.attributes) == 3
    assert child.attributes[0].name == "base_field"
    assert child.attributes[1].name == "middle_field"
    assert child.attributes[2].name == "concrete_field"


def test_flatten_mixed_concrete_and_abstract_inheritance(
    test_config, create_package, struct_class, create_attribute
) -> None:
    """Test inheritance where parent is concrete (not abstract)."""
    Configuration(template="idl_just_defs.jinja2")
    mod = create_package(name="root", package_id=0, object_id=0)

    # Create concrete parent
    concrete_parent = struct_class(
        name="ConcreteBase",
        object_id=1,
        is_abstract=False,
        parent=mod,
    )
    concrete_parent.attributes.append(
        create_attribute(
            name="base_field",
            parent=concrete_parent,
            type="string",
            attribute_id=10,
            namespace=["root"],
        )
    )

    # Create concrete child inheriting from concrete parent
    concrete_child = struct_class(
        name="ConcreteChild",
        object_id=2,
        is_abstract=False,
        parent=mod,
        generalization=["root", "ConcreteBase"],
    )
    concrete_child.attributes.append(
        create_attribute(
            name="child_field",
            parent=concrete_child,
            type="string",
            attribute_id=11,
            namespace=["root"],
        )
    )

    mod.classes = [concrete_parent, concrete_child]

    # Flatten
    flatten_abstract_classes([mod])

    # Both classes should remain (parent is concrete)
    assert len(mod.classes) == 2
    parent_result = find_class([mod], lambda c: c.name == "ConcreteBase")
    child_result = find_class([mod], lambda c: c.name == "ConcreteChild")
    assert parent_result is not None
    assert child_result is not None

    # Child should keep generalization (parent is concrete)
    assert child_result.generalization == ["root", "ConcreteBase"]

    # Child should not have flattened attributes (parent is concrete, not abstract)
    assert len(child_result.attributes) == 1
    assert child_result.attributes[0].name == "child_field"


def test_flatten_multiple_children_of_abstract(test_config, create_package, struct_class, create_attribute) -> None:
    """Test that multiple children each get independent copies of attributes."""
    Configuration(template="idl_just_defs.jinja2")
    mod = create_package(name="root", package_id=0, object_id=0)

    # Create abstract parent
    abstract_parent = struct_class(
        name="AbstractBase",
        object_id=1,
        is_abstract=True,
        parent=mod,
    )
    abstract_parent.attributes.append(
        create_attribute(
            name="base_field",
            parent=abstract_parent,
            type="string",
            attribute_id=10,
            namespace=["root"],
        )
    )

    # Create two concrete children
    child1 = struct_class(
        name="Child1",
        object_id=2,
        is_abstract=False,
        parent=mod,
        generalization=["root", "AbstractBase"],
    )
    child1.attributes.append(
        create_attribute(
            name="child1_field",
            parent=child1,
            type="string",
            attribute_id=11,
            namespace=["root"],
        )
    )

    child2 = struct_class(
        name="Child2",
        object_id=3,
        is_abstract=False,
        parent=mod,
        generalization=["root", "AbstractBase"],
    )
    child2.attributes.append(
        create_attribute(
            name="child2_field",
            parent=child2,
            type="string",
            attribute_id=12,
            namespace=["root"],
        )
    )

    mod.classes = [abstract_parent, child1, child2]

    # Flatten
    flatten_abstract_classes([mod])

    # Verify abstract parent removed
    assert len(mod.classes) == 2

    # Verify both children have independent copies
    result_child1 = find_class([mod], lambda c: c.name == "Child1")
    result_child2 = find_class([mod], lambda c: c.name == "Child2")

    assert result_child1 is not None and len(result_child1.attributes) == 2
    assert result_child2 is not None and len(result_child2.attributes) == 2

    # Modify one child's attributes and verify other is unaffected
    result_child1.attributes[0].name = "modified"
    assert result_child2.attributes[0].name == "base_field"


def test_flatten_abstract_as_field_type_validation() -> None:
    """Test that using abstract class as field type raises validation error."""
    config = Configuration(template="idl_just_defs.jinja2")
    mod = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create abstract class
    abstract_cls = ModelClass(
        name="AbstractType",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=1,
        namespace=["root"],
        is_struct=True,
        is_abstract=True,
        parent=mod,
    )

    # Create concrete class with attribute referencing abstract class
    concrete_cls = ModelClass(
        name="ConcreteClass",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=2,
        namespace=["root"],
        is_struct=True,
        is_abstract=False,
        parent=mod,
    )
    concrete_cls.attributes.append(
        ModelAttribute(
            name="abstract_field",
            alias="abstract_field",
            parent=concrete_cls,
            type="AbstractType",
            guid=str(uuid.uuid4()),
            attribute_id=10,
            namespace=["root"],
            connector=ModelConnection(
                connector_id=0,
                connector_type="Association",
                start_object_id=2,
                end_object_id=1,
            ),
        )
    )

    mod.classes = [abstract_cls, concrete_cls]

    # Should raise ValueError about abstract type reference
    with pytest.raises(ValueError, match="references abstract class"):
        flatten_abstract_classes([mod])


def test_flatten_attribute_name_conflict(test_config, create_package, struct_class, create_attribute) -> None:
    """Test that attribute name conflicts raise validation error."""
    Configuration(template="idl_just_defs.jinja2")
    mod = create_package(name="root", package_id=0, object_id=0)

    # Create abstract parent
    abstract_parent = struct_class(
        name="AbstractBase",
        object_id=1,
        is_abstract=True,
        parent=mod,
    )
    abstract_parent.attributes.append(
        create_attribute(
            name="shared_field",  # Same name as child
            parent=abstract_parent,
            type="string",
            attribute_id=10,
            namespace=["root"],
        )
    )

    # Create concrete child with conflicting attribute name
    concrete_child = struct_class(
        name="ConcreteChild",
        object_id=2,
        is_abstract=False,
        parent=mod,
        generalization=["root", "AbstractBase"],
    )
    concrete_child.attributes.append(
        create_attribute(
            name="shared_field",  # Conflicts with parent
            parent=concrete_child,
            type="string",
            attribute_id=11,
            namespace=["root"],
        )
    )

    mod.classes = [abstract_parent, concrete_child]

    # Should raise ValueError about conflict
    with pytest.raises(ValueError, match="Attribute name conflict"):
        flatten_abstract_classes([mod])


def test_flatten_nested_packages(test_config, create_package, struct_class, create_attribute) -> None:
    """Test flattening works correctly with nested packages."""
    Configuration(template="idl_just_defs.jinja2")
    root_pkg = create_package(name="root", package_id=0, object_id=0)
    child_pkg = create_package(name="child", package_id=1, object_id=1)
    root_pkg.packages = [child_pkg]

    # Create abstract parent in child package
    abstract_parent = struct_class(
        name="AbstractBase",
        object_id=2,
        namespace=["root", "child"],
        is_abstract=True,
        parent=child_pkg,
    )
    abstract_parent.attributes.append(
        create_attribute(
            name="base_field",
            parent=abstract_parent,
            type="string",
            attribute_id=10,
            namespace=["root", "child"],
        )
    )

    # Create concrete child in child package
    concrete_child = struct_class(
        name="ConcreteClass",
        object_id=3,
        namespace=["root", "child"],
        is_abstract=False,
        parent=child_pkg,
        generalization=["root", "child", "AbstractBase"],
    )
    concrete_child.attributes.append(
        create_attribute(
            name="concrete_field",
            parent=concrete_child,
            type="string",
            attribute_id=11,
            namespace=["root", "child"],
        )
    )

    child_pkg.classes = [abstract_parent, concrete_child]

    # Flatten
    flatten_abstract_classes([root_pkg])

    # Verify flattening worked in nested package
    assert len(child_pkg.classes) == 1
    assert child_pkg.classes[0].name == "ConcreteClass"
    assert len(child_pkg.classes[0].attributes) == 2


class TestTransformsEdgeCases:
    """Test edge cases and error paths in transforms."""

    def test_convert_map_stereotype_empty_package(self, test_config, create_package):
        """Test map stereotype conversion on empty package."""
        config = Configuration(template="idl_just_defs.jinja2")
        pkg = create_package(name="Empty", classes=[])
        root = [pkg]
        convert_map_stereotype(root, config)
        # Should not crash on empty package
        assert len(pkg.classes) == 0

    def test_filter_stereotypes_no_matches(self, test_config, struct_class, create_package):
        """Test stereotype filtering when no classes match."""
        config = Configuration(template="idl_just_defs.jinja2")
        config.filter_stereotypes = ["some_non_existent_stereotype"]
        pkg = create_package(name="Test", classes=[struct_class(name="Struct1")])
        root = [pkg]

        filter_stereotypes(root, config)

        # Struct should remain (no filter matches)
        assert len(pkg.classes) == 1

    def test_filter_empty_unions_empty_package(self, test_config, create_package):
        """Test empty union filtering on empty package."""
        config = Configuration(template="idl_just_defs.jinja2")
        pkg = create_package(name="Test", classes=[])
        root = [pkg]

        filter_empty_unions(root, config)

        # Should not crash
        assert len(pkg.classes) == 0

    def test_filter_empty_unions_non_union_classes(self, test_config, struct_class, create_package):
        """Test empty union filtering ignores non-union classes."""
        config = Configuration(template="idl_just_defs.jinja2")
        struct = struct_class(name="Struct1", attributes=[])
        pkg = create_package(name="Test", classes=[struct])
        root = [pkg]

        filter_empty_unions(root, config)

        # Struct should remain (not a union)
        assert len(pkg.classes) == 1

    def test_find_class_not_found(self, create_package):
        """Test finding class by condition when it doesn't exist."""
        pkg = create_package(name="Test")
        root = [pkg]

        result = find_class(root, lambda c: c.name == "NonExistent")
        assert result is None

    def test_find_unused_classes_empty_package(self, create_package):
        """Test finding unused classes in empty package."""
        config = Configuration(template="idl_just_defs.jinja2")
        pkg = create_package(name="Test", classes=[])
        root = [pkg]

        unused = find_unused_classes(root, config, "ext::interface")

        assert unused == []

    def test_flatten_abstract_classes_no_abstract(self, test_config, struct_class, create_package):
        """Test flattening when no abstract classes exist."""
        Configuration(template="idl_just_defs.jinja2")
        concrete = struct_class(name="Concrete", object_id=1, is_abstract=False)
        pkg = create_package(name="Test", classes=[concrete])
        root = [pkg]

        flatten_abstract_classes(root)

        # Nothing should change
        assert len(pkg.classes) == 1
        assert pkg.classes[0].name == "Concrete"


def test_filter_empty_unions_with_keep_stereotype() -> None:
    """Test that <<keep>> stereotype preserves empty unions when collapse_by_default=True."""
    config = Configuration(
        template="idl_just_defs.jinja2",
        collapse_empty_unions_by_default=True,
        keep_union_stereotype="keep",
    )

    # Create an empty union with <<keep>> stereotype
    pkg = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))
    empty_union = ModelClass(
        name="EmptyUnion",
        stereotypes=[config.stereotypes.idl_union, "keep"],
        object_id=1,
        namespace=["root"],
        is_union=True,
        parent=pkg,
        attributes=[],
    )
    pkg.classes = [empty_union]

    filter_empty_unions([pkg], config)

    # Union should be preserved due to <<keep>> stereotype
    assert len(pkg.classes) == 1
    assert pkg.classes[0].name == "EmptyUnion"


def test_filter_empty_unions_collapse_by_default() -> None:
    """Test that empty unions are collapsed by default when collapse_by_default=True."""
    config = Configuration(
        template="idl_just_defs.jinja2",
        collapse_empty_unions_by_default=True,
    )

    # Create an empty union without <<keep>> stereotype
    pkg = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))
    empty_union = ModelClass(
        name="EmptyUnion",
        stereotypes=[config.stereotypes.idl_union],
        object_id=1,
        namespace=["root"],
        is_union=True,
        parent=pkg,
        attributes=[],
    )
    pkg.classes = [empty_union]

    filter_empty_unions([pkg], config)

    # Union should be removed (collapsed)
    assert len(pkg.classes) == 0


def test_filter_empty_unions_keep_by_default() -> None:
    """Test that empty unions are kept by default when collapse_by_default=False."""
    config = Configuration(
        template="idl_just_defs.jinja2",
        collapse_empty_unions_by_default=False,
        collapse_union_stereotype="collapse",
    )

    # Create an empty union without <<collapse>> stereotype
    pkg = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))
    empty_union = ModelClass(
        name="EmptyUnion",
        stereotypes=[config.stereotypes.idl_union],
        object_id=1,
        namespace=["root"],
        is_union=True,
        parent=pkg,
        attributes=[],
    )
    pkg.classes = [empty_union]

    filter_empty_unions([pkg], config)

    # Union should be preserved (kept by default)
    assert len(pkg.classes) == 1
    assert pkg.classes[0].name == "EmptyUnion"


def test_filter_empty_unions_with_collapse_stereotype() -> None:
    """Test that <<collapse>> stereotype removes empty unions when collapse_by_default=False."""
    config = Configuration(
        template="idl_just_defs.jinja2",
        collapse_empty_unions_by_default=False,
        collapse_union_stereotype="collapse",
    )

    # Create an empty union with <<collapse>> stereotype
    pkg = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))
    empty_union = ModelClass(
        name="EmptyUnion",
        stereotypes=[config.stereotypes.idl_union, "collapse"],
        object_id=1,
        namespace=["root"],
        is_union=True,
        parent=pkg,
        attributes=[],
    )
    pkg.classes = [empty_union]

    filter_empty_unions([pkg], config)

    # Union should be removed due to <<collapse>> stereotype
    assert len(pkg.classes) == 0


def test_resolve_typedef_defaults_string_typedef() -> None:
    """Test that defaults for string typedef attributes are quoted as strings."""
    config = Configuration(template="idl_just_defs.jinja2")

    pkg = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create a string typedef
    version_typedef = ModelClass(
        name="Version",
        stereotypes=[config.stereotypes.idl_typedef],
        object_id=10,
        namespace=["root"],
        is_typedef=True,
        parent_type="string",
    )

    # Create a struct with an attribute of that typedef type, with a default
    struct = ModelClass(
        name="MyStruct",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=20,
        namespace=["root"],
        is_struct=True,
        attributes=[
            ModelAttribute(
                name="schema_version",
                alias="schema_version",
                type="Version",
                attribute_id=1,
                guid=str(uuid.uuid4()),
                namespace=["root"],
                properties={
                    "default": ModelAnnotation(value="01.00", value_type="object"),
                },
            ),
        ],
    )

    pkg.classes = [version_typedef, struct]

    resolve_typedef_defaults([pkg], config)

    default_ann = struct.attributes[0].properties["default"]
    assert default_ann.value_type == "str"
    assert default_ann.value == '"01.00"'


def test_resolve_typedef_defaults_int_typedef() -> None:
    """Test that defaults for int typedef attributes are resolved to int type."""
    config = Configuration(template="idl_just_defs.jinja2")

    pkg = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create an int typedef
    counter_typedef = ModelClass(
        name="Counter",
        stereotypes=[config.stereotypes.idl_typedef],
        object_id=10,
        namespace=["root"],
        is_typedef=True,
        parent_type="int",
    )

    struct = ModelClass(
        name="MyStruct",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=20,
        namespace=["root"],
        is_struct=True,
        attributes=[
            ModelAttribute(
                name="count",
                alias="count",
                type="Counter",
                attribute_id=1,
                guid=str(uuid.uuid4()),
                namespace=["root"],
                properties={
                    "default": ModelAnnotation(value="42", value_type="object"),
                },
            ),
        ],
    )

    pkg.classes = [counter_typedef, struct]

    resolve_typedef_defaults([pkg], config)

    default_ann = struct.attributes[0].properties["default"]
    assert default_ann.value_type == "int"
    assert default_ann.value == "42"


def test_resolve_typedef_defaults_enum_typedef_unchanged() -> None:
    """Test that defaults for non-primitive typedefs (e.g. enum) are not changed."""
    config = Configuration(template="idl_just_defs.jinja2")

    pkg = ModelPackage(name="root", package_id=0, object_id=0, guid=str(uuid.uuid4()))

    # Create a typedef that references a non-primitive type (not in primitive_types)
    custom_typedef = ModelClass(
        name="MyType",
        stereotypes=[config.stereotypes.idl_typedef],
        object_id=10,
        namespace=["root"],
        is_typedef=True,
        parent_type="SomeEnum",
    )

    struct = ModelClass(
        name="MyStruct",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=20,
        namespace=["root"],
        is_struct=True,
        attributes=[
            ModelAttribute(
                name="my_field",
                alias="my_field",
                type="MyType",
                attribute_id=1,
                guid=str(uuid.uuid4()),
                namespace=["root"],
                properties={
                    "default": ModelAnnotation(value="SOME_VALUE", value_type="object"),
                },
            ),
        ],
    )

    pkg.classes = [custom_typedef, struct]

    resolve_typedef_defaults([pkg], config)

    default_ann = struct.attributes[0].properties["default"]
    assert default_ann.value_type == "object"
    assert default_ann.value == "SOME_VALUE"
