"""JSON Schema to EA-IDL importer.

This module provides functionality to import JSON Schema files into EA databases,
converting JSON schema types to IDL structures with proper stereotypes.
"""

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import sqlalchemy
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session

from eaidl.config import Configuration
from eaidl.model import ModelAnnotation, ModelAttribute, ModelClass, ModelPackage

log = logging.getLogger(__name__)

# Create base for automap
base = automap_base()


@sqlalchemy.event.listens_for(base.metadata, "column_reflect")
def column_reflect(inspector, table, column_info):
    """Convert column names to lowercase for cross-database compatibility."""
    column_info["key"] = "attr_%s" % column_info["name"].lower()


class JsonSchemaImporter:
    """Import JSON Schema files into EA database as IDL structures."""

    def __init__(self, config: Configuration, schema_file: str, package_name: str):
        """Initialize the JSON schema importer.

        Args:
            config: EA-IDL configuration with database connection
            schema_file: Path to JSON schema file
            package_name: Name for root package to create
        """
        self.config = config
        self.schema_file = Path(schema_file)
        self.package_name = package_name
        self.schema_data: Dict[str, Any] = {}
        self.definitions: Dict[str, Any] = {}
        self.next_object_id = 1000  # Start high to avoid conflicts during parsing
        self.next_attribute_id = 1000
        self.next_package_id = 1000
        self.model_package_id = 0  # Will be set from database during import
        self.created_types: Set[str] = set()  # Track created type names to avoid duplicates
        self._schema_to_typedef: Dict[int, str] = {}  # Map schema object ID to typedef name to handle recursion
        self.type_to_object_id: Dict[str, int] = {}  # Map type names to Object_IDs for Classifier field
        self._processing_stack: List[str] = []  # Track currently processing definitions to detect cycles

        # Type mapping from JSON schema to IDL
        self.type_mapping = {
            "string": "string",
            "number": "double",
            "integer": "long",
            "boolean": "boolean",
        }

    def parse_schema(self) -> ModelPackage:
        """Parse JSON schema and create ModelPackage tree.

        Returns:
            Root ModelPackage containing all parsed classes
        """
        log.info(f"Parsing JSON schema from {self.schema_file}")

        # Load JSON schema file
        with open(self.schema_file) as f:
            self.schema_data = json.load(f)

        # Extract definitions ($defs in JSON Schema 2020-12)
        self.definitions = self.schema_data.get("$defs", {})

        # Create root package
        root_package = ModelPackage(
            name=self.package_name,
            package_id=self.next_package_id,
            object_id=self.next_object_id,
            guid=self._generate_guid(),
            namespace=[self.package_name],
            stereotypes=[self.config.stereotypes.package],
        )
        self.next_package_id += 1
        self.next_object_id += 1

        # Create child package to hold all classes
        # (IDL template expects classes in child packages, not root)
        child_package = ModelPackage(
            name="types",
            package_id=self.next_package_id,
            object_id=self.next_object_id,
            guid=self._generate_guid(),
            namespace=[self.package_name, "types"],
            stereotypes=[self.config.stereotypes.package],
            parent=root_package,
        )
        self.next_package_id += 1
        self.next_object_id += 1
        root_package.packages.append(child_package)

        # Check if root schema defines a union type (oneOf/anyOf)
        if "oneOf" in self.schema_data or "anyOf" in self.schema_data:
            # Use $dynamicAnchor as the type name, or default to package name
            root_type_name = self.schema_data.get("$dynamicAnchor", self.package_name)
            root_type_name = self._to_pascal_case(root_type_name)
            cls = self._create_union_class(root_type_name, self.schema_data, child_package)
            if cls:
                child_package.classes.append(cls)
                log.info(f"Created root union type: {root_type_name}")

        # Process all definitions
        for def_name, def_schema in self.definitions.items():
            cls = self._parse_definition(def_name, def_schema, child_package)
            if cls:
                child_package.classes.append(cls)

        log.debug("Finished processing all definitions")
        log.info(f"Created {len(child_package.classes)} classes from schema")
        return root_package

    def _parse_definition(self, name: str, schema: Dict[str, Any], parent: ModelPackage) -> Optional[ModelClass]:
        """Parse a single schema definition into a ModelClass.

        Args:
            name: Definition name
            schema: Schema definition
            parent: Parent package

        Returns:
            ModelClass or None if schema should be skipped
        """
        # Convert name to PascalCase
        class_name = self._to_pascal_case(name)

        # Check if we're already processing this definition (cycle detection)
        if class_name in self._processing_stack:
            log.debug(f"Skipping {class_name} - already in processing stack (cycle detected)")
            return None

        log.debug(f"Processing definition: {name}")

        # Check for duplicate
        if class_name in self.created_types:
            log.warning(f"Duplicate type name {class_name}, skipping")
            return None

        # Add to processing stack AND created_types before creating to prevent circular references
        self._processing_stack.append(class_name)
        self.created_types.add(class_name)

        try:
            # Determine type based on schema
            if "enum" in schema:
                return self._create_enum_class(class_name, schema, parent)
            elif "oneOf" in schema or "anyOf" in schema:
                return self._create_union_class(class_name, schema, parent)
            elif schema.get("type") == "object" or "properties" in schema:
                return self._create_struct_class(class_name, schema, parent)
            elif schema.get("type") == "array":
                return self._create_typedef_class(class_name, schema, parent)
            elif schema.get("type") in ["string", "number", "integer", "boolean"]:
                # Create typedef for primitives with constraints
                return self._create_typedef_class(class_name, schema, parent)
            else:
                # Skip other types
                log.debug(f"Skipping non-class definition: {name}")
                # Remove from created_types if we're not creating anything
                self.created_types.discard(class_name)
                return None
        finally:
            # Remove from processing stack when done
            if class_name in self._processing_stack:
                self._processing_stack.remove(class_name)

    def _create_struct_class(self, name: str, schema: Dict[str, Any], parent: ModelPackage) -> ModelClass:
        """Create a struct class from object schema.

        Args:
            name: Class name
            schema: Object schema
            parent: Parent package

        Returns:
            ModelClass with idlStruct stereotype
        """
        # Check if this struct already exists (circular reference detection)
        existing = next((cls for cls in parent.classes if cls.name == name and cls.is_struct), None)
        if existing:
            log.debug(f"Struct {name} already exists, reusing for circular reference")
            return existing

        # Add to created types immediately to prevent infinite recursion
        self.created_types.add(name)

        cls = ModelClass(
            name=name,
            object_id=self.next_object_id,
            namespace=parent.namespace,
            stereotypes=[self.config.stereotypes.main_class, self.config.stereotypes.idl_struct],
            is_struct=True,
            parent=parent,
            notes=schema.get("description"),
        )
        object_id = self.next_object_id
        self.next_object_id += 1

        # Register type for Classifier field lookups
        self.type_to_object_id[name] = object_id

        # Process properties
        properties = schema.get("properties", {})
        required_props = schema.get("required", [])

        for prop_name, prop_schema in properties.items():
            attr = self._create_attribute(prop_name, prop_schema, cls, prop_name not in required_props)
            if attr:
                cls.attributes.append(attr)

        return cls

    def _create_enum_class(self, name: str, schema: Dict[str, Any], parent: ModelPackage) -> ModelClass:
        """Create an enum class from enum schema.

        Args:
            name: Class name (must end with "Enum")
            schema: Enum schema
            parent: Parent package

        Returns:
            ModelClass with idlEnum stereotype
        """
        # Ensure name ends with "Enum"
        if not name.endswith("Enum"):
            name = name + "Enum"

        # Check if this enum already exists (circular reference detection)
        existing = next((cls for cls in parent.classes if cls.name == name and cls.is_enum), None)
        if existing:
            log.debug(f"Enum {name} already exists, reusing for circular reference")
            return existing

        # Add to created types immediately to prevent infinite recursion
        self.created_types.add(name)

        cls = ModelClass(
            name=name,
            object_id=self.next_object_id,
            namespace=parent.namespace,
            stereotypes=[self.config.stereotypes.main_class, self.config.stereotypes.idl_enum],
            is_enum=True,
            parent=parent,
            notes=schema.get("description"),
        )
        object_id = self.next_object_id
        self.next_object_id += 1

        # Register type for Classifier field lookups
        self.type_to_object_id[name] = object_id

        # Process enum values
        enum_values = schema.get("enum", [])
        enum_descriptions = schema.get("x-enum-descriptions", [])
        for i, enum_value in enumerate(enum_values):
            # Convert to valid enum member name
            member_name = self._to_enum_member_name(name, enum_value)
            member_notes = enum_descriptions[i] if i < len(enum_descriptions) else None
            attr = ModelAttribute(
                name=member_name,
                alias=member_name,
                type="long",
                attribute_id=self.next_attribute_id,
                guid=self._generate_guid(),
                parent=cls,
                notes=member_notes,
            )
            self.next_attribute_id += 1
            cls.attributes.append(attr)

        return cls

    def _create_union_class(self, name: str, schema: Dict[str, Any], parent: ModelPackage) -> ModelClass:
        """Create a union class from oneOf/anyOf schema.

        Args:
            name: Class name
            schema: Union schema
            parent: Parent package

        Returns:
            ModelClass with idlUnion stereotype
        """
        # Check if this union already exists (circular reference detection)
        existing = next((cls for cls in parent.classes if cls.name == name and cls.is_union), None)
        if existing:
            log.debug(f"Union {name} already exists, reusing for circular reference")
            return existing

        # Add to created types immediately to prevent infinite recursion
        self.created_types.add(name)

        cls = ModelClass(
            name=name,
            object_id=self.next_object_id,
            namespace=parent.namespace,
            stereotypes=[self.config.stereotypes.main_class, self.config.stereotypes.idl_union],
            is_union=True,
            parent=parent,
            notes=schema.get("description"),
        )
        object_id = self.next_object_id
        self.next_object_id += 1

        # Register type for Classifier field lookups
        self.type_to_object_id[name] = object_id

        # Create discriminator enum
        enum_name = name + "TypeEnum"

        # Check if enum already exists (in case of circular reference)
        existing_enum = next((c for c in parent.classes if c.name == enum_name and c.is_enum), None)
        if existing_enum:
            enum_cls = existing_enum
            enum_object_id = existing_enum.object_id
        else:
            enum_cls = ModelClass(
                name=enum_name,
                object_id=self.next_object_id,
                namespace=parent.namespace,
                stereotypes=[self.config.stereotypes.main_class, self.config.stereotypes.idl_enum],
                is_enum=True,
                parent=parent,
            )
            enum_object_id = self.next_object_id
            self.next_object_id += 1

            # Register enum type for Classifier field lookups
            self.type_to_object_id[enum_name] = enum_object_id
            self.created_types.add(enum_name)

            parent.classes.append(enum_cls)

        # Link union to enum
        cls.union_enum = "::".join(parent.namespace) + "::" + enum_name

        # Process union members
        variants = schema.get("oneOf", schema.get("anyOf", []))
        for i, variant in enumerate(variants):
            # Generate member name based on variant type
            member_name = self._generate_union_member_name(variant, i)
            union_key = f"{enum_name}_{member_name.upper()}"

            # Add enum member
            enum_attr = ModelAttribute(
                name=union_key,
                alias=union_key,
                type="long",
                attribute_id=self.next_attribute_id,
                guid=self._generate_guid(),
                parent=enum_cls,
            )
            self.next_attribute_id += 1
            enum_cls.attributes.append(enum_attr)

            # Add union member
            # Use resolve_type_with_intermediates for consistency and to handle nested arrays
            member_type_name_hint = self._to_pascal_case(name + "_" + member_name + "_Item")
            member_type = self._resolve_type_with_intermediates(variant, parent, member_type_name_hint)

            attr = ModelAttribute(
                name=member_name,
                alias=member_name,
                type=member_type,
                attribute_id=self.next_attribute_id,
                guid=self._generate_guid(),
                parent=cls,
                union_key=union_key,
                notes=variant.get("description"),
            )
            self.next_attribute_id += 1
            cls.attributes.append(attr)

        return cls

    def _create_typedef_class(self, name: str, schema: Dict[str, Any], parent: ModelPackage) -> ModelClass:
        """Create a typedef class from array or constrained primitive schema.

        Typedefs are simple type aliases. Array constraints (minItems, maxItems) should be
        placed as annotations on attributes that use the typedef, not on the typedef itself.

        Args:
            name: Class name
            schema: Typedef schema
            parent: Parent package

        Returns:
            ModelClass with idlTypedef stereotype
        """
        # Check if this typedef already exists (circular reference detection)
        existing = next((cls for cls in parent.classes if cls.name == name and cls.is_typedef), None)
        if existing:
            log.debug(f"Typedef {name} already exists, reusing for circular reference")
            return existing

        # Add to created types immediately to prevent infinite recursion
        self.created_types.add(name)

        cls = ModelClass(
            name=name,
            object_id=self.next_object_id,
            namespace=parent.namespace,
            stereotypes=[self.config.stereotypes.main_class, self.config.stereotypes.idl_typedef],
            is_typedef=True,
            parent=parent,
            notes=schema.get("description"),
        )
        object_id = self.next_object_id
        self.next_object_id += 1

        # Register type for Classifier field lookups
        self.type_to_object_id[name] = object_id

        # Determine parent type
        schema_type = schema.get("type")

        if schema_type == "array":
            # For arrays, resolve the items type
            items = schema.get("items", {})

            # If items is a oneOf/anyOf union, create an inline union type
            if "oneOf" in items or "anyOf" in items:
                # Create inline union for array items
                union_name = name + "Item"

                # Check if union already exists
                existing_union = next((c for c in parent.classes if c.name == union_name and c.is_union), None)
                if existing_union:
                    log.debug(f"Union {union_name} already exists, reusing")
                    item_type = union_name
                else:
                    union_cls = self._create_union_class(union_name, items, parent)
                    parent.classes.append(union_cls)
                    item_type = union_name
            else:
                # Use resolve_type_with_intermediates to handle nested arrays
                item_type = self._resolve_type_with_intermediates(items, parent, name + "Item")

            cls.parent_type = f"sequence<{item_type}>"
        else:
            # For primitives, use the mapped type
            cls.parent_type = self.type_mapping.get(schema_type, "string")

        return cls

    def _create_attribute(
        self, name: str, schema: Dict[str, Any], parent: ModelClass, is_optional: bool = False
    ) -> Optional[ModelAttribute]:
        """Create an attribute from property schema.

        Args:
            name: Property name
            schema: Property schema
            parent: Parent class
            is_optional: Whether property is optional

        Returns:
            ModelAttribute or None
        """
        # Handle inline enums (e.g., {"type": "string", "enum": ["a", "b"]})
        if "enum" in schema:
            # Create enum type for this property
            enum_name = self._to_pascal_case(parent.name + "_" + name + "_Enum")
            enum_schema = {"enum": schema["enum"], "description": schema.get("description")}
            enum_cls = self._create_enum_class(enum_name, enum_schema, parent.parent)
            parent.parent.classes.append(enum_cls)
            attr_type = enum_name
            is_collection = False
        else:
            # Resolve type normally
            attr_type = self._resolve_schema_type(schema)

            # Handle arrays
            is_collection = False
            if schema.get("type") == "array":
                is_collection = True
                items_schema = schema.get("items", {})
                # Check for inline enum in array items
                if "enum" in items_schema:
                    enum_name = self._to_pascal_case(parent.name + "_" + name + "_Item_Enum")
                    enum_schema = {"enum": items_schema["enum"], "description": items_schema.get("description")}
                    enum_cls = self._create_enum_class(enum_name, enum_schema, parent.parent)
                    parent.parent.classes.append(enum_cls)
                    attr_type = enum_name
                else:
                    # Use resolve_type_with_intermediates to handle nested arrays
                    attr_type = self._resolve_type_with_intermediates(
                        items_schema, parent.parent, self._to_pascal_case(parent.name + "_" + name + "_Item")
                    )

        # Create attribute
        attr = ModelAttribute(
            name=name,
            alias=name,
            type=attr_type,
            attribute_id=self.next_attribute_id,
            guid=self._generate_guid(),
            parent=parent,
            namespace=parent.namespace if not self._is_primitive_type(attr_type) else [],
            is_collection=is_collection,
            is_optional=is_optional,
            notes=schema.get("description"),
        )
        self.next_attribute_id += 1

        # Add stereotypes
        if is_optional:
            attr.stereotypes.append("optional")

        # Add constraints as annotations
        self._add_constraints(attr, schema)

        return attr

    def _resolve_type_with_intermediates(self, schema: Dict[str, Any], parent: ModelPackage, name_hint: str) -> str:
        """Resolve schema type, creating intermediate typedefs for nested arrays.

        Args:
            schema: Schema definition
            parent: Parent package (for creating new typedefs)
            name_hint: Name to use for generated typedefs

        Returns:
            Type name (existing or newly created)
        """
        # If it's an array, we need to create a typedef
        if schema.get("type") == "array":
            # Check if we've already processed this exact schema object
            schema_id = id(schema)
            if schema_id in self._schema_to_typedef:
                return self._schema_to_typedef[schema_id]

            # Generate a unique name for the typedef
            typedef_name = name_hint

            # Check if this typedef already exists in the package (by name)
            existing_cls = next((cls for cls in parent.classes if cls.name == typedef_name and cls.is_typedef), None)
            if existing_cls:
                # Cache it and return
                self._schema_to_typedef[schema_id] = typedef_name
                return typedef_name

            # Cache the intended name to break recursion
            self._schema_to_typedef[schema_id] = typedef_name

            # Create the typedef class
            cls = self._create_typedef_class(typedef_name, schema, parent)
            parent.classes.append(cls)
            return typedef_name

        # Otherwise resolve routinely
        return self._resolve_schema_type(schema)

    def _resolve_schema_type(self, schema: Dict[str, Any]) -> str:
        """Resolve JSON schema to IDL type name.

        Args:
            schema: Schema definition

        Returns:
            IDL type name
        """
        # Handle $ref
        if "$ref" in schema:
            return self._resolve_ref(schema["$ref"])

        # Handle $dynamicRef (JSON Schema 2020-12 feature)
        if "$dynamicRef" in schema:
            return self._resolve_dynamic_ref(schema["$dynamicRef"])

        # Handle type
        schema_type = schema.get("type")
        if schema_type in self.type_mapping:
            return self.type_mapping[schema_type]

        # Handle array - Note: this is fallback for cases where we don't have parent package context
        # Ideally _resolve_type_with_intermediates should be used instead
        if schema_type == "array":
            items = schema.get("items", {})
            return self._resolve_schema_type(items)

        # Default to string
        return "string"

    def _resolve_ref(self, ref: str) -> str:
        """Resolve $ref to type name with proper casing.

        Args:
            ref: Reference string (e.g., "#/$defs/point")

        Returns:
            Resolved type name in PascalCase
        """
        parts = ref.split("/")
        if len(parts) >= 3 and parts[1] == "$defs":
            name = parts[2]
            return self._to_pascal_case(name)
        return ref

    def _resolve_dynamic_ref(self, ref: str) -> str:
        """Resolve $dynamicRef to type name with proper casing.

        Args:
            ref: Dynamic reference string (e.g., "#cql2expression")

        Returns:
            Resolved type name in PascalCase
        """
        # $dynamicRef format: "#anchorname"
        if ref.startswith("#"):
            anchor_name = ref[1:]  # Remove leading #
            return self._to_pascal_case(anchor_name)
        return ref

    def _to_pascal_case(self, name: str) -> str:
        """Convert name to PascalCase.

        Args:
            name: Input name (snake_case, camelCase, etc.)

        Returns:
            PascalCase name
        """
        # Handle already PascalCase (starts with capital)
        if name and name[0].isupper() and "_" not in name:
            return name

        # First split on underscores
        if "_" in name:
            words = name.split("_")
            return "".join(word.capitalize() for word in words if word)

        # Handle camelCase by inserting spaces before capitals
        # Then capitalize each word
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
        words = spaced.split()
        return "".join(word.capitalize() for word in words if word)

    def _to_enum_member_name(self, enum_name: str, value: Any) -> str:
        """Convert enum value to valid enum member name.

        Args:
            enum_name: Name of the enum class
            value: Enum value

        Returns:
            Valid enum member name with prefix
        """
        # Convert value to string
        str_value = str(value).upper()

        # Sanitize (remove invalid characters)
        str_value = re.sub(r"[^A-Z0-9_]", "_", str_value)

        # Add enum name prefix
        return f"{enum_name}_{str_value}"

    def _generate_union_member_name(self, schema: Dict[str, Any], index: int) -> str:
        """Generate union member name from variant schema.

        Args:
            schema: Variant schema
            index: Variant index

        Returns:
            Member name
        """
        # Try to use type
        schema_type = schema.get("type")
        if schema_type:
            return f"{schema_type}_value"

        # Try to use $ref
        if "$ref" in schema:
            ref_name = self._resolve_ref(schema["$ref"])
            return f"{ref_name.lower()}_value"

        # Fallback to index
        return f"variant_{index}"

    def _is_primitive_type(self, type_name: str) -> bool:
        """Check if type is a primitive.

        Args:
            type_name: Type name

        Returns:
            True if primitive
        """
        primitives = {"string", "double", "long", "boolean", "float", "short", "octet", "char"}
        return type_name in primitives

    def _add_constraints(self, attr: ModelAttribute, schema: Dict[str, Any]) -> None:
        """Add JSON schema constraints as IDL annotations.

        Args:
            attr: Attribute to add constraints to
            schema: Property schema
        """
        # Min/max for numbers
        if "minimum" in schema:
            attr.properties["min"] = ModelAnnotation(value=schema["minimum"], value_type="int")
        if "maximum" in schema:
            attr.properties["max"] = ModelAnnotation(value=schema["maximum"], value_type="int")

        # Min/max items for arrays
        if "minItems" in schema:
            attr.properties[self.config.min_items] = ModelAnnotation(value=schema["minItems"], value_type="int")
        if "maxItems" in schema:
            attr.properties[self.config.max_items] = ModelAnnotation(value=schema["maxItems"], value_type="int")

        # Pattern for strings
        if "pattern" in schema:
            attr.properties["pattern"] = ModelAnnotation(value=schema["pattern"], value_type="str")

        # Default value
        if "default" in schema:
            default_val = schema["default"]
            val_type = type(default_val).__name__
            attr.properties["default"] = ModelAnnotation(value=default_val, value_type=val_type)

    def _generate_guid(self) -> str:
        """Generate EA-format GUID.

        Returns:
            GUID string in EA format: {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
        """
        return "{" + str(uuid.uuid4()).upper() + "}"

    def import_to_database(self, package: ModelPackage) -> None:
        """Write package tree to EA database.

        Args:
            package: Package to import
        """
        print(f"DEBUG: Importing package '{package.name}' to database")
        log.info(f"Importing package '{package.name}' to database")

        # Create database connection
        engine = sqlalchemy.create_engine(self.config.database_url, echo=False, future=True)
        session = Session(engine)

        # Prepare automap (use global base)
        base.prepare(autoload_with=engine)

        # Get table references
        TPackage = base.classes.t_package
        TObject = base.classes.t_object
        TAttribute = base.classes.t_attribute
        TXref = base.classes.t_xref
        TConnector = base.classes.t_connector
        TObjectProperties = base.classes.t_objectproperties

        try:
            # Get next available IDs
            print("DEBUG: Initializing IDs")
            self._initialize_ids(session, TPackage, TObject, TAttribute, TConnector)

            # Reassign IDs to package and classes
            print("DEBUG: Reassigning IDs")
            self._reassign_ids(package)

            # Insert packages recursively (root + children)
            print("DEBUG: Inserting package tree")
            self._insert_package_tree(
                session, package, TPackage, TObject, TXref, TAttribute, TObjectProperties, TConnector
            )

            # Commit changes
            print("DEBUG: Committing transaction...")
            session.commit()
            print("DEBUG: Transaction committed")

            # Count total classes across all packages
            print("DEBUG: Counting classes...")

            def count_classes(pkg):
                # print(f"DEBUG: Counting classes in {pkg.name}")
                count = len(pkg.classes)
                for child in pkg.packages:
                    count += count_classes(child)
                return count

            total_classes = count_classes(package)
            log.info(f"Successfully imported {total_classes} classes")

        except Exception as e:
            session.rollback()
            log.error(f"Failed to import schema: {e}")
            raise
        finally:
            session.close()

    def _initialize_ids(self, session: Session, TPackage: Any, TObject: Any, TAttribute: Any, TConnector: Any) -> None:
        """Initialize ID counters from database.

        Args:
            session: Database session
            TPackage: Package table
            TObject: Object table
            TAttribute: Attribute table
            TConnector: Connector table
        """
        # Get max package ID
        max_pkg = session.query(sqlalchemy.func.max(TPackage.attr_package_id)).scalar()
        self.next_package_id = (max_pkg or 0) + 1

        # Get max object ID
        max_obj = session.query(sqlalchemy.func.max(TObject.attr_object_id)).scalar()
        self.next_object_id = (max_obj or 0) + 1

        # Get max attribute ID
        max_attr = session.query(sqlalchemy.func.max(TAttribute.attr_id)).scalar()
        self.next_attribute_id = (max_attr or 0) + 1

        # Get max connector ID
        max_conn = session.query(sqlalchemy.func.max(TConnector.attr_connector_id)).scalar()
        self.next_connector_id = (max_conn or 0) + 1

        # Find Model package ID (parent for root packages)
        model_pkg = session.query(TPackage).filter(TPackage.attr_name == "Model").first()
        self.model_package_id = model_pkg.attr_package_id if model_pkg else 0
        if self.model_package_id == 0:
            log.warning("Model package not found in database, using Package_ID=0")

        log.debug(
            f"Next IDs - Package: {self.next_package_id}, Object: {self.next_object_id}, Attr: {self.next_attribute_id}, Connector: {self.next_connector_id}"
        )
        log.debug(f"Model package ID: {self.model_package_id}")

    def _reassign_ids(self, package: ModelPackage) -> None:
        """Recursively reassign IDs to package tree and all classes/attributes.

        Args:
            package: Package to reassign IDs for
        """
        # Reassign package IDs
        package.package_id = self.next_package_id
        self.next_package_id += 1

        package.object_id = self.next_object_id
        self.next_object_id += 1

        # Reassign class IDs and update type_to_object_id mapping
        for cls in package.classes:
            new_object_id = self.next_object_id
            self.next_object_id += 1

            # Update the type mapping with new Object_ID
            self.type_to_object_id[cls.name] = new_object_id
            cls.object_id = new_object_id

            # Reassign attribute IDs
            for attr in cls.attributes:
                attr.attribute_id = self.next_attribute_id
                self.next_attribute_id += 1

        # Recursively reassign IDs for child packages
        for child_package in package.packages:
            self._reassign_ids(child_package)

    def _insert_package_tree(
        self,
        session: Session,
        package: ModelPackage,
        TPackage: Any,
        TObject: Any,
        TXref: Any,
        TAttribute: Any,
        TObjectProperties: Any,
        TConnector: Any,
    ) -> None:
        """Recursively insert package tree (package + child packages + classes).

        Args:
            session: Database session
            package: Package to insert
            TPackage: Package table
            TObject: Object table
            TXref: Stereotype table
            TAttribute: Attribute table
            TObjectProperties: ObjectProperties table
            TConnector: Connector table
        """
        # Insert this package
        print(f"DEBUG: Inserting package {package.name}")
        self._insert_package(session, package, TPackage, TObject, TXref)

        # Insert classes in this package
        print(f"DEBUG: Inserting classes for {package.name} (count: {len(package.classes)})")
        self._insert_classes(session, package, TObject, TAttribute, TXref)

        # Insert object properties for classes in this package
        self._insert_object_properties(session, package, TObjectProperties)

        # Insert connectors for classes in this package
        self._insert_connectors(session, package, TConnector)

        # Recursively insert child packages
        for child_package in package.packages:
            self._insert_package_tree(
                session, child_package, TPackage, TObject, TXref, TAttribute, TObjectProperties, TConnector
            )

    def _insert_package(self, session: Session, package: ModelPackage, TPackage: Any, TObject: Any, TXref: Any) -> None:
        """Insert package into database.

        Args:
            session: Database session
            package: Package to insert
            TPackage: Package table
            TObject: Object table
            TXref: Stereotype table
        """
        # Determine parent ID
        if package.parent:
            parent_id = package.parent.package_id
            parent_package_id = package.parent.package_id
        else:
            # Root package - parent is Model
            parent_id = self.model_package_id
            parent_package_id = self.model_package_id

        # Create package entry in t_package
        pkg = TPackage()
        pkg.attr_package_id = package.package_id
        pkg.attr_name = package.name
        pkg.attr_ea_guid = package.guid
        pkg.attr_parent_id = parent_id
        pkg.attr_notes = package.notes or ""
        pkg.attr_version = "1.0"
        pkg.attr_packageflags = "isModel=1;VICON=3;"  # EA needs this to show package as model
        pkg.attr_batchsave = 0
        pkg.attr_batchload = 0
        session.add(pkg)

        # Create package object entry in t_object
        # This is required for the package to be loadable by ModelParser
        pkg_obj = TObject()
        pkg_obj.attr_object_id = package.object_id
        pkg_obj.attr_object_type = "Package"
        pkg_obj.attr_name = package.name
        pkg_obj.attr_ea_guid = package.guid
        pkg_obj.attr_package_id = parent_package_id
        pkg_obj.attr_note = package.notes or ""
        pkg_obj.attr_version = "1.0"
        pkg_obj.attr_complexity = "1"
        pkg_obj.attr_ntype = 0
        # CRITICAL: Link to t_package entry via PDATA1
        pkg_obj.attr_pdata1 = str(package.package_id)
        # Package stereotype in t_object
        pkg_obj.attr_stereotype = self.config.stereotypes.package  # "DataModel"
        pkg_obj.attr_status = "Proposed"
        pkg_obj.attr_classifier = 0
        pkg_obj.attr_parentid = 0
        pkg_obj.attr_phase = "1.0"
        pkg_obj.attr_scope = "Public"
        pkg_obj.attr_backcolor = -1
        pkg_obj.attr_borderwidth = -1
        session.add(pkg_obj)

        # Add stereotypes
        self._insert_stereotypes(session, package.guid, package.stereotypes, TXref)

    def _insert_classes(
        self, session: Session, package: ModelPackage, TObject: Any, TAttribute: Any, TXref: Any
    ) -> None:
        """Insert all classes in package.

        Args:
            session: Database session
            package: Package containing classes
            TObject: Object table
            TAttribute: Attribute table
            TXref: Stereotype table
        """
        for cls in package.classes:
            self._insert_class(session, cls, package, TObject, TAttribute, TXref)

    def _insert_class(
        self,
        session: Session,
        cls: ModelClass,
        package: ModelPackage,
        TObject: Any,
        TAttribute: Any,
        TXref: Any,
    ) -> None:
        """Insert a single class.

        Args:
            session: Database session
            cls: Class to insert
            package: Parent package
            TObject: Object table
            TAttribute: Attribute table
            TXref: Stereotype table
        """
        # Create object entry
        obj = TObject()
        obj.attr_object_id = cls.object_id
        obj.attr_object_type = "Class"
        obj.attr_name = cls.name
        obj.attr_ea_guid = self._generate_guid()
        obj.attr_package_id = package.package_id
        obj.attr_note = cls.notes or ""
        obj.attr_abstract = "1" if cls.is_abstract else "0"
        obj.attr_version = "1.0"
        obj.attr_complexity = "1"  # EA default for classes
        obj.attr_ntype = 0
        # Add stereotype in t_object.Stereotype field
        obj.attr_stereotype = self.config.stereotypes.main_class  # "DataElement"
        obj.attr_status = "Proposed"
        obj.attr_classifier = 0
        obj.attr_parentid = 0
        obj.attr_phase = "1.0"
        obj.attr_scope = "Public"
        obj.attr_gentype = "Java"  # Set code generation type for proper visual appearance
        obj.attr_pdata4 = "0"  # EA default for classes
        obj.attr_backcolor = -1  # Use MDG default color
        obj.attr_borderwidth = -1  # Use MDG default border
        obj.attr_fontcolor = -1  # Use MDG default font color
        obj.attr_bordercolor = -1  # Use MDG default border color

        # For typedefs, set parent type in Genlinks field
        if cls.is_typedef and cls.parent_type:
            obj.attr_genlinks = f"Parent={cls.parent_type};"

        session.add(obj)

        # Add stereotypes
        self._insert_stereotypes(session, obj.attr_ea_guid, cls.stereotypes, TXref)

        # Add attributes
        for attr in cls.attributes:
            self._insert_attribute(session, attr, cls, TAttribute)

    def _insert_attribute(self, session: Session, attr: ModelAttribute, parent: ModelClass, TAttribute: Any) -> None:
        """Insert an attribute.

        Args:
            session: Database session
            attr: Attribute to insert
            parent: Parent class
            TAttribute: Attribute table
        """
        db_attr = TAttribute()
        db_attr.attr_id = attr.attribute_id
        db_attr.attr_object_id = parent.object_id
        db_attr.attr_name = attr.name
        db_attr.attr_type = attr.type or ""
        db_attr.attr_ea_guid = attr.guid
        db_attr.attr_notes = attr.notes or ""
        db_attr.attr_scope = "Public"  # EA default
        db_attr.attr_iscollection = "1" if attr.is_collection else "0"
        db_attr.attr_isordered = "1" if attr.is_ordered else "0"
        db_attr.attr_lowerbound = attr.lower_bound or "1"
        db_attr.attr_upperbound = attr.upper_bound or "1"

        # Set Classifier for complex types
        if attr.type and attr.type in self.type_to_object_id:
            db_attr.attr_classifier = str(self.type_to_object_id[attr.type])
        else:
            db_attr.attr_classifier = "0"

        # Set collection bounds
        if attr.is_collection:
            db_attr.attr_lowerbound = "0"
            db_attr.attr_upperbound = "*"
            db_attr.attr_isordered = "1"  # Collections are typically ordered

        session.add(db_attr)

    def _insert_stereotypes(self, session: Session, guid: str, stereotypes: List[str], TXref: Any) -> None:
        """Insert stereotypes for an object.

        Args:
            session: Database session
            guid: Object GUID
            stereotypes: List of stereotype names
            TXref: Stereotype table
        """
        if not stereotypes:
            return

        # Mapping of stereotype names to FQNames (for MDG Technology linking)
        stereotype_fqnames = {
            "DataElement": "NAFv4-Core::DataElement",
            "DataModel": "NAFv4-Core::DataModel",
            "idlStruct": "IDL::idlStruct",
            "idlEnum": "IDL::idlEnum",
            "idlUnion": "IDL::idlUnion",
            "idlTypedef": "IDL::idlTypedef",
        }

        # Create stereotype string - each stereotype needs its own @STEREO block
        stereo_blocks = []
        for stereo in stereotypes:
            # Add FQName if known (links to MDG Technology for appearance)
            if stereo in stereotype_fqnames:
                stereo_blocks.append(f"@STEREO;Name={stereo};FQName={stereotype_fqnames[stereo]};@ENDSTEREO;")
            else:
                stereo_blocks.append(f"@STEREO;Name={stereo};@ENDSTEREO;")
        stereo_str = "".join(stereo_blocks)

        # Create xref entry
        xref = TXref()
        xref.attr_xrefid = self._generate_guid()  # XrefID is required
        xref.attr_client = guid
        xref.attr_name = "Stereotypes"
        xref.attr_type = "element property"
        xref.attr_description = stereo_str
        session.add(xref)

    def _insert_connectors(self, session: Session, package: ModelPackage, TConnector: Any) -> None:
        """Insert connectors for attribute associations, union-discriminator links, and typedef dependencies.

        Args:
            session: Database session
            package: Package containing classes
            TConnector: Connector table
        """
        for cls in package.classes:
            # Create typedef association connector if this is a typedef
            if cls.is_typedef and cls.parent_type:
                # Extract the referenced type from parent_type (e.g., "sequence<ArrayExpressionItem>" -> "ArrayExpressionItem")
                import re

                match = re.search(r"sequence<(.+?)>", cls.parent_type)
                if match:
                    ref_type = match.group(1)
                    # Check if this is a known type (not a primitive)
                    if ref_type in self.type_to_object_id:
                        connector = TConnector()
                        connector.attr_connector_id = self.next_connector_id
                        self.next_connector_id += 1

                        connector.attr_name = ""
                        connector.attr_connector_type = "Association"
                        connector.attr_direction = "Source -> Destination"
                        connector.attr_start_object_id = cls.object_id
                        connector.attr_end_object_id = self.type_to_object_id[ref_type]
                        connector.attr_linecolor = -1  # Use MDG default line color
                        connector.attr_ea_guid = self._generate_guid()

                        session.add(connector)
                        log.debug(f"Created typedef association: {cls.name} -> {ref_type}")
                elif cls.parent_type in self.type_to_object_id:
                    # Direct type reference (not a sequence)
                    connector = TConnector()
                    connector.attr_connector_id = self.next_connector_id
                    self.next_connector_id += 1

                    connector.attr_name = ""
                    connector.attr_connector_type = "Association"
                    connector.attr_direction = "Source -> Destination"
                    connector.attr_start_object_id = cls.object_id
                    connector.attr_end_object_id = self.type_to_object_id[cls.parent_type]
                    connector.attr_linecolor = -1  # Use MDG default line color
                    connector.attr_ea_guid = self._generate_guid()

                    session.add(connector)
                    log.debug(f"Created typedef association: {cls.name} -> {cls.parent_type}")

            # Create union-to-discriminator connector if this is a union class
            if cls.is_union and cls.union_enum:
                # Extract enum name from full path (e.g., "cql2::Cql2expressionTypeEnum" -> "Cql2expressionTypeEnum")
                enum_name = cls.union_enum.split("::")[-1]
                if enum_name in self.type_to_object_id:
                    connector = TConnector()
                    connector.attr_connector_id = self.next_connector_id
                    self.next_connector_id += 1

                    connector.attr_name = ""
                    connector.attr_connector_type = "Association"
                    connector.attr_direction = "Unspecified"
                    connector.attr_stereotype = "union"
                    connector.attr_start_object_id = cls.object_id
                    connector.attr_end_object_id = self.type_to_object_id[enum_name]
                    connector.attr_linecolor = -1  # Use MDG default line color
                    connector.attr_ea_guid = self._generate_guid()

                    session.add(connector)
                    log.debug(f"Created union connector: {cls.name} -> {enum_name}")

            # Create attribute association connectors
            for attr in cls.attributes:
                # Only create connectors for complex types (not primitives)
                if attr.type and attr.type in self.type_to_object_id:
                    connector = TConnector()
                    connector.attr_connector_id = self.next_connector_id
                    self.next_connector_id += 1

                    connector.attr_name = ""  # Empty for attribute associations
                    connector.attr_connector_type = "Association"
                    connector.attr_direction = "Source -> Destination"
                    connector.attr_start_object_id = cls.object_id
                    connector.attr_end_object_id = self.type_to_object_id[attr.type]
                    connector.attr_destrole = attr.name  # Attribute name as destination role
                    connector.attr_linecolor = -1  # Use MDG default line color
                    connector.attr_ea_guid = self._generate_guid()

                    # Don't set cardinality on connector (attribute already has it)

                    session.add(connector)
                    log.debug(f"Created connector: {cls.name}.{attr.name} -> {attr.type}")

    def _insert_object_properties(self, session: Session, package: ModelPackage, TObjectProperties: Any) -> None:
        """Insert object properties for NAFv4 MDG compatibility.

        Args:
            session: Database session
            package: Package containing classes
            TObjectProperties: ObjectProperties table
        """
        for cls in package.classes:
            # Add URI property (required by NAFv4)
            uri_prop = TObjectProperties()
            uri_prop.attr_object_id = cls.object_id
            uri_prop.attr_property = "URI"
            uri_prop.attr_value = ""
            uri_prop.attr_notes = ""
            uri_prop.attr_ea_guid = self._generate_guid()
            session.add(uri_prop)

            # Add isEncapsulated property (required by NAFv4)
            encap_prop = TObjectProperties()
            encap_prop.attr_object_id = cls.object_id
            encap_prop.attr_property = "isEncapsulated"
            encap_prop.attr_value = ""
            encap_prop.attr_notes = ""
            encap_prop.attr_ea_guid = self._generate_guid()
            session.add(encap_prop)

            log.debug(f"Added NAFv4 properties for: {cls.name}")
