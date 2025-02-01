"""Some methods that transform model into something else."""

from typing import Optional

from eaidl.model import ModelPackage, ModelClass, ModelAttribute
from eaidl.config import Configuration


def find_class(root: ModelPackage, target_object_id: int) -> Optional[ModelClass]:
    for cls in root.classes:
        if cls.object_id == target_object_id:
            return cls
    for pkg in root.packages:
        sub = find_class(pkg, target_object_id)
        if sub is not None:
            return sub
    return None


def attr_by_name(cls: ModelClass, name: str) -> ModelAttribute:
    for attr in cls.attributes:
        if attr.name == name:
            return attr
    raise AttributeError(f"Attribute {name} not found on class {cls.name}")


def _convert_map_stereotype(
    root: ModelPackage,
    current: ModelPackage,
    config: Configuration,
) -> None:
    for cls in current.classes:
        for attr in cls.attributes:
            if attr.connector is not None:
                # It can be none for primitive types
                dest = find_class(root, attr.connector.end_object_id)
                if dest is None:
                    raise AttributeError(f"End not found for attribute {attr.name}")
                if config.stereotypes.idl_map in dest.stereotypes:
                    attr.is_map = True
                    k = attr_by_name(dest, config.stereotypes.idl_map_key)
                    v = attr_by_name(dest, config.stereotypes.idl_map_value)
                    attr.is_map = True
                    if k.type is not None:
                        attr.map_key_type = "::".join(k.namespace + [k.type])
                    if v.type is not None:
                        attr.map_value_type = "::".join(v.namespace + [v.type])

    for pkg in current.packages:
        _convert_map_stereotype(root, pkg, config)


def convert_map_stereotype(
    root: ModelPackage,
    config: Configuration,
) -> None:
    """Walks through model and adds stuff needed for using maps.

    :param root: model root package
    :param config: configuration
    """
    _convert_map_stereotype(root, root, config)
