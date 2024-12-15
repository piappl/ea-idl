from jinja2 import Environment, PackageLoader, select_autoescape
from eaidl.load import ModelPackage
from eaidl.utils import Configuration
# from rich import inspect


def generate(config: Configuration, model: ModelPackage) -> None:
    env = Environment(loader=PackageLoader("eaidl"), autoescape=select_autoescape())
    # inspect(model)
    template = env.get_template("idl.jinja2")
    ret = template.render(package=model)
    print(ret)
