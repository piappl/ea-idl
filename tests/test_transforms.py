import uuid
from eaidl.transforms import convert_map_stereotype
from eaidl.model import ModelClass, ModelPackage, ModelAttribute, ModelConnection
from eaidl.config import Configuration
from eaidl.generate import generate


def test_convert_map_stereotype() -> None:
    config = Configuration(template="idl_just_defs.jinja2")
    mod = ModelPackage(name="root", package_id=0, object_id=1, guid=str(uuid.uuid4()))
    cls_1 = ModelClass(
        name="ClassName",
        stereotypes=[config.stereotypes.idl_struct],
        object_id=2,
        namespace=["root"],
        is_struct=True,
        parent=mod,
    )
    cls_2 = ModelClass(
        name="ClassMap",
        stereotypes=[config.stereotypes.idl_map],
        object_id=3,
        namespace=["root"],
        is_map=True,
        parent=mod,
    )
    cls_3 = ModelClass(
        name="ClassTypedef",
        parent_type="string",
        stereotypes=[config.stereotypes.idl_typedef],
        object_id=4,
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
        connector=ModelConnection(connector_id=0, connector_type="Association", start_object_id=2, end_object_id=3),
    )
    cls_1.attributes.append(map_attr)
    cls_1.attributes.append(
        ModelAttribute(
            name="name",
            parent=cls_1,
            type="string",
            guid=str(uuid.uuid4()),
            attribute_id=11,
            namespace=[],
        )
    )
    cls_2.attributes.append(
        ModelAttribute(
            name="key",
            parent=cls_1,
            type="string",
            guid=str(uuid.uuid4()),
            attribute_id=12,
            namespace=[],
        )
    )
    cls_2.attributes.append(
        ModelAttribute(
            name="value",
            parent=cls_1,
            type="ClassTypedef",
            guid=str(uuid.uuid4()),
            attribute_id=12,
            namespace=["root"],
            connector=ModelConnection(connector_id=0, connector_type="Association", start_object_id=1, end_object_id=3),
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
    assert "map<string, root::ClassTypedef>" in generate(config, mod)
    assert map_attr.is_map is True
    assert map_attr.map_key_type == "string"
    assert map_attr.map_value_type == "root::ClassTypedef"
