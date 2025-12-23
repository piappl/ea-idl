"""Tests for model.py helper methods."""

from eaidl.model import ModelClass, ModelPackage


def test_model_class_full_name():
    """Test ModelClass.full_name property."""
    cls = ModelClass(name="Foo", namespace=["root", "bar"], object_id=1)
    assert cls.full_name == "root::bar::Foo"


def test_model_class_full_name_no_namespace():
    """Test ModelClass.full_name with empty namespace."""
    cls = ModelClass(name="Foo", namespace=[], object_id=1)
    assert cls.full_name == "Foo"


def test_model_class_has_stereotype():
    """Test ModelClass.has_stereotype method."""
    cls = ModelClass(name="Foo", object_id=1, stereotypes=["struct", "experimental"])
    assert cls.has_stereotype("struct")
    assert cls.has_stereotype("experimental")
    assert not cls.has_stereotype("enum")
    assert not cls.has_stereotype("typedef")


def test_model_class_has_stereotype_empty():
    """Test ModelClass.has_stereotype with no stereotypes."""
    cls = ModelClass(name="Foo", object_id=1, stereotypes=[])
    assert not cls.has_stereotype("struct")


def test_model_class_is_enum_type(test_config):
    """Test ModelClass.is_enum_type method."""
    enum_cls = ModelClass(name="Color", object_id=1, stereotypes=[test_config.stereotypes.idl_enum])
    struct_cls = ModelClass(name="Person", object_id=2, stereotypes=[test_config.stereotypes.idl_struct])

    assert enum_cls.is_enum_type(test_config)
    assert not struct_cls.is_enum_type(test_config)


def test_model_class_is_struct_type(test_config):
    """Test ModelClass.is_struct_type method."""
    struct_cls = ModelClass(name="Person", object_id=1, stereotypes=[test_config.stereotypes.idl_struct])
    enum_cls = ModelClass(name="Color", object_id=2, stereotypes=[test_config.stereotypes.idl_enum])

    assert struct_cls.is_struct_type(test_config)
    assert not enum_cls.is_struct_type(test_config)


def test_model_class_is_union_type(test_config):
    """Test ModelClass.is_union_type method."""
    union_cls = ModelClass(name="Result", object_id=1, stereotypes=[test_config.stereotypes.idl_union])
    struct_cls = ModelClass(name="Person", object_id=2, stereotypes=[test_config.stereotypes.idl_struct])

    assert union_cls.is_union_type(test_config)
    assert not struct_cls.is_union_type(test_config)


def test_model_package_full_namespace():
    """Test ModelPackage.full_namespace property."""
    pkg = ModelPackage(name="service", package_id=1, object_id=1, guid="test-guid", namespace=["root", "api", "v1"])
    assert pkg.full_namespace == "root::api::v1"


def test_model_package_full_namespace_empty():
    """Test ModelPackage.full_namespace with empty namespace."""
    pkg = ModelPackage(name="root", package_id=1, object_id=1, guid="test-guid", namespace=[])
    assert pkg.full_namespace == ""
