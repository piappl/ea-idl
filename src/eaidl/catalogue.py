"""The IDL stereotype catalogue: stereotypes eaidl itself defines and reads, in the shared eacore format."""

from importlib.metadata import PackageNotFoundError, version

from eacore.catalogue import Catalogue, Source, StereotypeDef
from eaidl.config import Configuration


def _version() -> str:
    try:
        return version("eaidl")
    except PackageNotFoundError:
        return ""


def idl_catalogue(config: Configuration) -> Catalogue:
    """Build the catalogue from the stereotype names in ``config``.

    ``main_class`` and ``package`` are deliberately absent: they are stereotypes eaidl requires
    from the modelling profile, not ones it defines.
    """
    # name -> metaclasses, insertion ordered; the same name from two sources merges its metaclasses
    found: dict[str, list[str]] = {}

    def add(name: str | None, *applies_to: str) -> None:
        if not name:
            return
        known = found.setdefault(name, [])
        known.extend(a for a in applies_to if a not in known)

    st = config.stereotypes
    for name in (st.idl_struct, st.idl_union, st.idl_enum, st.idl_map, st.idl_typedef):
        add(name, "Class")
    add(st.idl_map_key, "Attribute")
    add(st.idl_map_value, "Attribute")
    # load.py (parse_attribute): is_optional = "optional" in attribute.stereotypes
    add("optional", "Attribute")
    # load.py (get_union_connections / get_values_connections): connectors selected by these stereotypes
    add("union", "Association")
    add("values", "Association")
    add(config.keep_union_stereotype, "Class")
    add(config.collapse_union_stereotype, "Class")
    # Plain name lists have no known base metaclass
    for names in (
        config.filter_stereotypes,
        config.keep_stereotypes,
        config.private_stereotypes,
        config.annotations_from_stereotypes,
    ):
        for name in names or []:
            add(name)

    return Catalogue(
        profile="IDL",
        source=Source(kind="eaidl", file="", version=_version()),
        stereotypes=[StereotypeDef(name=n, applies_to=a) for n, a in found.items()],
    )
