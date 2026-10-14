import shutil
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def nafv4_path() -> Path:
    return DATA / "nafv4.qea"


@pytest.fixture
def empty_path() -> Path:
    return DATA / "empty.qea"


@pytest.fixture
def qea_copy(tmp_path):
    """Copy a repository into tmp_path so a test can modify it."""

    def _copy(src: Path, name: str = "copy.qea") -> Path:
        dest = tmp_path / name
        shutil.copyfile(src, dest)
        return dest

    return _copy
