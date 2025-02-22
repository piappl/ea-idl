from eaidl.config import Configuration
from eaidl.model import ModelClass
from eaidl.utils import is_camel_case
from .base import validator, RESERVED_NAMES


def context(cls: ModelClass) -> str:
    return f"(in {".".join(cls.namespace)}.{cls.name})"


@validator
def name_for_reserved_worlds(config: Configuration, cls: ModelClass) -> None:
    if cls.name in RESERVED_NAMES:
        raise ValueError(f"Class name is on reserved world list {context(cls)}")


@validator
def name_camel_convention(config: Configuration, cls: ModelClass):
    if not is_camel_case(cls.name):
        raise ValueError(f"Class name has wrong case, expected camel case {context(cls)}")


@validator
def stereotypes(config: Configuration, cls: ModelClass):
    # Check if we have one of proper stereotypes on all P7
    if config.stereotypes.main_class in cls.stereotypes:
        count = 0
        if config.stereotypes.idl_union in cls.stereotypes:
            if cls.is_union is not True:
                raise ValueError(f"Class doesn't have proper is_union flag {context(cls)}")
            count += 1
        if config.stereotypes.idl_struct in cls.stereotypes:
            if cls.is_struct is not True:
                raise ValueError(f"Class doesn't have proper is_struct flag {context(cls)}")
            count += 1
        if config.stereotypes.idl_enum in cls.stereotypes:
            if cls.is_enum is not True:
                raise ValueError(f"Class doesn't have proper is_enum flag {context(cls)}")
            count += 1
        if config.stereotypes.idl_typedef in cls.stereotypes:
            if cls.is_typedef is not True:
                raise ValueError(f"Class doesn't have proper is_typedef flag {context(cls)}")
            count += 1
        if config.stereotypes.idl_map in cls.stereotypes:
            if cls.is_map is not True:
                raise ValueError(f"Class doesn't have proper is_map flag {context(cls)}")
            count += 1
        if count != 1:
            raise ValueError(f"Class doesn't have proper stereotypes {cls.stereotypes} {context(cls)}")


@validator
def enum_prefix(config: Configuration, cls: ModelClass):
    # We prefix enumerations (to make sure those are unique)
    if config.stereotypes.main_class in cls.stereotypes and config.stereotypes.idl_enum in cls.stereotypes:
        for attribute in cls.attributes:
            if attribute.name is None:
                raise ValueError(f"No name in enumeration {cls.name} attribute {context(cls)}")
            if not attribute.name.startswith(cls.name):
                raise ValueError(f"No prefix in enumeration {cls.name} attribute {context(cls)}")


@validator
def notes(config: Configuration, cls: ModelClass):
    if cls.notes is None or cls.notes.strip() == "":
        raise ValueError(f"Class '{cls.name}' has no description/comment/notes {context(cls)}")


@validator
def enum_attributes(config: Configuration, cls: ModelClass):
    if config.stereotypes.idl_enum not in cls.stereotypes:
        # We run this only for enums
        return

    # Check if enumeration attributes have same type
    types = set([attr.type for attr in cls.attributes])
    if len(types) != 1:
        # We should have a set (which has only unique items) with none
        raise ValueError(f"Enumeration needs to have no types {types} {context(cls)}")
    # Check default values (if set) are unique
    values = []
    for attr in cls.attributes:
        default = attr.properties.get("default")
        if default is None:
            continue
        values.append(default.value)
    count = len(cls.attributes)
    if len(values) != 0 and count != len(set(values)):
        raise ValueError(
            f"We expected to have values that match attributes numbers and all unique {context(cls)} {values}"
        )
