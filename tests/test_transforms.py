import uuid
from eaidl.transforms import (
    convert_map_stereotype,
    filter_stereotypes,
    filter_empty_unions,
    find_class,
    find_unused_classes,
    filter_unused_classes,
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
