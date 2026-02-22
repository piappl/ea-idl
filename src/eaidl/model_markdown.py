"""Render a model export dict (from ModelExporter.export()) as Markdown."""

from typing import Any, Dict, List, Optional


def render_markdown(
    data: Dict[str, Any],
    diagrams_dir: Optional[str] = None,
    diagram_paths: Optional[Dict[str, str]] = None,
) -> str:
    """Render full model export dict to a markdown string.

    :param data: Model export dict from ModelExporter.export()
    :param diagrams_dir: Directory containing exported diagram images (relative to output)
    :param diagram_paths: GUID → relative image path mapping (from diagrams.yaml)
    """
    lines: List[str] = []
    meta = data.get("metadata", {})

    lines.append("# Model Documentation")
    lines.append("")
    lines.append(f"> Exported from `{meta.get('database_url', '')}` on {meta.get('export_date', '')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for pkg in data.get("packages", []):
        _render_package(pkg, depth=2, lines=lines, diagrams_dir=diagrams_dir, diagram_paths=diagram_paths)

    return "\n".join(lines)


def _render_package(
    pkg: Dict[str, Any],
    depth: int,
    lines: List[str],
    diagrams_dir: Optional[str] = None,
    diagram_paths: Optional[Dict[str, str]] = None,
) -> None:
    heading = "#" * depth
    lines.append(f"{heading} {pkg['name']}")
    lines.append("")

    stereotypes = pkg.get("stereotypes")
    if stereotypes:
        lines.append(f"*Stereotypes: {', '.join(stereotypes)}*")
        lines.append("")

    notes = pkg.get("notes")
    if notes:
        lines.append(notes.strip())
        lines.append("")

    diagrams = pkg.get("diagrams")
    if diagrams:
        _render_diagrams(diagrams, depth + 1, lines, diagrams_dir, diagram_paths)

    for cls in pkg.get("classes", []):
        _render_class(cls, depth + 1, lines)

    for child in pkg.get("packages", []):
        _render_package(child, depth + 1, lines, diagrams_dir=diagrams_dir, diagram_paths=diagram_paths)

    lines.append("---")
    lines.append("")


def _resolve_diagram_path(
    d: Dict[str, Any], diagrams_dir: str, diagram_paths: Optional[Dict[str, str]]
) -> Optional[str]:
    """Resolve image path for a diagram, using GUID mapping if available."""
    guid = d.get("guid")
    if diagram_paths and guid and guid in diagram_paths:
        return f"{diagrams_dir}/{diagram_paths[guid]}.png"
    # Fallback to file_path from model export
    path = d.get("file_path")
    if path:
        return f"{diagrams_dir}/{path}.png"
    return None


def _render_diagrams(
    diagrams: List[Dict[str, Any]],
    depth: int,
    lines: List[str],
    diagrams_dir: Optional[str] = None,
    diagram_paths: Optional[Dict[str, str]] = None,
) -> None:
    heading = "#" * depth
    lines.append(f"{heading} Diagrams")
    lines.append("")
    if diagrams_dir:
        for d in diagrams:
            name = d.get("name", "")
            notes = d.get("notes")
            img_path = _resolve_diagram_path(d, diagrams_dir, diagram_paths)
            lines.append(f"#### {name}")
            lines.append("")
            if notes:
                lines.append(notes.strip())
                lines.append("")
            if img_path:
                lines.append(f"![{name}]({img_path})")
            else:
                lines.append(f"*Image not found for diagram: {name}*")
            lines.append("")
    else:
        lines.append("| Name | Type | Path | Notes |")
        lines.append("|------|------|------|-------|")
        for d in diagrams:
            name = d.get("name", "")
            dtype = d.get("diagram_type", "")
            path = d.get("file_path", "")
            notes = (d.get("notes") or "").strip().replace("\n", " ")
            lines.append(f"| {name} | {dtype} | {path} | {notes} |")
        lines.append("")


def _render_class(cls: Dict[str, Any], depth: int, lines: List[str]) -> None:
    heading = "#" * depth
    kind = cls.get("kind", "struct")
    lines.append(f"{heading} {cls['name']} ({kind})")
    lines.append("")

    stereotypes = cls.get("stereotypes")
    if stereotypes:
        lines.append(f"*Stereotypes: {', '.join(stereotypes)}*")
        lines.append("")

    notes = cls.get("notes")
    if notes:
        lines.append(notes.strip())
        lines.append("")

    relations = cls.get("relations")
    if relations:
        _render_relations_table(relations, depth + 1, lines)

    attributes = cls.get("attributes")
    if attributes:
        _render_attributes_table(attributes, depth + 1, lines)


def _render_relations_table(relations: List[Dict[str, Any]], depth: int, lines: List[str]) -> None:
    heading = "#" * depth
    lines.append(f"{heading} Relations")
    lines.append("")
    lines.append("| Type | Target | Stereotype | Direction | Cardinality |")
    lines.append("|------|--------|------------|-----------|-------------|")
    for r in relations:
        rtype = r.get("type", "")
        target = r.get("target", "")
        stereotype = r.get("stereotype") or "\u2014"
        direction = r.get("direction") or "\u2014"
        src_card = r.get("source_cardinality") or ""
        tgt_card = r.get("target_cardinality") or ""
        cardinality = f"{src_card}..{tgt_card}" if src_card or tgt_card else "\u2014"
        lines.append(f"| {rtype} | {target} | {stereotype} | {direction} | {cardinality} |")
    lines.append("")


def _render_attributes_table(attributes: List[Dict[str, Any]], depth: int, lines: List[str]) -> None:
    heading = "#" * depth
    lines.append(f"{heading} Attributes")
    lines.append("")
    lines.append("| Name | Type | Collection | Optional | Map | Bounds | Stereotypes |")
    lines.append("|------|------|------------|----------|-----|--------|-------------|")
    for attr in attributes:
        name = attr.get("name", "")
        atype = attr.get("type", "")
        collection = "yes" if attr.get("is_collection") else "no"
        optional = "yes" if attr.get("is_optional") else "no"
        is_map = "yes" if attr.get("is_map") else "no"
        lower = attr.get("lower_bound") or ""
        upper = attr.get("upper_bound") or ""
        bounds = f"{lower}..{upper}" if lower or upper else "\u2014"
        stereos = ", ".join(attr["stereotypes"]) if attr.get("stereotypes") else "\u2014"
        lines.append(f"| {name} | {atype} | {collection} | {optional} | {is_map} | {bounds} | {stereos} |")

        notes = attr.get("notes")
        if notes:
            lines.append(f"| | > {notes.strip()} | | | | | |")

    lines.append("")
