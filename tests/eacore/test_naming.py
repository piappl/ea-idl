from eacore.naming import column_key


def test_column_key_lowercases_and_prefixes():
    assert column_key("Object_ID") == "attr_object_id"
    assert column_key("object_id") == "attr_object_id"
    assert column_key("PDATA1") == "attr_pdata1"
