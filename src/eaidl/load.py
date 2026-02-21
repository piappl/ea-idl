from eaidl.utils import (
    to_bool,
    get_prop,
    enum_name_from_union_attr,
    try_cast,
)
from eaidl.tree_utils import find_class_by_id
from eaidl.config import Configuration
from eaidl.html_utils import strip_html
from eaidl.recursion import detect_types_needing_forward_declarations
from sqlalchemy.ext.automap import automap_base
from typing import Optional, Set, Dict
import sqlalchemy
from sqlalchemy.orm import Session
from typing import Any, List, Literal, Deque
import logging
import re
import uuid
import copy
import pydantic
import hashlib
from eaidl.validation.base import IDL_RESERVED_WORDS, DANGER_WORDS, apply_prefix_with_case
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
    ModelDiagram,
    ModelDiagramObject,
    ModelDiagramLink,
    ModelDiagramNote,
    ModelInteractionFragment,
    LinkedNote,
)
from eaidl import validation
from eaidl.sorting import topological_sort_classes, topological_sort_packages, CircularDependencyError

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


# find_class moved to eaidl.utils.find_class_by_id for reusability


class ModelParser:
    def __init__(self, config: Configuration) -> None:
        self.config = config
        self.engine = sqlalchemy.create_engine(config.database_url, echo=False, future=True)
        # Top level package for current tree
        self.root_package_guid: Optional[str] = None
        # Top level packages for all trees
        self.root_package_guids: List[str] = []

        self._validate_database_connection()
        base.prepare(autoload_with=self.engine)
        self._validate_database_schema()
        self.session = Session(self.engine)

    def _validate_database_connection(self) -> None:
        """Validate that the database can be connected to and has tables."""
        try:
            with self.engine.connect() as conn:
                # Test that we can actually connect
                conn.execute(sqlalchemy.text("SELECT 1"))
        except Exception as e:
            # Extract file path from database URL for better error messages
            db_path = self._extract_db_path()
            raise ConnectionError(
                f"Cannot connect to database: {self.config.database_url}\n"
                f"  File path: {db_path}\n"
                f"  Error: {e}\n"
                f"  Hint: Check that the file exists and is a valid SQLite database."
            ) from e

    def _validate_database_schema(self) -> None:
        """Validate that the database has the expected Enterprise Architect schema."""
        # Use SQLAlchemy inspector to check actual database tables
        # (not base.classes which persists from previous connections)
        inspector = sqlalchemy.inspect(self.engine)
        available_tables = inspector.get_table_names()

        # Check for required EA tables
        required_tables = ["t_package", "t_object", "t_attribute", "t_connector"]

        if not available_tables:
            db_path = self._extract_db_path()
            raise ValueError(
                f"Database has no tables: {self.config.database_url}\n"
                f"  File path: {db_path}\n"
                f"  Hint: The database file may be empty or not an Enterprise Architect database.\n"
                f"  EA databases are SQLite files with .qea or .eap extension."
            )

        missing_tables = [t for t in required_tables if t not in available_tables]
        if missing_tables:
            db_path = self._extract_db_path()
            raise ValueError(
                f"Database is missing required Enterprise Architect tables: {missing_tables}\n"
                f"  File path: {db_path}\n"
                f"  Available tables: {available_tables[:10]}{'...' if len(available_tables) > 10 else ''}\n"
                f"  Hint: This doesn't appear to be a valid Enterprise Architect database."
            )

        log.debug("Database schema validated: found %d tables", len(available_tables))

    def _extract_db_path(self) -> str:
        """Extract the file path from the database URL for error messages."""
        url = self.config.database_url
        # Handle sqlite URLs like "sqlite+pysqlite:///path/to/file.qea"
        if url.startswith("sqlite"):
            # Remove the dialect prefix
            if ":///" in url:
                return url.split(":///", 1)[1]
            elif "://" in url:
                return url.split("://", 1)[1]
        return url

    def load(self) -> List[ModelPackage]:
        whole: List[ModelPackage] = []
        # Create package to define annotations
        ext = ModelPackage(name="ext", package_id=-1, object_id=-1, guid=str(uuid.uuid4()))
        for name, prop in self.config.annotations.items():
            if prop.idl_default is True:
                continue
            if prop.idl_name is not None:
                name = prop.idl_name
            property_type = ModelPropertyType(property=name, notes=prop.notes, property_types=prop.idl_types)
            ext.property_types.append(property_type)
        whole.append(ext)
        TPackage = base.classes.t_package
        for root_package in self.config.root_packages:
            if root_package[0] == "{":
                root = self.session.query(TPackage).filter(TPackage.attr_ea_guid == root_package).scalar()
            else:
                root = self.session.query(TPackage).filter(TPackage.attr_name == root_package).scalar()
            if root is None:
                raise ValueError("Root package not found, check configuration")
            self.root_package_guids.append(root.attr_ea_guid)
        for root_package in self.config.root_packages:
            if root_package[0] == "{":
                root = self.session.query(TPackage).filter(TPackage.attr_ea_guid == root_package).scalar()
            else:
                root = self.session.query(TPackage).filter(TPackage.attr_name == root_package).scalar()
            if root is None:
                raise ValueError("Root package not found, check configuration")
            self.root_package_guid = root.attr_ea_guid
            package = self.package_parse(root, root=True)
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

            whole.append(package)
        self.get_union_connections(whole)
        self.get_values_connections(whole)
        return whole

    def get_union_connections(self, trees: List[ModelPackage]) -> Any:
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
                    log.error(
                        "Wrong union connection, expected enum and union, got %s, %s",
                        stereotypes,
                        obj.attr_name,
                    )
            union_class = find_class_by_id(trees, union_obj.attr_object_id)
            enum_class = find_class_by_id(trees, enum_obj.attr_object_id)
            if union_class is None or enum_class is None:
                # This is not really an error, if we are in package that is not
                # used (as we iterate on all connectors...)
                log.error(
                    "Cannot connect union to enum %s %s, if it is a different package this is fine",
                    union_obj.attr_name,
                    enum_obj.attr_name,
                )
                continue
            self.check_union_and_enum(union_class, enum_class)

    def get_values_connections(self, trees: List[ModelPackage]) -> Any:
        """Process <<values>> connectors that link classes to enums providing allowed values."""
        TConnector = base.classes.t_connector
        t_connectors = self.session.query(TConnector).filter(TConnector.attr_stereotype == "values").all()
        for connector in t_connectors:
            # For <<values>>, Start is the struct/class and End is the enum
            struct_obj = self.get_object(connector.attr_start_object_id)
            enum_obj = self.get_object(connector.attr_end_object_id)

            struct_class = find_class_by_id(trees, struct_obj.attr_object_id)
            enum_class = find_class_by_id(trees, enum_obj.attr_object_id)

            if struct_class is None or enum_class is None:
                # Not an error if classes are in different packages
                log.debug(
                    "Cannot connect struct to values enum %s %s, if it is a different package this is fine",
                    struct_obj.attr_name,
                    enum_obj.attr_name,
                )
                continue

            # Verify enum_class is actually an enum
            enum_stereotypes = self.get_stereotypes(enum_obj.attr_ea_guid)
            if self.config.stereotypes.idl_enum not in enum_stereotypes:
                log.error(
                    "Wrong values connection, expected enum, got %s for %s",
                    enum_stereotypes,
                    enum_obj.attr_name,
                )
                continue

            # Store the values_enum relationship on the class
            enum_full_name = "::".join(enum_class.namespace + [enum_class.name])
            struct_class.values_enums.append(enum_full_name)

            log.debug(
                "Connected struct %s to values enum %s",
                struct_class.name,
                enum_class.name,
            )

    def get_object_connections(
        self, object_id: int, mode: Literal["source", "destination", "both"] = "both"
    ) -> List[ModelConnection]:
        """
        It raises pydantic.ValidationError which need to be handled upstream where we have more context.

        """
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
            if t_connector.attr_connector_type == "NoteLink":
                continue
            # Wrap single stereotype in list
            stereotypes = [t_connector.attr_stereotype] if t_connector.attr_stereotype else []

            conn = ModelConnection(
                connector_id=t_connector.attr_connector_id,
                connector_type=t_connector.attr_connector_type,
                direction=t_connector.attr_direction,
                connector_sub_type=t_connector.attr_subtype,
                start_object_id=t_connector.attr_start_object_id,
                end_object_id=t_connector.attr_end_object_id,
                stereotypes=stereotypes,
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
            ret.append(conn)
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
        package.notes = strip_html(t_package_object.attr_note, special=True)
        package.stereotypes = self.get_stereotypes(package.guid)
        if parse_children:
            self.package_parse_children(package)
        # Load diagrams for this package
        package.diagrams = self.load_package_diagrams(package.package_id)
        # Load unlinked notes for this package
        package.unlinked_notes = self.get_unlinked_notes(package.package_id)
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

        # Detect circular dependencies for recursion support
        scc_map: Dict[int, Set[int]] = {}
        classes_list = list(classes)  # Convert to list once

        # Resolve dependencies before topological sort
        # This ensures typedefs and classes appear after the types they reference
        self.resolve_attribute_dependencies(classes_list)
        self.resolve_typedef_dependencies(classes_list)

        if self.config.allow_recursive_structs and classes_list:
            try:
                # Create a temporary package with just these classes for cycle detection
                temp_pkg = ModelPackage(
                    name=parent_package.name,
                    package_id=parent_package.package_id,
                    object_id=parent_package.object_id,
                    guid=parent_package.guid,
                )
                temp_pkg.classes = classes_list
                temp_pkg.namespace = parent_package.namespace

                # Detect cycles (this validates same-module requirement)
                needs_forward_decl, scc_map = detect_types_needing_forward_declarations([temp_pkg])

                # Mark classes that need forward declarations
                for cls in classes_list:
                    if cls.object_id in needs_forward_decl:
                        cls.needs_forward_declaration = True

            except ValueError as e:
                # Re-raise validation errors (e.g., cross-module cycles)
                log.error(f"Recursion validation failed in package {parent_package.name}: {e}")
                raise

        try:
            parent_package.classes = topological_sort_classes(classes_list, scc_map)
        except CircularDependencyError as e:
            log.error("Circular dependency detected in classes for package %s: %s", parent_package.name, e)
            # Depending on desired behavior, you might want to raise, return, or handle differently
            raise e
        log.debug("Sorting classes %s done", parent_package.name)

        log.debug("Sorting package %s", parent_package.name)
        try:
            parent_package.packages = topological_sort_packages(
                list(packages), self.get_all_depends_on, self.get_all_class_id
            )
        except CircularDependencyError as e:
            log.error("Circular dependency detected in packages for package %s: %s", parent_package.name, e)
            # Depending on desired behavior, you might want to raise, return, or handle differently
            raise e
        log.debug("Sorting packages of %s done", parent_package.name)

        # Do some statictics that templates can use later
        for cls in parent_package.classes:
            if self.config.stereotypes.idl_struct in cls.stereotypes:
                parent_package.info.structs += 1
            if self.config.stereotypes.idl_map in cls.stereotypes:
                parent_package.info.maps += 1
            if self.config.stereotypes.idl_typedef in cls.stereotypes:
                parent_package.info.typedefs += 1
            if self.config.stereotypes.idl_union in cls.stereotypes:
                parent_package.info.unions += 1
            if self.config.stereotypes.idl_enum in cls.stereotypes:
                parent_package.info.enums += 1
        parent_package.info.packages = len(parent_package.packages)
        has_definition_class = (
            parent_package.info.structs > 0 or parent_package.info.unions > 0 or parent_package.info.maps > 0
        )
        has_definition_child = any(pkg.info.create_definition for pkg in parent_package.packages)
        parent_package.info.create_definition = has_definition_class or has_definition_child

    def get_object(self, object_id: int) -> Any:
        TObject = base.classes.t_object
        return self.session.query(TObject).filter(TObject.attr_object_id == object_id).scalar()

    def get_linked_notes(self, object_id: int) -> List[LinkedNote]:
        """Get notes linked to an object via NoteLink connectors.

        Notes are always loaded for spell checking, regardless of output_linked_notes setting.

        :param object_id: object identifier
        :return: list of LinkedNote objects with full metadata
        """
        notes = []
        TConnector = base.classes.t_connector
        TObject = base.classes.t_object

        # NoteLink connectors have Start_Object_ID = object, End_Object_ID = note
        t_connectors = (
            self.session.query(TConnector)
            .filter(
                TConnector.attr_connector_type == "NoteLink",
                TConnector.attr_start_object_id == object_id,
            )
            .all()
        )

        for connector in t_connectors:
            note_obj = (
                self.session.query(TObject).filter(TObject.attr_object_id == connector.attr_end_object_id).scalar()
            )
            if note_obj and note_obj.attr_object_type == "Note" and note_obj.attr_note:
                content_html = note_obj.attr_note
                content_md = strip_html(content_html)
                if content_md:
                    checksum = hashlib.md5(content_html.encode("utf-8")).hexdigest()
                    notes.append(
                        LinkedNote(
                            note_id=note_obj.attr_object_id,
                            content=content_md,
                            content_html=content_html,
                            checksum=checksum,
                        )
                    )

        return notes

    def get_unlinked_notes(self, package_id: int) -> List[LinkedNote]:
        """Get notes in a package that are not linked to any object.

        Notes are always loaded for spell checking, regardless of output_unlinked_notes setting.

        :param package_id: package identifier
        :return: list of LinkedNote objects with full metadata
        """
        notes = []
        TObject = base.classes.t_object
        TConnector = base.classes.t_connector

        # Get all note objects in this package
        note_objects = (
            self.session.query(TObject)
            .filter(
                TObject.attr_package_id == package_id,
                TObject.attr_object_type == "Note",
            )
            .all()
        )

        for note_obj in note_objects:
            # Check if this note is linked to anything via NoteLink
            linked_connector = (
                self.session.query(TConnector)
                .filter(
                    TConnector.attr_connector_type == "NoteLink",
                    TConnector.attr_end_object_id == note_obj.attr_object_id,
                )
                .first()
            )

            # If not linked and has content, add it
            if not linked_connector and note_obj.attr_note:
                content_html = note_obj.attr_note
                content_md = strip_html(content_html)
                if content_md:
                    checksum = hashlib.md5(content_html.encode("utf-8")).hexdigest()
                    notes.append(
                        LinkedNote(
                            note_id=note_obj.attr_object_id,
                            content=content_md,
                            content_html=content_html,
                            checksum=checksum,
                        )
                    )

        return notes

    def load_package_diagrams(self, package_id: int) -> List[ModelDiagram]:
        """Load all diagrams for a package.

        :param package_id: package identifier
        :return: list of diagrams in this package
        """
        TDiagram = base.classes.t_diagram
        t_diagrams = self.session.query(TDiagram).filter(TDiagram.attr_package_id == package_id).all()

        diagrams = []
        for t_diagram in t_diagrams:
            try:
                diagram = self.diagram_parse(t_diagram)
                diagrams.append(diagram)
            except Exception as e:
                log.warning(
                    "Failed to parse diagram %s (ID: %s): %s",
                    getattr(t_diagram, "attr_name", "unknown"),
                    getattr(t_diagram, "attr_diagram_id", "unknown"),
                    str(e),
                )
                continue

        return diagrams

    def diagram_parse(self, t_diagram: Any) -> ModelDiagram:
        """Parse a single EA diagram.

        :param t_diagram: SQLAlchemy t_diagram object
        :return: ModelDiagram with objects and links loaded
        """
        diagram = ModelDiagram(
            diagram_id=t_diagram.attr_diagram_id,
            package_id=t_diagram.attr_package_id,
            name=t_diagram.attr_name,
            diagram_type=getattr(t_diagram, "attr_diagram_type", None),
            diagram_notes=getattr(t_diagram, "attr_notes", None),
            stereotype=getattr(t_diagram, "attr_stereotype", None),
            author=getattr(t_diagram, "attr_author", None),
            created_date=getattr(t_diagram, "attr_createddate", None),
            modified_date=getattr(t_diagram, "attr_modifieddate", None),
            guid=getattr(t_diagram, "attr_ea_guid", None),
            cx=getattr(t_diagram, "attr_cx", None),
            cy=getattr(t_diagram, "attr_cy", None),
            scale=getattr(t_diagram, "attr_scale", None),
        )

        # Load objects, links, notes, and fragments
        diagram.objects = self.load_diagram_objects(diagram.diagram_id)
        diagram.links = self.load_diagram_links(diagram.diagram_id)
        diagram.notes = self.load_diagram_notes(diagram.diagram_id)
        diagram.fragments = self.load_interaction_fragments(diagram.diagram_id)

        return diagram

    def load_diagram_objects(self, diagram_id: int) -> List[ModelDiagramObject]:
        """Load positioned objects on a diagram.

        :param diagram_id: diagram identifier
        :return: list of objects positioned on this diagram
        """
        TDiagramObjects = base.classes.t_diagramobjects
        t_objects = (
            self.session.query(TDiagramObjects)
            .filter(TDiagramObjects.attr_diagram_id == diagram_id)
            .order_by(TDiagramObjects.attr_sequence)
            .all()
        )

        objects = []
        for t_obj in t_objects:
            obj = ModelDiagramObject(
                object_id=t_obj.attr_object_id,
                diagram_id=t_obj.attr_diagram_id,
                rect_top=t_obj.attr_recttop,
                rect_left=t_obj.attr_rectleft,
                rect_right=t_obj.attr_rectright,
                rect_bottom=t_obj.attr_rectbottom,
                sequence=t_obj.attr_sequence,
                object_style=getattr(t_obj, "attr_objectstyle", None),
            )
            objects.append(obj)

        return objects

    def load_diagram_links(self, diagram_id: int) -> List[ModelDiagramLink]:
        """Load connector links on a diagram.

        :param diagram_id: diagram identifier
        :return: list of connector links on this diagram
        """
        TDiagramLinks = base.classes.t_diagramlinks
        t_links = self.session.query(TDiagramLinks).filter(TDiagramLinks.attr_diagramid == diagram_id).all()

        links = []
        for t_link in t_links:
            link = ModelDiagramLink(
                connector_id=t_link.attr_connectorid,
                diagram_id=t_link.attr_diagramid,
                geometry=getattr(t_link, "attr_geometry", None),
                style=getattr(t_link, "attr_style", None),
                hidden=getattr(t_link, "attr_hidden", 0),
                path=getattr(t_link, "attr_path", None),
            )
            links.append(link)

        return links

    def load_diagram_notes(self, diagram_id: int) -> List["ModelDiagramNote"]:
        """Load notes on a diagram.

        :param diagram_id: diagram identifier
        :return: list of notes on this diagram
        """
        TDiagramObjects = base.classes.t_diagramobjects
        TObject = base.classes.t_object

        # Query for notes: join t_diagramobjects with t_object where Object_Type = 'Note'
        notes_query = (
            self.session.query(TDiagramObjects, TObject)
            .join(TObject, TDiagramObjects.attr_object_id == TObject.attr_object_id)
            .filter(TDiagramObjects.attr_diagram_id == diagram_id)
            .filter(TObject.attr_object_type == "Note")
            .all()
        )

        notes = []
        for t_diag_obj, t_obj in notes_query:
            # EA stores note text in either Name or Note field
            name = getattr(t_obj, "attr_name", None)
            note_text = getattr(t_obj, "attr_note", None)
            # Use note_text as fallback if name is None
            if name is None and note_text:
                name = note_text.strip()
            elif name is None:
                name = ""

            note = ModelDiagramNote(
                object_id=t_obj.attr_object_id,
                diagram_id=diagram_id,
                name=name,
                note_text=note_text,
                rect_left=getattr(t_diag_obj, "attr_rectleft", 0),
                rect_top=getattr(t_diag_obj, "attr_recttop", 0),
                rect_right=getattr(t_diag_obj, "attr_rectright", 0),
                rect_bottom=getattr(t_diag_obj, "attr_rectbottom", 0),
            )
            notes.append(note)

        return notes

    def load_interaction_fragments(self, diagram_id: int) -> List["ModelInteractionFragment"]:
        """Load interaction fragments (alt, opt, loop, etc.) from a sequence diagram.

        :param diagram_id: diagram identifier
        :return: list of interaction fragments on this diagram
        """
        TObject = base.classes.t_object
        TDiagramObjects = base.classes.t_diagramobjects

        # Query for interaction fragments via t_diagramobjects join, including positioning
        fragments_query = (
            self.session.query(TObject, TDiagramObjects)
            .join(TDiagramObjects, TObject.attr_object_id == TDiagramObjects.attr_object_id)
            .filter(TDiagramObjects.attr_diagram_id == diagram_id)
            .filter((TObject.attr_object_type == "InteractionFragment") | (TObject.attr_object_type == "Interaction"))
            .all()
        )

        fragments = []
        for t_obj, t_diag_obj in fragments_query:
            fragment = ModelInteractionFragment(
                object_id=t_obj.attr_object_id,
                name=getattr(t_obj, "attr_name", ""),
                stereotype=getattr(t_obj, "attr_stereotype", None),
                note=getattr(t_obj, "attr_note", None),
                parent_id=getattr(t_obj, "attr_parentid", None),
                rect_top=getattr(t_diag_obj, "attr_recttop", 0),
                rect_bottom=getattr(t_diag_obj, "attr_rectbottom", 0),
            )
            fragments.append(fragment)

        return fragments

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

    def resolve_attribute_dependencies(self, classes: List[ModelClass]) -> None:
        """
        Resolve dependencies for all classes by looking at their attributes.
        This ensures structs and unions correctly depend on the types of their members.
        """
        name_to_class = {cls.name: cls for cls in classes}

        for cls in classes:
            if cls.is_typedef:
                continue

            for attr in cls.attributes:
                if not attr.type or self.config.is_primitive_type(attr.type):
                    continue

                # If the attribute has an explicit namespace (e.g. from a connector),
                # it must match the current package's namespace to be considered a local dependency.
                if attr.namespace and attr.namespace != cls.namespace:
                    continue

                # Look up the referenced type in the same package
                # (Cross-package dependencies are handled by topological_sort_packages)
                ref_class = name_to_class.get(attr.type)
                if ref_class and ref_class.object_id not in cls.depends_on:
                    cls.depends_on.append(ref_class.object_id)
                    log.debug(f"Added attribute dependency: {cls.name} -> {ref_class.name} (attribute: {attr.name})")

    def resolve_typedef_dependencies(self, classes: List[ModelClass]) -> None:
        """
        Resolve dependencies for typedefs by extracting referenced types from parent_type.
        """
        name_to_class = {cls.name: cls for cls in classes}

        for cls in classes:
            if not cls.is_typedef or not cls.parent_type:
                continue

            # Extract referenced type name from parent_type
            ref_type_name = None

            # Try to extract from sequence<...>
            match = re.search(r"sequence<(.+?)>", cls.parent_type)
            if match:
                ref_type_name = match.group(1).strip()
            else:
                # Try to extract from map<key, value> - get the value type
                match = re.search(r"map<[^,]+,\s*(.+?)>", cls.parent_type)
                if match:
                    ref_type_name = match.group(1).strip()
                else:
                    # Direct type reference (typedef MyType OtherType)
                    ref_type_name = cls.parent_type.strip()

            if not ref_type_name or self.config.is_primitive_type(ref_type_name):
                # Skip primitives
                continue

            # Look up the referenced type in the same package
            ref_class = name_to_class.get(ref_type_name)
            if not ref_class:
                # Referenced type not in same package - skip
                continue

            # Add dependency for ordering
            if ref_class.object_id not in cls.depends_on:
                cls.depends_on.append(ref_class.object_id)
                log.debug(
                    f"Added typedef dependency: {cls.name} -> {ref_class.name} "
                    f"(from parent_type: {cls.parent_type})"
                )

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
            if package.attr_ea_guid in self.root_package_guids:
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
        """Parse EA attribute into ModelAttribute.

        Orchestrates parsing of attribute metadata, multiplicity, defaults, and associations.
        """
        attribute = ModelAttribute(
            name=t_attribute.attr_name,
            alias=t_attribute.attr_name,
            type=t_attribute.attr_type,
            guid=t_attribute.attr_ea_guid,
            attribute_id=t_attribute.attr_object_id,
            parent=parent_class,
        )

        # Handle reserved words
        reserved_words = self.config.reserved_words or IDL_RESERVED_WORDS
        danger_words = self.config.danger_words or DANGER_WORDS

        if attribute.name in reserved_words:
            if self.config.reserved_words_action == "prefix":
                attribute.name = apply_prefix_with_case(
                    attribute.name, self.config.reserved_words_prefix, is_class=False
                )

        # Handle danger words
        if attribute.name in danger_words:
            if self.config.danger_words_action == "prefix":
                attribute.name = apply_prefix_with_case(attribute.name, self.config.danger_words_prefix, is_class=False)

        attribute.namespace = []
        attribute.stereotypes = self.get_stereotypes(attribute.guid)
        attribute.is_optional = "optional" in attribute.stereotypes
        attribute.is_ordered = to_bool(t_attribute.attr_isordered)
        attribute.is_static = to_bool(t_attribute.attr_isstatic)
        attribute.notes = strip_html(t_attribute.attr_notes, special=True)
        attribute.linked_notes = self.get_linked_notes(attribute.attribute_id)

        self._parse_attribute_multiplicity(attribute, t_attribute)
        self._parse_attribute_default_value(attribute, t_attribute)

        if attribute.is_optional:
            attribute.properties["optional"] = self.create_annotation(None)

        self._parse_attribute_association(attribute, parent_class)

        validation.base.run("attribute", self.config, attribute=attribute, cls=parent_class)
        return attribute

    def _parse_attribute_multiplicity(self, attribute: ModelAttribute, t_attribute) -> None:
        """Parse attribute multiplicity (bounds and collection flags)."""
        attribute.lower_bound = t_attribute.attr_lowerbound
        attribute.upper_bound = t_attribute.attr_upperbound
        attribute.is_collection = to_bool(t_attribute.attr_iscollection)

        if not attribute.is_collection:
            return

        if attribute.lower_bound and attribute.lower_bound != "*":
            attribute.lower_bound_number = int(attribute.lower_bound)
            if attribute.lower_bound_number != 0:
                attribute.properties[self.config.min_items] = ModelAnnotation(
                    value=attribute.lower_bound_number, value_type="int"
                )

        if attribute.upper_bound and attribute.upper_bound != "*":
            attribute.upper_bound_number = int(attribute.upper_bound)
            attribute.properties[self.config.max_items] = ModelAnnotation(
                value=attribute.upper_bound_number, value_type="int"
            )

    def _parse_attribute_default_value(self, attribute: ModelAttribute, t_attribute) -> None:
        """Parse attribute default value."""
        if t_attribute.attr_default is None:
            return

        attr_type = t_attribute.attr_type
        attr_default = t_attribute.attr_default

        if attr_type == "str":
            attribute.properties["default"] = ModelAnnotation(value=attr_default, value_type=attr_type)
        elif attr_type in ["int", "float"] and attr_default:
            attribute.properties["default"] = ModelAnnotation(value=attr_default, value_type=attr_type)
        elif attr_type and attr_default:
            attribute.properties["default"] = ModelAnnotation(value=attr_default, value_type="object")
        elif attr_default:  # No type but has default
            log.error("What is type here? %s %s %s", attribute.name, attr_type, attr_default)

    def _parse_attribute_association(self, attribute: ModelAttribute, parent_class: ModelClass) -> None:
        """Parse attribute association connectors."""
        try:
            connections = self.get_object_connections(parent_class.object_id, mode="source")
        except pydantic.ValidationError:
            log.error(attribute.model_dump_json(indent=4))
            return

        for connection in connections:
            if connection.connector_type != "Association":
                continue
            if connection.destination.role != attribute.alias:
                continue

            destination = self.get_object(connection.end_object_id)
            if connection.end_object_id not in parent_class.depends_on:
                parent_class.depends_on.append(connection.end_object_id)

            attribute.namespace = self.get_namespace(destination.attr_package_id)
            if destination.attr_name == attribute.type:
                attribute.connector = connection
                # Update is_collection if connector specifies it via cardinality
                if connection.destination.cardinality in ["*", "0..*", "1..*"]:
                    attribute.is_collection = True
                break

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
        try:
            assert self.config.stereotypes.idl_union in model_union.stereotypes
            assert self.config.stereotypes.idl_enum in model_enum.stereotypes
            assert len(model_enum.attributes) >= len(model_union.attributes)
        except AssertionError as error:
            descr = f"Wrong attributes in {model_union.name} or {model_enum.name}"
            raise ValueError(descr) from error
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
            union_attr.union_namespace = model_enum.namespace

    def class_parse(self, parent_package: Optional[ModelPackage], t_object) -> ModelClass:
        """Parse EA object into ModelClass.

        Orchestrates parsing of class metadata, attributes, dependencies, and properties.
        """
        model_class = ModelClass(
            name=t_object.attr_name,
            object_id=t_object.attr_object_id,
            guid=t_object.attr_ea_guid,
            parent=parent_package,
        )

        # Handle reserved words for class names
        reserved_words = self.config.reserved_words or IDL_RESERVED_WORDS
        danger_words = self.config.danger_words or DANGER_WORDS

        if model_class.name in reserved_words:
            if self.config.reserved_words_action == "prefix":
                model_class.name = apply_prefix_with_case(
                    model_class.name, self.config.reserved_words_prefix, is_class=True
                )

        # Handle danger words for class names
        if model_class.name in danger_words:
            if self.config.danger_words_action == "prefix":
                model_class.name = apply_prefix_with_case(
                    model_class.name, self.config.danger_words_prefix, is_class=True
                )

        if parent_package is not None:
            model_class.namespace = parent_package.namespace

        self._parse_class_basic_metadata(model_class, t_object)
        self._parse_generalization(model_class)
        self._parse_class_attributes(parent_package, model_class)
        self._parse_typedef_dependencies(model_class)
        self._parse_union_dependencies(model_class)
        self._parse_class_properties(model_class, t_object)

        model_class.linked_notes = self.get_linked_notes(model_class.object_id)
        self._set_class_type_flags(model_class)

        validation.base.run("struct", self.config, cls=model_class)
        return model_class

    def _parse_class_basic_metadata(self, model_class: ModelClass, t_object) -> None:
        """Parse basic class metadata (stereotypes, abstract flag, parent type, notes)."""
        model_class.stereotypes = self.get_stereotypes(t_object.attr_ea_guid)
        model_class.is_abstract = to_bool(t_object.attr_abstract)
        if t_object.attr_genlinks is not None:
            model_class.parent_type = (
                m.group(1)
                if (m := re.search(r"(?:Parent|Implements)=(.*?);", t_object.attr_genlinks)) is not None
                else None
            )
        model_class.notes = strip_html(t_object.attr_note, special=True)

    def _parse_generalization(self, model_class: ModelClass) -> None:
        """Parse generalization (inheritance) links."""
        try:
            connections = self.get_object_connections(model_class.object_id, mode="source")
        except pydantic.ValidationError as e:
            log.error("Unable to create union connections %s %s", model_class.namespace, model_class.name)
            log.exception(e)
            return

        for connection in connections:
            if connection.connector_type == "Generalization":
                destination = self.get_object(connection.end_object_id)
                namespace = self.get_namespace(destination.attr_package_id)
                namespace.append(destination.attr_name)
                model_class.depends_on.append(connection.end_object_id)
                model_class.generalization = namespace

    def _parse_class_attributes(self, parent_package: Optional[ModelPackage], model_class: ModelClass) -> None:
        """Parse class attributes."""
        TAttribute = base.classes.t_attribute
        t_attributes = (
            self.session.query(TAttribute)
            .filter(TAttribute.attr_object_id == model_class.object_id)
            .order_by(TAttribute.attr_pos)
            .all()
        )
        for t_attribute in t_attributes:
            model_class.attributes.append(self.attribute_parse(parent_package, model_class, t_attribute))

    def _parse_typedef_dependencies(self, model_class: ModelClass) -> None:
        """Parse typedef-specific dependencies (Association connectors)."""
        if self.config.stereotypes.idl_typedef not in model_class.stereotypes:
            return

        try:
            connections = self.get_object_connections(model_class.object_id, mode="source")
        except pydantic.ValidationError as e:
            log.error("Unable to get typedef connections %s %s", model_class.namespace, model_class.name)
            log.exception(e)
            return

        for connection in connections:
            if connection.connector_type == "Association":
                ref_type_id = connection.end_object_id
                if ref_type_id not in model_class.depends_on:
                    model_class.depends_on.append(ref_type_id)
                    log.debug(
                        f"Added typedef dependency from Association connector: "
                        f"{model_class.name} -> object_id {ref_type_id} "
                        f"(parent_type: {model_class.parent_type})"
                    )

    def _parse_union_dependencies(self, model_class: ModelClass) -> None:
        """Parse union-specific dependencies (enum connections)."""
        if self.config.stereotypes.idl_union not in model_class.stereotypes:
            return

        try:
            connections = self.get_object_connections(model_class.object_id)
        except pydantic.ValidationError as e:
            log.error("Unable to create union connections %s %s", model_class.namespace, model_class.name)
            log.exception(e)
            return

        for connection in connections:
            if "union" in connection.stereotypes:
                enum_id = (
                    connection.end_object_id
                    if model_class.object_id != connection.end_object_id
                    else connection.start_object_id
                )
                model_class.depends_on.append(enum_id)

    def _parse_class_properties(self, model_class: ModelClass, t_object) -> None:
        """Parse class properties and annotations from EA database."""
        # Parse properties from t_objectproperties
        TObjectProperties = base.classes.t_objectproperties
        t_properties = (
            self.session.query(TObjectProperties)
            .filter(TObjectProperties.attr_object_id == model_class.object_id)
            .all()
        )
        for t_property in t_properties:
            if t_property.attr_property in self.config.annotations.keys():
                prop_config = self.config.annotations[t_property.attr_property]
                val = None
                for item in [int, float, str]:
                    val = try_cast(t_property.attr_value, item)
                    if val is not None:
                        break

                if prop_config.idl_default:
                    prop_name = prop_config.idl_name if prop_config.idl_name else t_property.attr_property
                    model_class.properties[prop_name] = self.create_annotation(val)
                else:
                    model_class.properties[f"ext::{t_property.attr_property}"] = self.create_annotation(val)
            elif t_property.attr_property not in ["URI", "isEncapsulated"]:
                log.warning("Property %s is not configured", t_property.attr_property)

        # Parse annotations from stereotypes
        for stereotype in model_class.stereotypes:
            if stereotype in self.config.annotations_from_stereotypes and stereotype in self.config.annotations.keys():
                prop_config = self.config.annotations[stereotype]
                if prop_config.idl_default:
                    prop_name = prop_config.idl_name if prop_config.idl_name else stereotype
                    model_class.properties[prop_name] = self.create_annotation(None)
                else:
                    model_class.properties[f"ext::{stereotype}"] = self.create_annotation(None)

        # Parse custom properties
        for prop in self.get_custom_properties(t_object.attr_ea_guid):
            if prop.name in self.config.annotations.keys():
                prop_config = self.config.annotations[prop.name]
                value = to_bool(prop.value) if prop.type == "Boolean" else prop.value

                if value is not False:
                    if prop_config.idl_default:
                        prop_name = prop_config.idl_name if prop_config.idl_name else prop.name
                        model_class.properties[prop_name] = self.create_annotation(value)
                    else:
                        model_class.properties[f"ext::{prop.name}"] = self.create_annotation(value)
            elif prop.name not in []:
                log.warning("Custom property %s is not configured", prop.name)

    def _set_class_type_flags(self, model_class: ModelClass) -> None:
        """Set type flags (is_union, is_struct, etc.) based on stereotypes."""
        if self.config.stereotypes.main_class not in model_class.stereotypes:
            return

        if self.config.stereotypes.idl_union in model_class.stereotypes:
            model_class.is_union = True
        if self.config.stereotypes.idl_struct in model_class.stereotypes:
            model_class.is_struct = True
        if self.config.stereotypes.idl_map in model_class.stereotypes:
            model_class.is_map = True
        if self.config.stereotypes.idl_enum in model_class.stereotypes:
            model_class.is_enum = True
        if self.config.stereotypes.idl_typedef in model_class.stereotypes:
            model_class.is_typedef = True
