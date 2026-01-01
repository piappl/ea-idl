from typing import Optional, List
import logging
from jinja2 import Environment, PackageLoader, select_autoescape
from eaidl.load import ModelPackage
from eaidl.config import Configuration
from eaidl.transforms import (
    convert_map_stereotype,
    filter_stereotypes,
    filter_empty_unions,
    filter_unused_classes,
    flatten_abstract_classes,
)

log = logging.getLogger(__name__)


def create_env(config: Optional[Configuration] = None) -> Environment:
    """Create jinja2 environment.

    :param config: configuration, defaults to None
    :return: environment
    """
    env = Environment(
        loader=PackageLoader("eaidl"),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
    # Make config available as a global variable in all templates
    if config:
        env.globals["config"] = config
        # Add filter for mapping EA types to IDL types
        env.filters["idl_type"] = config.get_idl_type
    return env


def render(config: Configuration, packages: List[ModelPackage]) -> str:
    env = create_env(config)
    template = env.get_template(config.template)
    return template.render(packages=packages, config=config)


def generate(config: Configuration, packages: List[ModelPackage]) -> str:
    if config.enable_maps:
        convert_map_stereotype(packages, config)
    # Flatten abstract classes before filtering stereotypes
    # This ensures abstract class attributes are merged into concrete classes
    # before any stereotype-based filtering happens
    if config.flatten_abstract_classes:
        flatten_abstract_classes(packages)
    if config.filter_stereotypes is not None:
        filter_stereotypes(packages, config)
        filter_empty_unions(packages, config)
    if config.filter_unused_classes:
        filter_unused_classes(packages, config, config.unused_root_property, remove=True)

    # Note: Cycle detection and forward declaration marking now happens
    # during load time (in ModelParser.package_parse_children) to allow
    # topological sorting to proceed with valid circular dependencies.

    return render(config, packages)
