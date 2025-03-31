"""Some methods that transform model into something else."""

import logging
from typing import Optional, Callable, List

from eaidl.model import ModelPackage, ModelClass, ModelAttribute
from eaidl.config import Configuration

log = logging.getLogger(__name__)


def find_class(roots: List[ModelPackage], condition: Callable[[ModelClass], bool]) -> Optional[ModelClass]:
    for root in roots:
        for cls in root.classes:
            if condition(cls):
                return cls
        for pkg in root.packages:
            sub = find_class([pkg], condition)
            if sub is not None:
                return sub
    return None


def remove_attr(root: ModelPackage, condition: Callable[[ModelAttribute], bool]) -> None:
    for cls in root.classes:
        for attr in cls.attributes[:]:
            if condition(attr):
                cls.attributes.remove(attr)
    for pkg in root.packages:
        remove_attr(pkg, condition)


def get_attrs(root: ModelPackage, condition: Callable[[ModelAttribute], bool]) -> List[ModelAttribute]:
    attrs = []
    for cls in root.classes:
        for attr in cls.attributes[:]:
            if condition(attr):
                attrs.append(attr)
    for pkg in root.packages:
        attrs += get_attrs(pkg, condition)
    return attrs


def attr_by_name(cls: ModelClass, name: str) -> ModelAttribute:
    for attr in cls.attributes:
        if attr.name == name:
            return attr
    raise AttributeError(f"Attribute {name} not found on class {cls.name}")


def _convert_map_stereotype(
    root: List[ModelPackage],
    current: ModelPackage,
    config: Configuration,
) -> None:
    for cls in current.classes:
        for attr in cls.attributes:
            if attr.connector is not None:
                # It can be none for primitive types
                dest = find_class(root, lambda c: c.object_id == attr.connector.end_object_id)  # type: ignore
                if dest is None:
                    raise AttributeError(f"End not found for attribute {'::'.join(attr.namespace)}.{attr.name}")
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
    packages: List[ModelPackage],
    config: Configuration,
) -> None:
    """Walks through model and adds stuff needed for using maps.

    :param root: model root package
    :param config: configuration
    """
    for package in packages:
        _convert_map_stereotype(packages, package, config)


def _filter_stereotypes(root: ModelPackage, current: ModelPackage, config: Configuration) -> None:
    if config.filter_stereotypes is None:
        return
    for filter in config.filter_stereotypes:
        for cls in current.classes[:]:
            # Fist try to remove whole classes tagged with stereotypes that
            # is configured to be removed.
            if filter in cls.stereotypes:
                log.warning("Filtering class based on stereotype " + "::".join(cls.namespace + [cls.name]))
                current.classes.remove(cls)
                # Not we still have to remove all attributes that reference it...
                remove_attr(
                    root,
                    lambda a: a.connector is not None and a.connector.end_object_id == cls.object_id,
                )
    for filter in config.filter_stereotypes:
        for cls in current.classes:
            # Now we look at remaining attributes, and remove those tagged
            for attr in cls.attributes[:]:
                for filter in config.filter_stereotypes:
                    if filter in attr.stereotypes:
                        log.warning(
                            "Filtering attribute based on stereotype "
                            + "::".join(cls.namespace + [cls.name])
                            + "."
                            + attr.name
                        )
                        cls.attributes.remove(attr)
    for pkg in current.packages[:]:
        for filter in config.filter_stereotypes:
            if filter in pkg.stereotypes:
                current.packages.remove(pkg)
    for pkg in current.packages:
        _filter_stereotypes(root, pkg, config)


def filter_stereotypes(
    packages: List[ModelPackage],
    config: Configuration,
) -> None:
    """Walks through model filters out attributes with configured stereotypes.

    :param root: model root package
    :param config: configuration
    """
    for package in packages:
        _filter_stereotypes(package, package, config)


def _filter_empty_unions(roots: List[ModelPackage], current: ModelPackage, config: Configuration) -> None:
    for cls in current.classes[:]:
        if config.keep_union_stereotype in cls.stereotypes:
            continue
        if cls.is_union and (cls.attributes is None or len(cls.attributes) == 0):
            # This is empty union
            for root in roots:
                remove_attr(
                    root,
                    lambda a: a.connector is not None and a.connector.end_object_id == cls.object_id,
                )
            current.classes.remove(cls)
        elif cls.is_union and (cls.attributes is not None and len(cls.attributes) == 1):
            # This is union of one element, two way to go, we can replace with
            # primitive or other class
            for root in roots:
                attrs = get_attrs(
                    root,
                    lambda a: a.connector is not None and a.connector.end_object_id == cls.object_id,
                )
                if cls.attributes[0].connector is None:
                    # Primitive
                    for attr in attrs:
                        attr.type = cls.attributes[0].type
                        attr.namespace = cls.attributes[0].namespace
                        attr.connector = None
                else:
                    for attr in attrs:
                        attr.type = cls.attributes[0].type
                        attr.namespace = cls.attributes[0].namespace
                        old = attr.connector
                        attr.connector = cls.attributes[0].connector
                        attr.connector.connector_id = old.connector_id  # type: ignore
                        attr.connector.start_object_id = old.start_object_id  # type: ignore
            current.classes.remove(cls)
    for pkg in current.packages:
        _filter_empty_unions(roots, pkg, config)


def filter_empty_unions(
    packages: List[ModelPackage],
    config: Configuration,
) -> None:
    """Walks through model filters unions that are empty or have one option.

    :param root: model root package
    :param config: configuration
    """
    for package in packages:
        _filter_empty_unions(packages, package, config)
