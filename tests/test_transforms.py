import uuid
from eaidl.transforms import convert_map_stereotype, filter_stereotypes, filter_empty_unions, find_class
from eaidl.model import ModelClass, ModelPackage, ModelAttribute, ModelConnection
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
    convert_map_stereotype(mod, config)
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
    assert "map<string, root::ClassTypedef>" in render(config, mod)
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
    filter_stereotypes(mod, config)
    assert "attr_1" not in render(config, mod)
    assert "attr_2" in render(config, mod)


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
    filter_empty_unions(mod, config)
    assert "attr_1" not in render(config, mod)
    assert "ClassUnion" not in render(config, mod)


def test_filter_one_union_member() -> None:
    config = Configuration(template="idl_just_defs.jinja2")
    mod = build_union_structure(config)
    # This is similar to test for removing empty unions, but we add one member
    un = find_class(mod, lambda c: c.object_id == 1)
    assert un is not None
    assert un.attributes is not None
    un.attributes = [ModelAttribute(name="a_member", type="string", attribute_id=123, guid=str(uuid.uuid4()))]
    print(render(config, mod))
    filter_empty_unions(mod, config)
    assert "ClassUnion" not in render(config, mod)
    print(render(config, mod))
