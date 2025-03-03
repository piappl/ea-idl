from typing import Literal, Optional, List, Dict
from pydantic import BaseModel

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
    stereotype: Optional[str] = None
    source: ModelConnectionEnd = ModelConnectionEnd()
    destination: ModelConnectionEnd = ModelConnectionEnd()


ModelAnnotationTypeLiteral = Literal["none", "str", "int", "float", "bool", "object"]
ModelAnnotationType = int | float | str | bool | None


class ModelAnnotation(LocalBaseModel):
    value_type: ModelAnnotationTypeLiteral = "none"
    value: ModelAnnotationType = None


class ModelClass(LocalBaseModel):
    name: str
    parent: Optional["ModelPackage"] = None
    object_id: int
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
    is_union: bool = False
    is_enum: bool = False
    is_typedef: bool = False
    is_struct: bool = False
    is_map: bool = False


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


class ModelAttribute(LocalBaseModel):
    name: str
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
    union_namespace: Optional[str] = None
