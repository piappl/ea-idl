from eaidl.utils import (
    to_bool,
    get_prop,
    enum_name_from_union_attr,
    try_cast,
)
from eaidl.config import Configuration
from sqlalchemy.ext.automap import automap_base
from typing import Optional
import sqlalchemy
from sqlalchemy.orm import Session
from typing import Any, List, Literal, Deque
import logging
import re
import copy
from collections import deque
from eaidl.model import (
    ModelAnnotation,
    ModelAnnotationType,
    ModelAnnotationTypeLiteral,
    ModelClass,
    ModelPackage,
    ModelAttribute,
    ModelConnection,
    ModelConnectionEnd,
    ModelPropertyType,
    ModelCustomProperty,
)
from eaidl import validation

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


def find_class(tree: ModelPackage, object_id: int) -> Optional[ModelClass]:
    for cls in tree.classes:
        if cls.object_id == object_id:
            return cls
    for package in tree.packages:
        ret = find_class(package, object_id)
        if ret is not None:
            return ret
    return None


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
        whole = self.package_parse(root, root=True)
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
        for name, prop in self.config.annotations.items():
            if prop.idl_default is True:
                continue
            if prop.idl_name is not None:
                name = prop.idl_name
            property_type = ModelPropertyType(property=name, notes=prop.notes, property_types=prop.idl_types)
            whole.property_types.append(property_type)
        self.get_union_connections(whole)
        return whole

    def get_union_connections(self, tree: ModelPackage) -> Any:
        TConnector = base.classes.t_connector
        t_connectors = self.session.query(TConnector).filter(TConnector.attr_stereotype == "union").all()
        for connector in t_connectors:
            for object_id in [
                connector.attr_start_object_id,
                connector.attr_end_object_id,
            ]:
                obj = self.get_object(object_id)
                stereotypes = self.get_stereotypes(obj.attr_ea_guid)
                if self.config.stereotypes.idl_union in stereotypes:
                    union_obj = obj
                elif self.config.stereotypes.idl_enum in stereotypes:
                    enum_obj = obj
                else:
                    log.error("Wrong union connection")
            union_class = find_class(tree, union_obj.attr_object_id)
            enum_class = find_class(tree, enum_obj.attr_object_id)
            if union_class is None or enum_class is None:
                log.error("Cannot connect union to enum")
                continue
            self.check_union_and_enum(union_class, enum_class)

    def get_object_connections(
        self, object_id: int, mode: Literal["source", "destination", "both"] = "both"
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
                    stereotype=t_connector.attr_stereotype,
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
        root=False,
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
        # Override root name?
        if root and self.config.root_package_name is not None:
            package.name = self.config.root_package_name
        if parent_package is None:
            package.namespace = [package.name]
        else:
            package.namespace = copy.copy(parent_package.namespace)
            package.namespace.append(package.name)
        package.notes = t_package_object.attr_note
        package.stereotypes = self.get_stereotypes(package.guid)
        if parse_children:
            self.package_parse_children(package)
        # There is some validation
        validation.base.run("package", self.config, package=package)
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
                if t_package is None:
                    log.error("Package not found %s", child_t_object.attr_ea_guid)
                    continue
                if child_t_object.attr_ea_guid in self.config.ignore_packages:
                    log.error(
                        "Ignoring %s %s",
                        child_t_object.attr_ea_guid,
                        t_package.attr_name,
                    )
                    continue
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
                # inspect(child_t_object)
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

        log.debug("Sorting package %s", parent_package.name)
        edges = []
        while len(packages) > 0:
            # FIXME, if there is something wrong we might infinite loop here with while.
            # print([package.name for package in packages])
            current_package: ModelPackage = packages.popleft()
            ready = True
            for package in packages:
                for dependant in self.get_all_depends_on(current_package):
                    if dependant in self.get_all_class_id(package):
                        # We are not ready for that one, put it back on another end
                        packages.append(current_package)
                        if (current_package.name, package.name) not in edges and (
                            package.name,
                            current_package.name,
                        ) not in edges:
                            # This is new edge
                            edges.append((current_package.name, package.name))
                        elif (package.name, current_package.name) in edges:
                            log.error(
                                "Got circular dependency in packages %s and %s",
                                package.name,
                                current_package.name,
                            )
                            return

                        ready = False
                        break
                if not ready:
                    break
            if ready:
                parent_package.packages.append(current_package)
        log.debug("Sorting packages of %s done", parent_package.name)
        # print([package.name for package in parent_package.packages])

        # Do some statictics that templates can use later
        for cls in parent_package.classes:
            if self.config.stereotypes.idl_struct in cls.stereotypes:
                parent_package.info.structs += 1
            if self.config.stereotypes.idl_typedef in cls.stereotypes:
                parent_package.info.typedefs += 1
            if self.config.stereotypes.idl_union in cls.stereotypes:
                parent_package.info.unions += 1
            if self.config.stereotypes.idl_enum in cls.stereotypes:
                parent_package.info.enums += 1
        parent_package.info.packages = len(parent_package.packages)
        # We have to know when to create packages, otherwise IDL parser
        # doesn't like empty ones.
        if parent_package.info.packages + parent_package.info.unions + parent_package.info.structs:
            parent_package.info.create_definition = True
        parent_package.info.create_declaration = True

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

    def get_all_depends_on(self, parent_package: ModelPackage) -> List[int]:
        ret = []
        for package in parent_package.packages:
            ret += package.depends_on
            ret += self.get_all_depends_on(package)
        for cls in parent_package.classes:
            ret += cls.depends_on

        return list(set(ret))

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
            if self.root_package_guid == package.attr_ea_guid and self.config.root_package_name is not None:
                namespace.append(self.config.root_package_name)
            else:
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

    def create_annotation(self, value: ModelAnnotationType) -> ModelAnnotation:
        value_type: ModelAnnotationTypeLiteral = "none"
        if isinstance(value, str):
            value_type = "str"
        if isinstance(value, float):
            value_type = "float"
        if isinstance(value, int):
            value_type = "int"
        return ModelAnnotation(value=value, value_type=value_type)

    def attribute_parse(
        self,
        parent_package: Optional[ModelPackage],
        parent_class: ModelClass,
        t_attribute,
    ) -> ModelAttribute:
        attribute = ModelAttribute(
            name=t_attribute.attr_name,
            type=t_attribute.attr_type,
            guid=t_attribute.attr_ea_guid,
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
        attribute.stereotypes = self.get_stereotypes(attribute.guid)
        attribute.is_collection = to_bool(t_attribute.attr_iscollection)
        attribute.is_ordered = to_bool(t_attribute.attr_isordered)
        attribute.is_static = to_bool(t_attribute.attr_isstatic)
        attribute.notes = t_attribute.attr_notes
        if t_attribute.attr_default is not None:
            # @default Annotation
            #           This annotation allows specifying a default value for the annotated element.
            #
            if t_attribute.attr_type in ["str"]:
                # We allow for empty strings
                attribute.properties["default"] = ModelAnnotation(
                    value=t_attribute.attr_default, value_type=t_attribute.attr_type
                )
            if t_attribute.attr_type in ["int", "float"] and t_attribute.attr_default != "":
                attribute.properties["default"] = ModelAnnotation(
                    value=t_attribute.attr_default, value_type=t_attribute.attr_type
                )
            elif t_attribute.attr_type is not None and t_attribute.attr_default != "":
                attribute.properties["default"] = ModelAnnotation(value=t_attribute.attr_default, value_type="object")
            else:
                pass
                # We don't set anything here
                # attribute.properties["value"] = ModelAnnotation(value=None, value_type="none")

        if attribute.is_optional is True:
            # This is optional when present
            attribute.properties["optional"] = self.create_annotation(None)
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
        validation.base.run("attribute", self.config, attribute=attribute, cls=parent_class)
        return attribute

    def get_stereotypes(self, guid: str) -> List[str]:
        stereotypes = []
        TXref = base.classes.t_xref
        t_xref = (
            self.session.query(TXref).filter(TXref.attr_client == guid).filter(TXref.attr_name == "Stereotypes").first()
        )
        if t_xref is not None:
            stereotypes = re.findall("@STEREO;Name=(.*?);", t_xref.attr_description)
        TObject = base.classes.t_object
        t_object = self.session.query(TObject).filter(TObject.attr_ea_guid == guid).scalar()
        if t_object is not None and t_object.attr_stereotype and t_object.attr_stereotype not in stereotypes:
            # We might be looking for stereotypes of something that is not an object,
            # so we can get t_object == None here.
            stereotypes.append(t_object.attr_stereotype)
        return stereotypes

    def get_custom_properties(self, guid: str) -> List[ModelCustomProperty]:
        TXref = base.classes.t_xref
        t_xref = (
            self.session.query(TXref)
            .filter(TXref.attr_client == guid)
            .filter(TXref.attr_name == "CustomProperties")
            .first()
        )
        # inspect(t_xref)
        # @PROP=@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;@PRMT=@ENDPRMT;@ENDPROP;
        if t_xref is not None:
            props: List[ModelCustomProperty] = []
            for prop in re.findall("@PROP=(.*?)@ENDPROP;", t_xref.attr_description):
                # @NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;
                props.append(
                    ModelCustomProperty(
                        name=get_prop(prop, "NAME"),
                        value=get_prop(prop, "VALU"),
                        type=get_prop(prop, "TYPE"),
                    )
                )
            return props
        else:
            return []

    def check_union_and_enum(self, model_union: ModelClass, model_enum: ModelClass) -> None:
        """Tries to fill stuff in union based on associated enumeration.

        Also does some checks if those are correctly modelled.

        :param model_union: model for union
        :param model_enum: model for enumeration
        :raises ValueError: if something is not ok im model
        """
        assert self.config.stereotypes.idl_union in model_union.stereotypes
        assert self.config.stereotypes.idl_enum in model_enum.stereotypes
        assert len(model_enum.attributes) >= len(model_union.attributes)
        model_union.union_enum = "::".join(model_enum.namespace + [model_enum.name])
        for union_attr in model_union.attributes:
            assert union_attr.name is not None
            union_attr_name = enum_name_from_union_attr(model_enum.name, union_attr.name)
            enum_attr = None
            for item in model_enum.attributes:
                if item.name == union_attr_name:
                    log.debug("Found union member %s %s", item.name, union_attr_name)
                    enum_attr = item
            if enum_attr is None:
                error = f"Not found union member {union_attr_name}"
                raise ValueError(error)
            union_attr.union_key = enum_attr.name

    def class_parse(self, parent_package: Optional[ModelPackage], t_object) -> ModelClass:
        model_class = ModelClass(
            name=t_object.attr_name,
            object_id=t_object.attr_object_id,
            parent=parent_package,
        )
        if parent_package is not None:
            model_class.namespace = parent_package.namespace

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
                model_class.depends_on.append(connection.end_object_id)
                model_class.generalization = namespace

        # Add attributes
        TAttribute = base.classes.t_attribute
        t_attributes = self.session.query(TAttribute).filter(TAttribute.attr_object_id == model_class.object_id).all()
        for t_attribute in t_attributes:
            model_class.attributes.append(self.attribute_parse(parent_package, model_class, t_attribute))

        if self.config.stereotypes.idl_union in model_class.stereotypes:
            # Check if we have enumeration for that union
            connections = self.get_object_connections(model_class.object_id)
            for connection in connections:
                if connection.stereotype == "union":
                    # Need to add dependency, we don't care for direction here
                    if model_class.object_id != connection.end_object_id:
                        enum_id = connection.end_object_id
                    if model_class.object_id != connection.start_object_id:
                        enum_id = connection.start_object_id
                    model_class.depends_on.append(enum_id)
                    # We want to do this later, when our tree is build
                    # self.check_union_and_enum(model_class, self.class_parse(None, self.get_object(enum_id)))

        TObjectProperties = base.classes.t_objectproperties
        t_properties = (
            self.session.query(TObjectProperties)
            .filter(TObjectProperties.attr_object_id == model_class.object_id)
            .all()
        )
        for t_property in t_properties:
            if t_property.attr_property in self.config.annotations.keys():
                prop_config = self.config.annotations[t_property.attr_property]
                for item in [int, float, str]:
                    val = try_cast(t_property.attr_value, item)
                    if val is not None:
                        break
                if prop_config.idl_name is not None:
                    model_class.properties[prop_config.idl_name] = self.create_annotation(val)
                else:
                    model_class.properties[f"ext::{t_property.attr_property}"] = self.create_annotation(val)
            else:
                if t_property.attr_property not in ["URI", "isEncapsulated"]:
                    # Those are set by EA on bunch of things, so lets skip the warning
                    log.warning("Property %s is not configured", t_property.attr_property)
        for prop in self.get_custom_properties(t_object.attr_ea_guid):
            if prop.name in self.config.annotations.keys():
                prop_config = self.config.annotations[prop.name]
                value = prop.value
                if prop.type == "Boolean":
                    # This does something silly with isFinalSpecialization
                    # (as bool(-1) is True)
                    value = to_bool(prop.value)
                if value is False:
                    pass
                elif prop_config.idl_name is not None:
                    model_class.properties[prop_config.idl_name] = self.create_annotation(value)
                else:
                    model_class.properties[f"ext::{t_property.attr_property}"] = self.create_annotation(value)
            else:
                if prop.name not in []:
                    # Those are set by EA on bunch of things, so lets skip the warning
                    log.warning("Custom property %s is not configured", prop.name)

        # Check if we have one of proper stereotypes on all P7
        if self.config.stereotypes.main_class in model_class.stereotypes:
            if self.config.stereotypes.idl_union in model_class.stereotypes:
                model_class.is_union = True
            if self.config.stereotypes.idl_struct in model_class.stereotypes:
                model_class.is_struct = True
            if self.config.stereotypes.idl_enum in model_class.stereotypes:
                model_class.is_enum = True
            if self.config.stereotypes.idl_typedef in model_class.stereotypes:
                model_class.is_typedef = True

        # There is some validation
        validation.base.run("struct", self.config, cls=model_class)
        return model_class
