from eaidl.load import ModelParser
from eaidl.utils import Configuration
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.ext.automap import automap_base

from rich import print, inspect


def test_load_row():
    engine = create_engine("sqlite+pysqlite:///tests/data/nafv4.qea", echo=True)
    stmt = text("SELECT * FROM t_object")
    with Session(engine) as session:
        result = session.execute(stmt)
        for row in result:
            print(row)


def test_reflect():
    base = automap_base()
    engine = create_engine("sqlite+pysqlite:///tests/data/nafv4.qea", echo=False)

    # reflect the tables
    base.prepare(autoload_with=engine)
    session = Session(engine)
    contents = {
        "t_datatypes": 650,
        "t_package": 6,
        "t_object": 26,
        "t_attribute": 5,
        "t_connector": 9,
        "t_connectortag": 0,
        "t_diagram": 2,
        "t_diagramobjects": 19,
        "t_diagramlinks": 9,
        "t_objectproperties": 22,
    }

    for key, value in contents.items():
        assert session.query(getattr(base.classes, key)).count() == value

    items = session.query(base.classes.t_package).all()
    for item in items:
        inspect(item)


def test_load():
    ret = ModelParser(Configuration())
    model = ret.load()
    inspect(model)
