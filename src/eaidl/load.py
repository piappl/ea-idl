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
import copy
from collections import deque

log = logging.getLogger(__name__)

ModelScope = Literal["Private", "Public", "Protected", "Package"]


class LocalBaseModel(BaseModel):
    notes: Optional[str] = None
    namespace: List[str] = []


ConnectorType = Literal[
    "Abstraction",
    "Aggregation",
    "Assembly",
    "Association",
    "Collaboration",
    "CommunicationPath",
    "Connector",
    "ControlFlow",
    "Delegate",
    "Dependency",
    "Deployment",
    "ERLink",
    "Extension",
    "Generalization",
    "InformationFlow",
    "Instantiation",
    "InterruptFlow",
    "Manifest",
    "Nesting",
    "NoteLink",
    "ObjectFlow",
    "Package",
    "ProtocolConformance",
    "ProtocolTransition",
    "Realisation",
    "Sequence",
    "StateFlow",
    "Substitution",
    "Usage",
    "UseCase",
]


class ModelConnectionEnd(LocalBaseModel):
    cardinality: Optional[str] = None
    access: Optional[ModelScope] = None
    element: Optional[str] = None
    role: Optional[str] = None
    role_type: Optional[str] = None
    role_note: Optional[str] = None
    containment: Optional[str] = None
    is_aggregate: int = 0
    is_ordered: int = 0
    qualifier: Optional[str] = None


class ModelConnection(LocalBaseModel):
    connector_id: int
    connector_type: ConnectorType
    connector_sub_type: Optional[str] = None
    direction: Optional[
        Literal[
            "Source -> Destination",
            "Destination -> Source",
            "Unspecified",
            "Bi-Directional",
        ]
    ] = None
    start_object_id: int
    end_object_id: int
    source: ModelConnectionEnd
    destination: ModelConnectionEnd


class ModelClass(LocalBaseModel):
    name: str
    parent: Optional["ModelPackage"] = None
    object_id: int
    is_abstract: Optional[bool] = None
    alias: Optional[str] = None
    stereotype: Optional[str] = None
    attributes: List["ModelAttribute"] = []
    stereotypes: Optional[List[str]] = None
    depends_on: List[int] = []


class ModelPackage(LocalBaseModel):
    package_id: int
    object_id: int
    parent: Optional["ModelPackage"] = None
    name: str
    guid: str
    packages: List["ModelPackage"] = []
    classes: List[ModelClass] = []
    depends_on: List[int] = []


class ModelAttribute(LocalBaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    attribute_id: int
    parent: Optional["ModelClass"] = None
    scope: Optional[ModelScope] = None
    position: Optional[int] = None
    is_optional: Optional[bool] = None
    is_collection: Optional[bool] = None
    is_ordered: Optional[bool] = None
    is_static: Optional[bool] = None
    lower_bound: Optional[str] = None
    upper_bound: Optional[str] = None
    connector: Optional[ModelConnection] = None


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


def get_object_connections(
    session, base, object_id: int, mode: Literal["source", "destination", "both"]
) -> List[ModelConnection]:
    ret = []
    TConnector = base.classes.t_connector
    if mode == "source":
        t_connectors = (
            session.query(TConnector)
            .filter(
                TConnector.attr_start_object_id == object_id,
            )
            .all()
        )
    elif mode == "destination":
        t_connectors = (
            session.query(TConnector)
            .filter(
                TConnector.attr_end_object_id == object_id,
            )
            .all()
        )
    else:
        t_connectors = (
            session.query(TConnector)
            .filter(
                sqlalchemy.or_(
                    TConnector.attr_start_object_id == object_id,
                    TConnector.attr_end_object_id == object_id,
                )
            )
            .all()
        )
    for t_connector in t_connectors:
        ret.append(
            ModelConnection(
                connector_id=t_connector.attr_connector_id,
                connector_type=t_connector.attr_connector_type,
                direction=t_connector.attr_direction,
                connector_sub_type=t_connector.attr_subtype,
                start_object_id=t_connector.attr_start_object_id,
                end_object_id=t_connector.attr_end_object_id,
                source=ModelConnectionEnd(
                    cardinality=t_connector.attr_sourcecard,
                    access=t_connector.attr_sourceaccess,
                    element=t_connector.attr_sourceelement,
                    role=t_connector.attr_sourcerole,
                    role_type=t_connector.attr_sourceroletype,
                    role_note=t_connector.attr_sourcerolenote,
                    containment=t_connector.attr_sourcecontainment,
                    is_aggregate=t_connector.attr_sourceisaggregate,
                    is_ordered=t_connector.attr_sourceisordered,
                    qualifier=t_connector.attr_sourcequalifier,
                ),
                destination=ModelConnectionEnd(
                    cardinality=t_connector.attr_destcard,
                    access=t_connector.attr_destaccess,
                    element=t_connector.attr_destelement,
                    role=t_connector.attr_destrole,
                    role_type=t_connector.attr_destroletype,
                    role_note=t_connector.attr_destrolenote,
                    containment=t_connector.attr_destcontainment,
                    is_aggregate=t_connector.attr_sourceisaggregate,
                    is_ordered=t_connector.attr_destisordered,
                    qualifier=t_connector.attr_destqualifier,
                ),
            )
        )
    return ret


def package_parse(
    session,
    base,
    t_package: Any,
    parent_package: Optional[ModelPackage] = None,
    parse_children=True,
) -> ModelPackage:
    TObject = base.classes.t_object
    t_package_object = session.query(TObject).filter(TObject.attr_ea_guid == t_package.attr_ea_guid).scalar()
    package = ModelPackage(
        package_id=t_package.attr_package_id,
        object_id=t_package_object.attr_object_id,
        name=t_package.attr_name,
        guid=t_package.attr_ea_guid,
        parent=parent_package,
    )

    if parent_package is None:
        package.namespace = [package.name]
    else:
        package.namespace = copy.copy(parent_package.namespace)
        package.namespace.append(package.name)
    package.notes = t_package_object.attr_note

    if parse_children:
        package_parse_children(session, base, package)

    return package


def package_parse_children(session, base, parent_package: ModelPackage):
    TObject = base.classes.t_object
    TPackage = base.classes.t_package
    child_t_objects = session.query(TObject).filter(TObject.attr_package_id == parent_package.package_id).all()
    classes = deque()
    packages = deque()
    for child_t_object in child_t_objects:
        # inspect(child_t_object)

        if child_t_object.attr_object_type == "Package":
            stmt = sqlalchemy.select(TPackage).where(TPackage.attr_ea_guid == child_t_object.attr_ea_guid)
            t_package = session.execute(stmt).scalars().first()
            pkg = package_parse(session, base, t_package, parent_package)
            packages.append(pkg)

        elif child_t_object.attr_object_type == "Class":
            cls: ModelClass = class_parse(session, base, parent_package, child_t_object)
            if cls.name is not None:
                classes.append(cls)
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
    # Now we need to sort stuff. Do classes, those have depends_on list, which
    # means those need to go first.
    transferred_objects: List[int] = []
    for count in range(len(classes) * len(classes)):
        # If there is something wrong we might infinite loop here with while,
        # for sure we can handle that in size*size/2
        if count == len(classes) * len(classes) - 1:
            log.error("Something is wrong with class dependencies")
            break
        if len(classes) == 0:
            break
        item: ModelClass = classes.popleft()
        for dependant in item.depends_on:
            if dependant not in transferred_objects:
                # We are not ready for that one, put it back on another end
                classes.append(item)
                break
        transferred_objects.append(item.object_id)
        parent_package.classes.append(item)
    # FIXME, packages need sorting to.
    parent_package.packages = [item for item in packages]


def to_bool(val: bool | int | str) -> bool:
    if isinstance(val, str):
        if val.lower() in ["1", "true"]:
            return True
        else:
            return False
    if val:
        return True
    return False


def get_object(session, base, object_id: int) -> Any:
    TObject = base.classes.t_object
    return session.query(TObject).filter(TObject.attr_object_id == object_id).scalar()


def get_namespace(session, base, bottom_package_id: int) -> List[str]:
    """Get namespace given package identifier.

    It goes up the package chain.

    :param session: session
    :param base: base
    :param destination: package identifier
    :return: namespace as a list of string
    """
    namespace = []
    current_package_id = bottom_package_id
    while True:
        TPackage = base.classes.t_package
        package = session.query(TPackage).filter(TPackage.attr_package_id == current_package_id).scalar()
        current_package_id = package.attr_parent_id
        namespace.append(package.attr_name)
        if current_package_id in [0, None]:
            break
    namespace.reverse()
    return namespace


def attribute_parse(
    session, base, parent_package: ModelPackage, parent_class: ModelClass, t_attribute
) -> ModelAttribute:
    attribute = ModelAttribute(
        name=t_attribute.attr_name,
        type=t_attribute.attr_type,
        attribute_id=t_attribute.attr_object_id,
        parent=parent_class,
    )
    # Note that we cannot fill namespace here - this is namespace for class that
    # has this attribute, we need to fill with namespace for type of this attribute
    attribute.namespace = []
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

    connections = get_object_connections(session, base, parent_class.object_id, mode="source")
    for connection in connections:
        # We can gent object from database, but we probably prefer to find it in our structure
        # right now it might not be there yet... but still we can find right connection
        # and have to look up actual class later.
        destination = get_object(session, base, connection.end_object_id)
        # We create dependency, so we can sort classes later
        if connection.end_object_id not in parent_class.depends_on:
            parent_class.depends_on.append(connection.end_object_id)

        # We are really interested in namespace here. So we need to go up.
        attribute.namespace = get_namespace(session, base, destination.attr_package_id)
        # We create dependency, so we can sort packages later
        if destination.attr_package_id not in parent_package.depends_on:
            parent_package.depends_on.append(destination.attr_package_id)
        if destination.attr_name == attribute.type:
            attribute.connector = connection
            break

    # There is some validation
    if attribute.connector is None:
        log.warning("No connector found for attribute %s %s", parent_class.name, attribute.name)
    if parent_class.object_id != attribute.attribute_id:
        log.warning(
            "Validation issue: attribute parent is different %d %d in %s %s",
            parent_class.object_id,
            attribute.attribute_id,
            parent_class.name,
            attribute.name,
        )
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
    model_class = ModelClass(
        name=t_object.attr_name,
        object_id=t_object.attr_object_id,
        parent=parent_package,
    )
    model_class.namespace = parent_package.namespace
    TAttribute = base.classes.t_attribute
    t_attributes = session.query(TAttribute).filter(TAttribute.attr_object_id == model_class.object_id).all()
    for t_attribute in t_attributes:
        model_class.attributes.append(attribute_parse(session, base, parent_package, model_class, t_attribute))
    model_class.stereotype = t_object.attr_stereotype
    model_class.stereotypes = get_stereotypes(session, base, t_object.attr_ea_guid)
    model_class.is_abstract = to_bool(t_object.attr_abstract)
    model_class.notes = t_object.attr_note
    return model_class
