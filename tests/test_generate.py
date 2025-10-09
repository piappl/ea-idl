from pathlib import Path
from eaidl.generate import generate
from eaidl.load import ModelParser
from eaidl.utils import Configuration


def test_generate() -> None:
    path = Path(__file__).parent / "data" / "nafv4.qea"
    config = Configuration()
    config.database_url = f"sqlite+pysqlite:///{path.as_posix()}"
    config.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    config.filter_stereotypes = ["lobw"]
    parser = ModelParser(config)
    with (Path(__file__).parent / "data" / "nafv4.idl").open("w") as output:
        output.write(generate(config, parser.load()))


def test_generate_just_defs() -> None:
    path = Path(__file__).parent / "data" / "nafv4.qea"
    config = Configuration()
    config.database_url = f"sqlite+pysqlite:///{path.as_posix()}"
    config.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    config.template = "idl_just_defs.jinja2"
    config.filter_stereotypes = ["hibw"]
    parser = ModelParser(config)
    with (Path(__file__).parent / "data" / "nafv4_just_defs.idl").open("w") as output:
        output.write(generate(config, parser.load()))
