from typing import Literal, Optional, List, Dict, TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from eaidl.config import Configuration

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


class ModelCustomProperty(BaseModel):
    name: str
    value: bool | int | float | str
    type: str


class ModelPropertyType(BaseModel):
    property: str
    notes: Optional[str] = None
    property_types: List[str] = []


class LinkedNote(BaseModel):
    """Represents a note linked via NoteLink connector.

    Used for notes that are separate Note objects in EA,
    linked to packages/classes/attributes via NoteLink connectors.
    """

    note_id: int  # Object_ID of Note object in t_object
    content: str  # Markdown content (for display)
    content_html: str  # Original HTML from EA (for checksum)
    checksum: str  # MD5 checksum of content_html


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
    stereotypes: List[str] = []
    source: ModelConnectionEnd = ModelConnectionEnd()
    destination: ModelConnectionEnd = ModelConnectionEnd()


ModelAnnotationTypeLiteral = Literal["none", "str", "int", "float", "bool", "object"]
ModelAnnotationType = int | float | str | bool | None


class ModelAnnotation(LocalBaseModel):
    value_type: ModelAnnotationTypeLiteral = "none"
    value: ModelAnnotationType = None


class ModelDiagramObject(LocalBaseModel):
    """Represents an object placement on an EA diagram."""

    object_id: int
    diagram_id: int
    rect_top: int
    rect_left: int
    rect_right: int
    rect_bottom: int
    sequence: int  # Z-order
    object_style: Optional[str] = None


class ModelDiagramLink(LocalBaseModel):
    """Represents a connector on an EA diagram."""

    connector_id: int
    diagram_id: int
    geometry: Optional[str] = None  # EA's encoded path data
    style: Optional[str] = None
    hidden: int = 0
    path: Optional[str] = None


class ModelDiagramNote(LocalBaseModel):
    """Represents a note on an EA diagram."""

    object_id: int
    diagram_id: int
    name: str  # Note content
    note_text: Optional[str] = None  # Additional note text
    rect_left: int = 0
    rect_top: int = 0
    rect_right: int = 0
    rect_bottom: int = 0


class ModelInteractionFragment(LocalBaseModel):
    """Represents an interaction fragment (alt, opt, loop, etc.) in a sequence diagram."""

    object_id: int
    name: str  # Fragment label
    stereotype: Optional[str] = None  # "alt", "opt", "loop", "par", etc.
    note: Optional[str] = None  # Condition text
    parent_id: Optional[int] = None
    messages: List[int] = []  # Connector IDs of messages in this fragment
    rect_top: int = 0  # Top Y-coordinate for spatial positioning
    rect_bottom: int = 0  # Bottom Y-coordinate for spatial positioning


class ModelDiagram(LocalBaseModel):
    """Represents an EA diagram."""

    diagram_id: int
    package_id: int
    name: str
    diagram_type: Optional[str] = None  # "Class", "Custom", "Sequence", etc.
    stereotype: Optional[str] = None
    author: Optional[str] = None
    created_date: Optional[str] = None
    modified_date: Optional[str] = None
    guid: Optional[str] = None
    cx: Optional[int] = None  # Canvas width
    cy: Optional[int] = None  # Canvas height
    scale: Optional[int] = None  # Scale percentage
    diagram_notes: Optional[str] = None  # Diagram metadata notes (from t_diagram.notes)
    objects: List[ModelDiagramObject] = []
    links: List[ModelDiagramLink] = []
    notes: List[ModelDiagramNote] = []  # Note objects on the diagram
    fragments: List[ModelInteractionFragment] = []


class ModelClass(LocalBaseModel):
    name: str
    parent: Optional["ModelPackage"] = None
    object_id: int
    guid: Optional[str] = None
    is_abstract: Optional[bool] = None
    alias: Optional[str] = None
    attributes: List["ModelAttribute"] = []
    stereotypes: List[str] = []
    generalization: Optional[List[str]] = None
    depends_on: List[int] = []
    parent_type: Optional[str] = None
    properties: Dict[str, ModelAnnotation] = {}
    #: It this is union, there can be a enumeration specified here
    union_enum: Optional[str] = None
    #: If this class has <<values>> relationships to enums, the enums are listed here
    values_enums: List[str] = []
    #: Additional notes linked to this class via NoteLink connectors
    linked_notes: List[LinkedNote] = []
    is_union: bool = False
    is_enum: bool = False
    is_typedef: bool = False
    is_struct: bool = False
    is_map: bool = False
    #: True if this struct needs a forward declaration (due to circular dependency)
    needs_forward_declaration: bool = False

    @property
    def full_name(self) -> str:
        """Get fully qualified name (e.g., 'root::MyClass')."""
        return "::".join(self.namespace + [self.name])

    def has_stereotype(self, stereotype: str) -> bool:
        """Check if class has a specific stereotype."""
        return stereotype in self.stereotypes

    def is_enum_type(self, config: "Configuration") -> bool:
        """Check if this is an enum class."""
        return config.stereotypes.idl_enum in self.stereotypes

    def is_struct_type(self, config: "Configuration") -> bool:
        """Check if this is a struct class."""
        return config.stereotypes.idl_struct in self.stereotypes

    def is_union_type(self, config: "Configuration") -> bool:
        """Check if this is a union class."""
        return config.stereotypes.idl_union in self.stereotypes


class ModelPackageInfo(LocalBaseModel):
    structs: int = 0
    typedefs: int = 0
    unions: int = 0
    maps: int = 0
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
    stereotypes: List[str] = []
    classes: List[ModelClass] = []
    depends_on: List[int] = []
    info: ModelPackageInfo = ModelPackageInfo()
    property_types: List[ModelPropertyType] = []
    #: Notes that are not linked to any object in this package
    unlinked_notes: List[LinkedNote] = []
    #: EA diagrams associated with this package
    diagrams: List[ModelDiagram] = []

    @property
    def full_namespace(self) -> str:
        """Get fully qualified namespace."""
        return "::".join(self.namespace)


class ModelAttribute(LocalBaseModel):
    #: Name of attribute, as it will be in output
    name: str
    #: Name of attribute, as it was in model
    alias: str
    type: Optional[str] = None
    attribute_id: int
    guid: str
    parent: Optional["ModelClass"] = None
    scope: Optional[ModelScope] = None
    position: Optional[int] = None
    stereotypes: List[str] = []
    is_optional: Optional[bool] = None
    is_collection: Optional[bool] = None
    is_ordered: Optional[bool] = None
    is_static: Optional[bool] = None
    #: Set to true if this attribute is a map
    is_map: Optional[bool] = None
    #: If this attribute is a map (is_map==True) this is kye type
    map_key_type: Optional[str] = None
    #: If this attribute is a map (is_map==True) this is value type
    map_value_type: Optional[str] = None
    lower_bound: Optional[str] = None
    #: Lower bound converted to integer if that is possible, false otherwise
    lower_bound_number: Optional[int] = None
    upper_bound: Optional[str] = None
    #: Upper bound converted to integer if that is possible, false otherwise
    upper_bound_number: Optional[int] = None
    connector: Optional[ModelConnection] = None
    properties: Dict[str, ModelAnnotation] = {}
    union_key: Optional[str] = None
    union_namespace: Optional[List[str]] = []
    #: If this attribute has a <<values>> relationship to an enum, the enum is specified here
    values_enum: Optional[str] = None
    #: Additional notes linked to this attribute via NoteLink connectors
    linked_notes: List[LinkedNote] = []
