from eaidl.utils import Configuration
from sqlalchemy.ext.automap import automap_base
from pydantic import BaseModel
from typing import Optional
import sqlalchemy
from sqlalchemy.orm import Session
from rich import inspect
from typing import Any, List, Literal
import logging
import re

log = logging.getLogger(__name__)

ModelScope = Literal["Private", "Public", "Protected", "Package"]


class LocalBaseModel(BaseModel):
    notes: Optional[str] = None


class ModelClass(LocalBaseModel):
    name: str
    object_id: int
    is_abstract: Optional[bool] = None
    alias: Optional[str] = None
    stereotype: Optional[str] = None
    attributes: List["ModelAttribute"] = []
    stereotypes: Optional[List[str]] = None


class ModelPackage(LocalBaseModel):
    package_id: int
    name: str
    guid: str
    namespace: List[str] = []
    packages: List["ModelPackage"] = []
    classes: List[ModelClass] = []


class ModelAttribute(LocalBaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    attribute_id: int
    parent_object_id: int
    scope: Optional[ModelScope] = None
    position: Optional[int] = None
    is_optional: Optional[bool] = None
    is_collection: Optional[bool] = None
    is_ordered: Optional[bool] = None
    is_static: Optional[bool] = None

    lower_bound: Optional[str] = None
    upper_bound: Optional[str] = None


base = automap_base()


@sqlalchemy.event.listens_for(base.metadata, "column_reflect")
def column_reflect(inspector, table, column_info):
    """
    We do conversion of column names to lowe case, so we can support different types of databased.
    In sqlite we have Object_ID and UpperBound, in postresql we have object_id and upperbound.

    https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html#mapper-automated-reflection-schemes

    """
    column_info["key"] = "attr_%s" % column_info["name"].lower()


def load(config: Configuration) -> ModelPackage:
    engine = sqlalchemy.create_engine(config.database_url, echo=False, future=True)
    base.prepare(autoload_with=engine)
    TPackage = base.classes.t_package
    with Session(engine) as session:
        if config.root_package[0] == "{":
            root = session.query(TPackage).filter(TPackage.attr_ea_guid == config.root_package).scalar()
        else:
            root = session.query(TPackage).filter(TPackage.attr_name == config.root_package).scalar()
        if root is None:
            raise ValueError("Root package not found, check configuration")
        return package_parse(session, base, root)


def package_parse(
    session,
    base,
    t_package: Any,
    parent_package: Optional[ModelPackage] = None,
    parse_children=True,
) -> ModelPackage:
    package = ModelPackage(
        package_id=t_package.attr_package_id,
        name=t_package.attr_name,
        guid=t_package.attr_ea_guid,
    )

    TObject = base.classes.t_object
    t_package_object = session.query(TObject).filter(TObject.attr_ea_guid == t_package.attr_ea_guid).scalar()
    if parent_package is None:
        package.namespace = []
    else:
        package.namespace.append(parent_package.name)

    package.notes = t_package_object.attr_note

    if parse_children:
        package_parse_children(session, base, package)

    return package


def package_parse_children(session, base, parent_package: ModelPackage):
    TObject = base.classes.t_object
    TPackage = base.classes.t_package
    child_t_objects = session.query(TObject).filter(TObject.attr_package_id == parent_package.package_id).all()

    for child_t_object in child_t_objects:
        # inspect(child_t_object)
        if child_t_object.attr_object_type == "Package":
            stmt = sqlalchemy.select(TPackage).where(TPackage.attr_ea_guid == child_t_object.attr_ea_guid)
            t_package = session.execute(stmt).scalars().first()
            pkg = package_parse(session, base, t_package, parent_package)
            parent_package.packages.append(pkg)

        elif child_t_object.attr_object_type == "Class":
            cls: ModelClass = class_parse(session, base, parent_package, child_t_object)
            if cls.name is not None:
                parent_package.classes.append(cls)
        elif child_t_object.attr_object_type in [
            "Note",
            "Text",
            "StateMachine",
            "StateNode",
            "State",
            "Activity",
            "StateNode",
            "UMLDiagram",
            "Object",
            "Port",
            "Part",
            "Boundary",
        ]:
            # Those are silent
            log.debug("Not parsing %s", child_t_object.attr_object_type)
        else:
            log.error("Not parsing %s", child_t_object.attr_object_type)
            inspect(child_t_object)


def to_bool(val: bool | int | str) -> bool:
    if isinstance(val, str):
        if val.lower() in ["1", "true"]:
            return True
        else:
            return False
    if val:
        return True
    return False


def attribute_parse(
    session, base, parent_package: ModelPackage, parent_class: ModelClass, t_attribute
) -> ModelAttribute:
    attribute = ModelAttribute(
        name=t_attribute.attr_name,
        type=t_attribute.attr_type,
        attribute_id=t_attribute.attr_object_id,
        parent_object_id=parent_class.object_id,
    )
    if t_attribute.attr_lowerbound == "0" and t_attribute.attr_upperbound == "1":
        attribute.is_optional = True
    else:
        attribute.is_optional = False

    attribute.lower_bound = t_attribute.attr_lowerbound
    attribute.upper_bound = t_attribute.attr_upperbound

    attribute.is_collection = to_bool(t_attribute.attr_iscollection)
    attribute.is_ordered = to_bool(t_attribute.attr_isordered)
    attribute.is_static = to_bool(t_attribute.attr_isstatic)
    attribute.notes = t_attribute.attr_notes

    # There is some validation
    if attribute.is_collection and attribute.upper_bound in [None, "1", "0"]:
        log.warning(
            "Validation issue: attribute is collection, but upper bound is %s in %s.%s",
            attribute.upper_bound,
            parent_class.name,
            attribute.name,
        )
    if not attribute.is_collection and attribute.upper_bound not in [None, "1", "0"]:
        log.warning(
            "Validation issue: attribute is not collection, but upper bound is in %s %s.%s",
            attribute.upper_bound,
            parent_class.name,
            attribute.name,
        )
    return attribute


def get_stereotypes(session, base, guid: str) -> List[str]:
    TXref = base.classes.t_xref
    t_xref = session.query(TXref).filter(TXref.attr_client == guid).filter(TXref.attr_name == "Stereotypes").first()
    if t_xref is not None:
        return re.findall("@STEREO;Name=(.*?);", t_xref.attr_description)
    else:
        return []


def class_parse(session, base, parent_package: ModelPackage, t_object) -> ModelClass:
    model_class = ModelClass(name=t_object.attr_name, object_id=t_object.attr_object_id)
    TAttribute = base.classes.t_attribute
    t_attributes = session.query(TAttribute).filter(TAttribute.attr_object_id == model_class.object_id).all()
    for t_attribute in t_attributes:
        model_class.attributes.append(attribute_parse(session, base, parent_package, model_class, t_attribute))
    model_class.stereotype = t_object.attr_stereotype
    model_class.stereotypes = get_stereotypes(session, base, t_object.attr_ea_guid)
    model_class.is_abstract = to_bool(t_object.attr_abstract)
    model_class.notes = t_object.attr_note
    return model_class
