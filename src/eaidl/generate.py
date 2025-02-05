from typing import Optional, List
from jinja2 import Environment, PackageLoader, select_autoescape
from eaidl.load import ModelPackage
from eaidl.config import Configuration
from eaidl.transforms import convert_map_stereotype, filter_stereotypes, filter_empty_unions


def create_env(config: Optional[Configuration] = None) -> Environment:
    """Create jinja2 environment.

    :param config: configuration, defaults to None
    :return: environment
    """
    return Environment(
        loader=PackageLoader("eaidl"),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )


def render(config: Configuration, packages: List[ModelPackage]) -> str:
    env = create_env(config)
    template = env.get_template(config.template)
    return template.render(packages=packages)


def generate(config: Configuration, packages: List[ModelPackage]) -> str:
    if config.enable_maps:
        convert_map_stereotype(packages, config)
    if config.filter_stereotypes is not None:
        filter_stereotypes(packages, config)
        filter_empty_unions(packages, config)
    return render(config, packages)
