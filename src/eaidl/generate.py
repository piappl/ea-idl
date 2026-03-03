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
    resolve_typedef_defaults,
)

log = logging.getLogger(__name__)


def escape_idl_string(value: str) -> str:
    """Escape a string value for use in IDL string literals.

    IDL follows C-style escape sequences where backslashes must be escaped.
    If the value starts and ends with double quotes (string delimiters stored
    in the database), only escape content between the quotes, not the delimiters.

    :param value: string to escape
    :return: escaped string with backslashes escaped
    """
    if not isinstance(value, str):
        return value

    # Check if value starts and ends with quotes (stored delimiters)
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        # Extract content between quotes, escape it, then add quotes back
        content = value[1:-1]
        content = content.replace("\\", "\\\\")
        # Also escape any inner double quotes if present
        content = content.replace('"', '\\"')
        return f'"{content}"'
    else:
        # No stored delimiters, escape entire value
        value = value.replace("\\", "\\\\")
        value = value.replace('"', '\\"')
        return value


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
    # Add filter for escaping string values in IDL
    env.filters["escape_idl_string"] = escape_idl_string
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

    # Resolve default values for string typedef attributes so they are
    # not rendered as qualified object references
    resolve_typedef_defaults(packages, config)

    return render(config, packages)
