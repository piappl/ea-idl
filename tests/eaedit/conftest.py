import shutil
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "data"
NAF_MDG = Path(__file__).parents[2] / "refs/naf_v4_ea_plugins/NAFv4 Core 2021.12/NAFv4-Core-MDG-2021.12.xml"


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


@pytest.fixture
def mini_mdg_path() -> Path:
    return Path(__file__).parent / "data" / "mini-mdg.xml"


@pytest.fixture
def naf_mdg_path() -> Path:
    if not NAF_MDG.exists():
        pytest.skip("NAF MDG not available")
    return NAF_MDG
