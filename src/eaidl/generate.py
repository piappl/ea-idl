from typing import Optional
from jinja2 import Environment, PackageLoader, select_autoescape
from eaidl.load import ModelPackage
from eaidl.config import Configuration
from eaidl.transforms import convert_map_stereotype


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


def generate(config: Configuration, model: ModelPackage) -> str:
    if config.enable_maps:
        convert_map_stereotype(model, config)
    env = create_env(config)
    template = env.get_template(config.template)
    return template.render(package=model)
