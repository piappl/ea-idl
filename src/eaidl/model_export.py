"""Export full EA model structure to YAML for documentation generation."""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import pydantic
import yaml

from eaidl.config import Configuration
from eaidl.load import ModelParser
from eaidl.model import (
    ModelAttribute,
    ModelClass,
    ModelDiagram,
    ModelPackage,
)

log = logging.getLogger(__name__)


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Convert a name to a safe cross-platform filename component."""
    if not name:
        return "unnamed"

    safe_name = name
    replacements = {
        "<": "",
        ">": "",
        ":": "_",
        '"': "",
        "/": "_",
        "\\": "_",
        "|": "_",
        "?": "",
        "*": "",
        "\0": "",
        "\r": "",
        "\n": "_",
        "\t": "_",
    }
    for old_char, new_char in replacements.items():
        safe_name = safe_name.replace(old_char, new_char)

    safe_name = "".join(char if 32 <= ord(char) < 127 or ord(char) > 127 else "_" for char in safe_name)
    safe_name = re.sub(r"_+", "_", safe_name).strip(" ._")
    return safe_name[:max_length] if safe_name else "unnamed"


def _class_kind(cls: ModelClass) -> str:
    """Determine the kind string for a class."""
    if cls.is_enum:
        return "enum"
    if cls.is_union:
        return "union"
    if cls.is_typedef:
        return "typedef"
    if cls.is_map:
        return "map"
    return "struct"


class ModelExporter:
    """Exports model tree to a nested dict structure suitable for YAML serialization."""

    def __init__(self, config: Configuration, parser: ModelParser):
        self.config = config
        self.parser = parser

    def export(self, packages: List[ModelPackage]) -> Dict[str, Any]:
        """Export full model to a dict."""
        return {
            "metadata": {
                "database_url": self.config.database_url,
                "root_packages": self.config.root_packages,
                "export_date": datetime.now(timezone.utc).isoformat(),
            },
            "packages": [self._export_package(pkg) for pkg in packages],
        }

    def _export_package(self, package: ModelPackage) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": package.name,
            "guid": package.guid,
            "namespace": package.namespace,
            "notes": package.notes,
            "stereotypes": package.stereotypes or None,
        }

        if package.diagrams:
            result["diagrams"] = [self._export_diagram(d, package) for d in package.diagrams]

        if package.classes:
            result["classes"] = [self._export_class(cls) for cls in package.classes]

        if package.packages:
            result["packages"] = [self._export_package(child) for child in package.packages]

        return result

    def _export_diagram(self, diagram: ModelDiagram, package: ModelPackage) -> Dict[str, Any]:
        path_components = [sanitize_filename(ns) for ns in package.namespace]
        path_components.append(sanitize_filename(package.name))
        path_components.append(sanitize_filename(diagram.name))
        file_path = "/".join(path_components)

        return {
            "name": diagram.name,
            "guid": diagram.guid,
            "diagram_type": diagram.diagram_type,
            "file_path": file_path,
            "notes": diagram.diagram_notes,
        }

    def _export_class(self, cls: ModelClass) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": cls.name,
            "guid": cls.guid,
            "kind": _class_kind(cls),
            "notes": cls.notes,
            "stereotypes": cls.stereotypes or None,
        }

        relations = self._export_relations(cls)
        if relations:
            result["relations"] = relations

        if cls.attributes:
            result["attributes"] = [self._export_attribute(attr) for attr in cls.attributes]

        return result

    def _export_attribute(self, attr: ModelAttribute) -> Dict[str, Any]:
        return {
            "name": attr.name,
            "guid": attr.guid,
            "type": attr.type,
            "notes": attr.notes,
            "stereotypes": attr.stereotypes or None,
            "is_collection": attr.is_collection,
            "is_optional": attr.is_optional,
            "is_map": attr.is_map,
            "lower_bound": attr.lower_bound,
            "upper_bound": attr.upper_bound,
        }

    def _export_relations(self, cls: ModelClass) -> List[Dict[str, Any]]:
        """Load and export all non-NoteLink connectors for a class."""
        try:
            connections = self.parser.get_object_connections(cls.object_id, mode="source")
        except pydantic.ValidationError:
            log.warning("Could not load connections for %s", cls.name)
            return []

        relations = []
        for conn in connections:
            target_obj = self.parser.get_object(conn.end_object_id)
            if target_obj is None:
                continue

            try:
                target_namespace = self.parser.get_namespace(target_obj.attr_package_id)
            except Exception:
                target_namespace = []

            relations.append(
                {
                    "type": conn.connector_type,
                    "stereotype": conn.stereotypes[0] if conn.stereotypes else None,
                    "target": target_obj.attr_name,
                    "target_guid": target_obj.attr_ea_guid,
                    "target_namespace": target_namespace,
                    "direction": conn.direction,
                    "source_cardinality": conn.source.cardinality,
                    "target_cardinality": conn.destination.cardinality,
                }
            )
        return relations


def export_model_yaml(
    config: Configuration, parser: ModelParser, packages: List[ModelPackage], output_path: str
) -> None:
    """Entry point: export model to YAML file."""
    exporter = ModelExporter(config, parser)
    data = exporter.export(packages)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120)

    log.info("Model exported to %s", output_path)


def export_model_markdown(
    config: Configuration, parser: ModelParser, packages: List[ModelPackage], output_path: str
) -> None:
    """Entry point: export model to Markdown file."""
    from eaidl.model_markdown import render_markdown

    exporter = ModelExporter(config, parser)
    data = exporter.export(packages)
    md = render_markdown(data)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    log.info("Model exported to %s", output_path)
