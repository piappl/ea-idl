from pathlib import Path
from eaidl.generate import generate
from eaidl.load import ModelParser
from eaidl.utils import Configuration
from rich import inspect


def test_generate() -> None:
    path = Path(__file__).parent / "data" / "nafv4.qea"
    config = Configuration()
    config.database_url = f"sqlite+pysqlite:///{path.as_posix()}"
    config.root_package = "{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"
    inspect(config)
    parser = ModelParser(config)
    with (Path(__file__).parent / "data" / "nafv4.idl").open("w") as output:
        output.write(generate(config, parser.load()))
