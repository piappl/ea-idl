from eaidl.utils import load_config
from pathlib import Path
import pytest


def test_load_json() -> None:
    path = Path(__file__).parent / "data" / "config.json"
    config = load_config(path)
    assert config.database_url == "sqlite:///:memory:"


def test_load_yaml() -> None:
    path = Path(__file__).parent / "data" / "config.yaml"
    config = load_config(path)
    assert config.database_url == "sqlite:///:memory:"


def test_load_file_does_not_exist() -> None:
    path = "not_exists"
    with pytest.raises(FileNotFoundError):
        load_config(path)


def test_load_file_wrong_data() -> None:
    path = Path(__file__).parent / "data" / "wrong.yaml"
    with pytest.raises(ValueError):
        load_config(path)
