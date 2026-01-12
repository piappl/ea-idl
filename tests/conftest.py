"""Shared pytest fixtures for EA-IDL tests."""

import pytest
import uuid
from pathlib import Path
from eaidl.config import Configuration
from eaidl.model import ModelClass, ModelPackage, ModelAttribute
from eaidl.load import ModelParser


@pytest.fixture
def test_db_path():
    """Path to the test SQLite database."""
    return Path(__file__).parent / "data" / "nafv4.qea"


@pytest.fixture
def test_config(test_db_path):
    """Configuration object for tests using the test database."""
    config = Configuration()
    config.database_url = f"sqlite+pysqlite:///{test_db_path.as_posix()}"
    config.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    # Allow reserved words in tests to avoid breaking existing test data
    config.reserved_words_action = "allow"
    return config


@pytest.fixture(scope="module")
def model_parser(test_config):
    """ModelParser instance for loading test data."""
    return ModelParser(test_config)


@pytest.fixture(scope="module")
def parsed_model(model_parser):
    """Fully parsed model from test database."""
    return model_parser.load()


@pytest.fixture
def struct_class(test_config):
    """Factory for creating test struct classes.

    Usage:
        struct_class(name="TestStruct", object_id=1, is_abstract=True)
    """

    def _create(name="TestStruct", object_id=None, **kwargs):
        defaults = {
            "object_id": object_id or (hash(name) & 0xFFFFFFFF),
            "guid": str(uuid.uuid4()),
            "stereotypes": [test_config.stereotypes.idl_struct],
            "namespace": ["root"],
            "attributes": [],
        }
        return ModelClass(name=name, **{**defaults, **kwargs})

    return _create


@pytest.fixture
def enum_class(test_config):
    """Factory for creating test enum classes.

    Usage:
        enum_class(name="TestEnum", object_id=1)
    """

    def _create(name="TestEnum", object_id=None, **kwargs):
        defaults = {
            "object_id": object_id or (hash(name) & 0xFFFFFFFF),
            "guid": str(uuid.uuid4()),
            "stereotypes": [test_config.stereotypes.idl_enum],
            "namespace": ["root"],
            "attributes": [],
        }
        return ModelClass(name=name, **{**defaults, **kwargs})

    return _create


@pytest.fixture
def typedef_class(test_config):
    """Factory for creating test typedef classes.

    Usage:
        typedef_class(name="TestTypedef", parent_type="string")
    """

    def _create(name="TestTypedef", object_id=None, **kwargs):
        defaults = {
            "object_id": object_id or (hash(name) & 0xFFFFFFFF),
            "guid": str(uuid.uuid4()),
            "stereotypes": [test_config.stereotypes.idl_typedef],
            "namespace": ["root"],
            "attributes": [],
        }
        return ModelClass(name=name, **{**defaults, **kwargs})

    return _create


@pytest.fixture
def union_class(test_config):
    """Factory for creating test union classes.

    Usage:
        union_class(name="TestUnion", object_id=1)
    """

    def _create(name="TestUnion", object_id=None, **kwargs):
        defaults = {
            "object_id": object_id or (hash(name) & 0xFFFFFFFF),
            "guid": str(uuid.uuid4()),
            "stereotypes": [test_config.stereotypes.idl_union],
            "namespace": ["root"],
            "attributes": [],
        }
        return ModelClass(name=name, **{**defaults, **kwargs})

    return _create


@pytest.fixture
def create_package():
    """Factory for creating test packages.

    Usage:
        create_package(name="TestPkg", classes=[cls1, cls2])
    """

    def _create(name="TestPkg", object_id=None, **kwargs):
        defaults = {
            "package_id": object_id or (hash(name) & 0xFFFFFFFF),
            "object_id": object_id or (hash(name) & 0xFFFFFFFF),
            "guid": str(uuid.uuid4()),
            "namespace": [],
            "packages": [],
            "classes": [],
        }
        return ModelPackage(name=name, **{**defaults, **kwargs})

    return _create


@pytest.fixture
def create_attribute():
    """Factory for creating test attributes.

    Usage:
        create_attribute(name="test_attr", type="string", attribute_id=1)
    """

    def _create(name="test_attr", attribute_id=None, **kwargs):
        defaults = {
            "alias": name,
            "attribute_id": attribute_id or (hash(name) & 0xFFFFFFFF),
            "guid": str(uuid.uuid4()),
        }
        return ModelAttribute(name=name, **{**defaults, **kwargs})

    return _create


# Shared utility functions
def flatten_packages(packages):
    """Recursively flatten package hierarchy into a flat list."""
    result = []
    for pkg in packages:
        result.append(pkg)
        result.extend(flatten_packages(pkg.packages))
    return result


def collect_all_depends_on(packages):
    """Collect all dependencies recursively from packages and classes."""
    result = []
    for pkg in packages:
        result.extend(pkg.depends_on)
        result.extend(collect_all_depends_on(pkg.packages))
        for cls in pkg.classes:
            result.extend(cls.depends_on)
    return result


def collect_all_class_ids(packages):
    """Collect all class IDs recursively from packages."""
    result = []
    for pkg in packages:
        result.extend([cls.object_id for cls in pkg.classes])
        result.extend(collect_all_class_ids(pkg.packages))
    return result
