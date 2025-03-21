from eaidl.config import Configuration
from sqlalchemy.ext.automap import automap_base
import sqlalchemy
from sqlalchemy.orm import Session
import logging


log = logging.getLogger(__name__)

#: We use automap and reflection for tables now. We could switch to declarative,
#: but most of the fields are useless anyway, and because we don't have good
#: documentation every use of field need to be investigated inside example
#: database.
#:
#: https://docs.sqlalchemy.org/en/20/orm/extensions/automap.html#generating-mappings-from-an-existing-metadata
#:
base = automap_base()


@sqlalchemy.event.listens_for(base.metadata, "column_reflect")
def column_reflect(inspector, table, column_info):
    """
    We do conversion of column names to lowe case, so we can support different types of databased.
    In sqlite we have Object_ID and UpperBound, in postresql we have object_id and upperbound.

    https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html#mapper-automated-reflection-schemes

    """
    column_info["key"] = "attr_%s" % column_info["name"].lower()


class ModelChanger:
    """Just as sample code to change model fields in bulk."""

    def __init__(self, config: Configuration) -> None:
        self.config = config
        self.engine = sqlalchemy.create_engine(config.database_url, echo=False, future=True)
        base.prepare(autoload_with=self.engine)
        self.session = Session(self.engine)

    def change(self) -> None:
        pass
        # TConnector = base.classes.t_connector
        # t_connectors = self.session.query(TConnector).filter(TConnector.attr_connector_type == "Association").all()
        # for connector in t_connectors:
        #     if connector.attr_destrole is not None:
        #         if connector.attr_destrole.startswith("a_"):
        #             print(f"{connector.attr_destrole} -> {connector.attr_destrole[2:]}")
        #             connector.attr_destrole = connector.attr_destrole[2:]

        # # Commit the changes to the database
        # self.session.commit()
        # TAttribute = base.classes.t_attribute
        # t_attributes = self.session.query(TAttribute).all()

        # for attribute in t_attributes:
        #     if attribute.attr_name is not None:
        #         if attribute.attr_name.startswith("a_"):
        #             print(f"{attribute.attr_name} -> {attribute.attr_name[2:]}")
        #             attribute.attr_name = attribute.attr_name[2:]
        # # Commit the changes to the database
        # self.session.commit()
