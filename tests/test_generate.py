from eaidl.generate import generate
from eaidl.load import load
from eaidl.utils import Configuration


def test_generatE() -> None:
    generate(Configuration(), load(Configuration()))
