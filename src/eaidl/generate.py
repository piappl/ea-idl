from typing import Optional
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


def render(config: Configuration, model: ModelPackage) -> str:
    env = create_env(config)
    template = env.get_template(config.template)
    return template.render(package=model)


def generate(config: Configuration, model: ModelPackage) -> str:
    if config.enable_maps:
        convert_map_stereotype(model, config)
    if config.filter_stereotypes is not None:
        filter_stereotypes(model, config)
        filter_empty_unions(model, config)
    return render(config, model)
