from eaidl.config import Configuration
from eaidl.model import ModelPackage
from eaidl.utils import is_lower_snake_case
from .base import validator


def context(package: ModelPackage) -> str:
    return f"(in {".".join(package.namespace)})"


@validator
def name_snake_convention(config: Configuration, package: ModelPackage):
    if not is_lower_snake_case(package.name):
        raise ValueError(f"Package {package.name} has wrong case, expected lower snake case: {context(package)}")


@validator
def stereotypes(config: Configuration, package: ModelPackage):
    if config.stereotypes.package not in package.stereotypes:
        raise ValueError(
            f"Package {package.name} has wrong stereotypes, found {package.stereotypes} expected {config.stereotypes.package} {context(package)}"
        )


@validator
def notes(config: Configuration, package: ModelPackage):
    if package.notes is None or package.notes.strip() == "":
        raise ValueError(f"Package {package.name} has no description/comment/notes {context(package)}")
