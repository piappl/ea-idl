from jinja2 import Environment, PackageLoader, select_autoescape
from eaidl.load import ModelPackage
from eaidl.config import Configuration
# from rich import inspect


def generate(config: Configuration, model: ModelPackage) -> str:
    env = Environment(
        loader=PackageLoader("eaidl"), autoescape=select_autoescape(), trim_blocks=True, lstrip_blocks=True
    )
    template = env.get_template("idl.jinja2")
    return template.render(package=model)
