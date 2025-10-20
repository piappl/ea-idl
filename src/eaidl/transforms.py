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
                    raise AttributeError(
                        f"End not found for attribute {'::'.join(attr.namespace)}::{cls.name}.{attr.name}"
                    )
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


def _collect_used_classes(
    roots: List[ModelPackage],
    cls: ModelClass,
    used: set[int],
    config: Configuration,
) -> None:
    """Recursively collect all classes used by the given class.

    :param roots: root packages to search for referenced classes
    :param cls: class to analyze
    :param used: set of used class object_ids (mutated)
    :param config: configuration
    """
    if cls.object_id in used:
        return  # Already processed

    used.add(cls.object_id)

    # Process generalization (parent class)
    if cls.generalization:
        # generalization is a List[str] representing the namespace path
        # We need to find the parent class by name
        parent_name = cls.generalization[-1] if cls.generalization else None
        if parent_name:
            parent_cls = find_class(roots, lambda c: c.name == parent_name)
            if parent_cls:
                _collect_used_classes(roots, parent_cls, used, config)

    # Process all attributes
    for attr in cls.attributes:
        if attr.connector is not None:
            # This attribute references another class
            referenced = find_class(roots, lambda c: c.object_id == attr.connector.end_object_id)  # type: ignore
            if referenced:
                _collect_used_classes(roots, referenced, used, config)

        # Handle map types
        if attr.is_map and attr.map_key_type:
            # Map key might be a complex type
            key_type_name = attr.map_key_type.split("::")[-1]
            if key_type_name not in config.primitive_types:
                key_cls = find_class(roots, lambda c: c.name == key_type_name)
                if key_cls:
                    _collect_used_classes(roots, key_cls, used, config)

        if attr.is_map and attr.map_value_type:
            # Map value might be a complex type
            value_type_name = attr.map_value_type.split("::")[-1]
            if value_type_name not in config.primitive_types:
                value_cls = find_class(roots, lambda c: c.name == value_type_name)
                if value_cls:
                    _collect_used_classes(roots, value_cls, used, config)

    # Process union_enum if it exists
    if cls.union_enum:
        # union_enum is stored as a full qualified name like "core::data::EnumName"
        enum_name = cls.union_enum.split("::")[-1]
        enum_namespace = cls.union_enum.split("::")[:-1]
        enum_cls = find_class(roots, lambda c: c.name == enum_name and c.namespace == enum_namespace)
        if enum_cls:
            _collect_used_classes(roots, enum_cls, used, config)

    # Process values_enums if they exist
    if cls.values_enums:
        for values_enum_full_name in cls.values_enums:
            # values_enum is stored as a full qualified name like "core::data::EnumName"
            enum_name = values_enum_full_name.split("::")[-1]
            enum_namespace = values_enum_full_name.split("::")[:-1]
            enum_cls = find_class(roots, lambda c: c.name == enum_name and c.namespace == enum_namespace)
            if enum_cls:
                _collect_used_classes(roots, enum_cls, used, config)


def find_unused_classes(
    packages: List[ModelPackage],
    config: Configuration,
    root_property: str = "ext::interface",
) -> List[ModelClass]:
    """Find all classes that are not used by any root class.

    A root class is one marked with the specified property (default: ext::interface).
    A class is considered "used" if it's referenced directly or indirectly by a root class.

    :param packages: list of root packages
    :param config: configuration
    :param root_property: property name that marks root classes
    :return: list of unused classes
    """
    used_classes: set[int] = set()
    all_classes: List[ModelClass] = []

    # Collect all classes
    def collect_all_classes(pkg: ModelPackage) -> None:
        all_classes.extend(pkg.classes)
        for sub_pkg in pkg.packages:
            collect_all_classes(sub_pkg)

    for package in packages:
        collect_all_classes(package)

    # Find root classes (those marked with the root_property)
    root_classes = [cls for cls in all_classes if root_property in cls.properties]

    if not root_classes:
        log.warning(f"No root classes found with property '{root_property}'. All classes will be considered unused.")

    # Collect all classes used by root classes
    for root_cls in root_classes:
        _collect_used_classes(packages, root_cls, used_classes, config)

    # Find unused classes
    unused = [cls for cls in all_classes if cls.object_id not in used_classes]

    return unused


def _filter_unused_classes(
    root: ModelPackage,
    current: ModelPackage,
    unused_ids: set[int],
) -> None:
    """Remove unused classes from the model.

    :param root: root package (for removing attributes)
    :param current: current package being processed
    :param unused_ids: set of unused class object_ids
    """
    for cls in current.classes[:]:
        if cls.object_id in unused_ids:
            log.info(f"Removing unused class: {'::'.join(cls.namespace + [cls.name])}")
            current.classes.remove(cls)
            # Remove attributes that reference this class
            remove_attr(
                root,
                lambda a: a.connector is not None and a.connector.end_object_id == cls.object_id,
            )

    for pkg in current.packages:
        _filter_unused_classes(root, pkg, unused_ids)


def filter_unused_classes(
    packages: List[ModelPackage],
    config: Configuration,
    root_property: str = "ext::interface",
    remove: bool = True,
) -> List[ModelClass]:
    """Find and optionally remove unused classes from the model.

    :param packages: list of root packages
    :param config: configuration
    :param root_property: property name that marks root classes
    :param remove: if True, remove unused classes from the model
    :return: list of unused classes (before removal if remove=True)
    """
    unused = find_unused_classes(packages, config, root_property)

    if unused:
        log.warning(f"Found {len(unused)} unused classes:")
        for cls in unused:
            log.warning(f"  - {'::'.join(cls.namespace + [cls.name])}")

    if remove and unused:
        unused_ids = {cls.object_id for cls in unused}
        for package in packages:
            _filter_unused_classes(package, package, unused_ids)
        log.info(f"Removed {len(unused)} unused classes from model")

    return unused
