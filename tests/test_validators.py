import pytest
import uuid
from typing import Optional
from eaidl import validation as v
from eaidl.config import Configuration
from eaidl.model import ModelAttribute, ModelClass


def m_attr(name: str = "attr", attribute_id: int = 0, type: Optional[str] = None) -> ModelAttribute:
    return ModelAttribute(name=name, alias=name, attribute_id=attribute_id, type=type, guid=str(uuid.uuid4))


def m_class(name: str = "cls", object_id: int = 0) -> ModelClass:
    return ModelClass(name=name, object_id=object_id)


def test_attribute_name_for_reserved_worlds() -> None:
    with pytest.raises(ValueError):
        v.attribute.name_for_reserved_worlds(
            Configuration(validators_fail=["attribute.name_for_reserved_worlds"]),
            attribute=m_attr(name="from"),
            cls=m_class(),
        )
    # This will not run test, validators are disabled
    v.attribute.name_for_reserved_worlds(
        Configuration(validators_fail=[]),
        attribute=m_attr(name="from"),
        cls=m_class(),
    )
    # Correct output
    v.attribute.name_for_reserved_worlds(
        Configuration(validators_fail=[]),
        attribute=m_attr(name="from_a"),
        cls=m_class(),
    )


def test_attribute_connector_leads_to_type() -> None:
    with pytest.raises(ValueError):
        v.attribute.connector_leads_to_type(
            Configuration(validators_fail=["attribute.connector_leads_to_type"]),
            attribute=m_attr(name="from"),
            cls=m_class(),
        )
    # Will work for primitive
    v.attribute.connector_leads_to_type(
        Configuration(validators_fail=["attribute.connector_leads_to_type"]),
        attribute=m_attr(name="from", type="string"),
        cls=m_class(),
    )
