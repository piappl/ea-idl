from eaidl.generate import generate
from eaidl.load import ModelParser
from eaidl.utils import Configuration


def test_generatE() -> None:
    config = Configuration()
    parser = ModelParser(config)
    generate(Configuration(), parser.load())
