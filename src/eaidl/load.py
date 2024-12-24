from eaidl.utils import Configuration, is_lower_snake_case, is_camel_case
from sqlalchemy.ext.automap import automap_base
from pydantic import BaseModel
from typing import Optional
import sqlalchemy
from sqlalchemy.orm import Session
from rich import inspect
from typing import Any, List, Literal, Deque, Dict
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


class ModelPropertyType(BaseModel):
    property: str
    notes: Optional[str] = None
    property_types: List[str] = []


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
    stereotypes: List[str] = []
    generalization: Optional[List[str]] = None
    depends_on: List[int] = []
    parent_type: Optional[str] = None
    properties: Dict[str, float | str | int] = {}


class ModelPackageInfo(LocalBaseModel):
    structs: int = 0
    typedefs: int = 0
    unions: int = 0
    enums: int = 0
    packages: int = 0
    create_definition: bool = False
    create_declaration: bool = False


class ModelPackage(LocalBaseModel):
    package_id: int
    object_id: int
    parent: Optional["ModelPackage"] = None
    name: str
    guid: str
    packages: List["ModelPackage"] = []
    classes: List[ModelClass] = []
    depends_on: List[int] = []
    info: ModelPackageInfo = ModelPackageInfo()
    property_types: List[ModelPropertyType] = []


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


def to_bool(val: bool | int | str) -> bool:
    if isinstance(val, str):
        if val.lower() in ["1", "true"]:
            return True
        else:
            return False
    if val:
        return True
    return False


class ModelParser:
    def __init__(self, config: Configuration) -> None:
        self.config = config
        self.engine = sqlalchemy.create_engine(config.database_url, echo=False, future=True)
        # Make base class field
        self.root_package_guid: Optional[str] = None
        base.prepare(autoload_with=self.engine)
        self.session = Session(self.engine)

    def load(self) -> ModelPackage:
        TPackage = base.classes.t_package

        if self.config.root_package[0] == "{":
            root = self.session.query(TPackage).filter(TPackage.attr_ea_guid == self.config.root_package).scalar()
        else:
            root = self.session.query(TPackage).filter(TPackage.attr_name == self.config.root_package).scalar()
        if root is None:
            raise ValueError("Root package not found, check configuration")
        self.root_package_guid = root.attr_ea_guid

        whole = self.package_parse(root)
        # We can get property types from model, but it somehow lacks information...
        # TPropertytypes = base.classes.t_propertytypes
        # p_propertytypes = self.session.query(TPropertytypes).all()
        # for property in p_propertytypes:
        #     name = property.attr_property
        #     if name not in self.config.properties:
        #         continue
        #     if name in self.config.properties_map.keys():
        #         name = self.config.properties_map[name]
        #     property_type = ModelPropertyType(
        #         property=name,
        #         description=property.attr_description,
        #         notes=property.attr_notes,
        #     )
        #     whole.property_types.append(property_type)
        # So we take them from config
        for name, prop in self.config.properties.items():
            if prop.idl_default is True:
                continue
            if prop.idl_name is not None:
                name = prop.idl_name
            property_type = ModelPropertyType(property=name, notes=prop.description, property_types=prop.idl_types)
            whole.property_types.append(property_type)

        return whole

    def get_object_connections(
        self, object_id: int, mode: Literal["source", "destination", "both"]
    ) -> List[ModelConnection]:
        ret = []
        TConnector = base.classes.t_connector
        if mode == "source":
            t_connectors = (
                self.session.query(TConnector)
                .filter(
                    TConnector.attr_start_object_id == object_id,
                )
                .all()
            )
        elif mode == "destination":
            t_connectors = (
                self.session.query(TConnector)
                .filter(
                    TConnector.attr_end_object_id == object_id,
                )
                .all()
            )
        else:
            t_connectors = (
                self.session.query(TConnector)
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
        self,
        t_package: Any,
        parent_package: Optional[ModelPackage] = None,
        parse_children=True,
    ) -> ModelPackage:
        TObject = base.classes.t_object
        t_package_object = self.session.query(TObject).filter(TObject.attr_ea_guid == t_package.attr_ea_guid).scalar()
        package = ModelPackage(
            package_id=t_package.attr_package_id,
            object_id=t_package_object.attr_object_id,
            name=t_package.attr_name,
            guid=t_package.attr_ea_guid,
            parent=parent_package,
        )
        if not is_lower_snake_case(package.name):
            log.warning("Package name has wrong case, expected lower snake case: %s", package.name)
        if parent_package is None:
            package.namespace = [package.name]
        else:
            package.namespace = copy.copy(parent_package.namespace)
            package.namespace.append(package.name)
        package.notes = t_package_object.attr_note

        if parse_children:
            self.package_parse_children(package)

        return package

    def package_parse_children(self, parent_package: ModelPackage):
        TObject = base.classes.t_object
        TPackage = base.classes.t_package
        child_t_objects = self.session.query(TObject).filter(TObject.attr_package_id == parent_package.package_id).all()
        classes: Deque[ModelClass] = deque([])
        packages: Deque[ModelPackage] = deque([])
        for child_t_object in child_t_objects:
            # inspect(child_t_object)
            if child_t_object.attr_object_type == "Package":
                stmt = sqlalchemy.select(TPackage).where(TPackage.attr_ea_guid == child_t_object.attr_ea_guid)
                t_package = self.session.execute(stmt).scalars().first()
                pkg = self.package_parse(t_package, parent_package)
                packages.append(pkg)

            elif child_t_object.attr_object_type == "Class":
                cls: ModelClass = self.class_parse(parent_package, child_t_object)
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
        log.debug("Sorting classes %s", parent_package.name)
        # Now we need to sort stuff. Do classes, those have depends_on list, which
        # means those need to go first.
        while len(classes) > 0:
            # FIXME, if there is something wrong we might infinite loop here with while.
            c2: ModelClass = classes.popleft()
            ready = True
            for obj in classes:
                if obj.object_id in c2.depends_on:
                    # We are not ready for that one, put it back on another end
                    classes.append(c2)
                    ready = False
                    break
            if ready:
                parent_package.classes.append(c2)
        log.debug("Sorting classes %s done", parent_package.name)

        # FIXME, packages need sorting to.
        # parent_package.packages = [item for item in packages]
        # print([package.name for package in packages])

        # We want to know on what classes _outside_ of this package this package
        # depends on.
        depends_on = []
        for p2 in parent_package.packages:
            for c3 in p2.classes:
                depends_on += c3.depends_on
        # print(parent_package.namespace, parent_package.name, depends_on)
        for c2 in parent_package.classes:
            depends_on += c2.depends_on
        # print(parent_package.namespace, parent_package.name, depends_on)
        # Now we know what we depend on including internal ones
        for item in depends_on:
            if item not in self.get_all_class_id(parent_package) and item not in parent_package.depends_on:
                parent_package.depends_on.append(item)

        # print(parent_package.namespace, parent_package.name, parent_package.depends_on)
        log.debug("Sorting package %s", parent_package.name)
        while len(packages) > 0:
            # FIXME, if there is something wrong we might infinite loop here with while.
            current_package: ModelPackage = packages.popleft()
            ready = True
            for package in packages:
                for dependant in current_package.depends_on:
                    if dependant in self.get_all_class_id(package):
                        # We are not ready for that one, put it back on another end
                        packages.append(current_package)
                        ready = False
                        break
                if not ready:
                    break
            if ready:
                parent_package.packages.append(current_package)
        log.debug("Sorting packages of %s is not done", parent_package.name)
        # print([package.name for package in parent_package.packages])

        # Do some statictics that templates can use later
        for cls in parent_package.classes:
            if "idlStruct" in cls.stereotypes:
                parent_package.info.structs += 1
            if "idlTypedef" in cls.stereotypes:
                parent_package.info.typedefs += 1
            if "idlUnion" in cls.stereotypes:
                parent_package.info.unions += 1
            if "idlEnum" in cls.stereotypes:
                parent_package.info.enums += 1
        parent_package.info.packages = len(parent_package.packages)
        # We have to know when to create packages, otherwise IDL parser
        # doesn't like empty ones.
        if parent_package.info.packages + parent_package.info.unions + parent_package.info.structs:
            parent_package.info.create_definition = True
        parent_package.info.create_declaration = True

        # if parent_package.info.create_definition is False:
        #     print(parent_package.namespace)
        #     print(parent_package.name)
        #     inspect(parent_package.info)

    def get_object(self, object_id: int) -> Any:
        TObject = base.classes.t_object
        return self.session.query(TObject).filter(TObject.attr_object_id == object_id).scalar()

    def get_all_class_id(self, parent_package: ModelPackage) -> List[int]:
        ret = []
        for package in parent_package.packages:
            ret += self.get_all_class_id(package)
        for cls in parent_package.classes:
            ret.append(cls.object_id)
        return ret

    def get_namespace(self, bottom_package_id: int) -> List[str]:
        """Get namespace given package identifier.

        It goes up the package chain.

        Package identifier is `attr_package_id` field on package reflection.
        For packages outside of `root_package` tree list will be empty, and warning will be reported.

        .. note:: that this will walk up until `root_package` and `load()` needs
            to be called before using it.

        :param bottom_package_id: package identifier
        :return: namespace as a list of string
        """
        namespace = []
        current_package_id = bottom_package_id
        while True:
            TPackage = base.classes.t_package
            package = self.session.query(TPackage).filter(TPackage.attr_package_id == current_package_id).scalar()
            current_package_id = package.attr_parent_id
            namespace.append(package.attr_name)
            if self.root_package_guid == package.attr_ea_guid:
                # We got to our configured top package
                break
            if current_package_id in [0, None]:
                # We got to top package, this is not normal, as it is outside
                # of root we are using.
                log.warning("Namespace search never reached root_package")
                namespace = []
                break
        namespace.reverse()
        return namespace

    def attribute_parse(self, parent_package: ModelPackage, parent_class: ModelClass, t_attribute) -> ModelAttribute:
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

        connections = self.get_object_connections(parent_class.object_id, mode="source")
        for connection in connections:
            if connection.connector_type != "Association":
                continue
            if connection.destination.role != attribute.name:
                continue
            # inspect(connection)
            # We can gent object from database, but we probably prefer to find it in our structure
            # right now it might not be there yet... but still we can find right connection
            # and have to look up actual class later.
            destination = self.get_object(connection.end_object_id)
            # We create dependency, so we can sort classes later
            if connection.end_object_id not in parent_class.depends_on:
                parent_class.depends_on.append(connection.end_object_id)

            # We are really interested in namespace here. So we need to go up.
            attribute.namespace = self.get_namespace(destination.attr_package_id)
            if destination.attr_name == attribute.type:
                attribute.connector = connection
                break

        # There is some validation
        if (
            attribute.connector is None
            and "idlEnum" not in parent_class.stereotypes
            and attribute.type not in self.config.primitive_types
        ):
            # In normal condition we weed connector for all attributes, leading
            # to a type of this attribute. Exceptions are for enumeration and
            # attributes that are of primitive types.
            log.error(
                "No connector found for attribute %s %s %s",
                parent_class.name,
                attribute.type,
                attribute.name,
            )
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
        if not attribute.is_collection and attribute.upper_bound not in [
            None,
            "1",
            "0",
        ]:
            log.warning(
                "Validation issue: attribute is not collection, but upper bound is in %s %s.%s",
                attribute.upper_bound,
                parent_class.name,
                attribute.name,
            )
        if (
            attribute.name is None
            or not is_lower_snake_case(attribute.name)
            and "idlEnum" not in parent_class.stereotypes
        ):
            log.warning("Attribute name has wrong case, expected snake case %s", attribute.name)
        return attribute

    def get_stereotypes(self, guid: str) -> List[str]:
        TXref = base.classes.t_xref
        t_xref = (
            self.session.query(TXref).filter(TXref.attr_client == guid).filter(TXref.attr_name == "Stereotypes").first()
        )
        if t_xref is not None:
            return re.findall("@STEREO;Name=(.*?);", t_xref.attr_description)
        else:
            return []

    def class_parse(self, parent_package: ModelPackage, t_object) -> ModelClass:
        model_class = ModelClass(
            name=t_object.attr_name,
            object_id=t_object.attr_object_id,
            parent=parent_package,
        )
        if not is_camel_case(model_class.name):
            log.warning("Class name has wrong case, expected camel case %s", model_class.name)
        model_class.namespace = parent_package.namespace
        model_class.stereotype = t_object.attr_stereotype
        model_class.stereotypes = self.get_stereotypes(t_object.attr_ea_guid)
        model_class.is_abstract = to_bool(t_object.attr_abstract)
        if t_object.attr_genlinks is not None:
            # We set parent for typedefs.
            model_class.parent_type = (
                m.group(1) if (m := re.search(r"Parent=(.*?);", t_object.attr_genlinks)) is not None else None
            )
        model_class.notes = t_object.attr_note
        connections = self.get_object_connections(model_class.object_id, mode="source")
        for connection in connections:
            if connection.connector_type == "Generalization":
                destination = self.get_object(connection.end_object_id)
                namespace = self.get_namespace(destination.attr_package_id)
                namespace.append(destination.attr_name)
                model_class.generalization = namespace
        connections = self.get_object_connections(model_class.object_id, mode="destination")
        for connection in connections:
            if connection.connector_type == "Generalization":
                model_class.depends_on.append(connection.end_object_id)
        # Add attributes
        TAttribute = base.classes.t_attribute
        t_attributes = self.session.query(TAttribute).filter(TAttribute.attr_object_id == model_class.object_id).all()
        for t_attribute in t_attributes:
            model_class.attributes.append(self.attribute_parse(parent_package, model_class, t_attribute))

        TObjectProperties = base.classes.t_objectproperties
        t_properties = (
            self.session.query(TObjectProperties)
            .filter(TObjectProperties.attr_object_id == model_class.object_id)
            .all()
        )
        for t_property in t_properties:
            if t_property.attr_property in self.config.properties.keys():
                prop_config = self.config.properties[t_property.attr_property]
                if prop_config.idl_name is not None:
                    model_class.properties[prop_config.idl_name] = t_property.attr_value
                else:
                    model_class.properties[f"ext::{t_property.attr_property}"] = t_property.attr_value
        return model_class
