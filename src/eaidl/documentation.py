"""Publish a complete diagram catalogue independently of IDL transforms."""

from collections import Counter
from pathlib import Path
import json
import re
from xml.etree import ElementTree as ET

from sqlalchemy import text

from eaidl.html_utils import strip_html
from eaidl.native_diagram_extractor import NativeDiagramExtractor
from eaidl.native_diagram_svg import render_svg, rewrite_svg_links
from eaidl.tree_utils import traverse_packages


def normalize_guid(value):
    return value.strip("{}").lower()


def select_diagrams(package_rows, diagram_rows, settings):
    """Resolve roots exactly, map viewpoints, and account for every scoped diagram."""
    packages = {row["Package_ID"]: row for row in package_rows}

    def resolve_roots(selectors):
        resolved = set()
        for selector in selectors:
            matches = [
                row["Package_ID"]
                for row in package_rows
                if (
                    normalize_guid(row["ea_guid"] or "") == normalize_guid(selector)
                    if selector.startswith("{")
                    else row["Name"] == selector
                )
            ]
            if len(matches) != 1:
                raise ValueError(f"Documentation root must resolve to one package: {selector}")
            resolved.update(matches)
        return resolved

    roots = resolve_roots(settings.root_packages)
    section_roots = {}
    known_views = set()
    unscoped_views = set()
    for key, section_config in settings.sections.items():
        if key == "other":
            raise ValueError("Documentation section 'other' is reserved for unmapped views")
        section_roots[key] = resolve_roots(section_config.root_packages)
        for view in section_config.views:
            view = view.upper()
            known_views.add(view)
            if not section_config.root_packages:
                if view in unscoped_views:
                    raise ValueError(f"Documentation view mapped more than once: {view}")
                unscoped_views.add(view)
    exclusions = {normalize_guid(guid): reason for guid, reason in settings.exclude_diagrams.items()}
    if any(not reason.strip() for reason in exclusions.values()):
        raise ValueError("Every excluded documentation diagram needs a reason")
    entries = []
    for row in diagram_rows:
        ancestors = []
        current = row["Package_ID"]
        while current in packages:
            if current in ancestors:
                raise ValueError("Cycle in model package hierarchy")
            ancestors.append(current)
            current = packages[current]["Parent_ID"]
        if not roots.intersection(ancestors):
            continue
        guid = normalize_guid(row["ea_guid"] or "")
        if not guid:
            raise ValueError(f"Documentation diagram has no GUID: {row['Diagram_ID']}")
        # The NAF profile is authoritative; package ancestry also handles ordinary UML diagrams.
        match = re.search(r"MDGDgm=[^;]*::([^;]+?)(?: - |;|$)", row.get("StyleEx") or "")
        view = match.group(1).strip().upper() if match else ""
        if not view:
            view = next(
                (packages[i]["Name"].upper() for i in ancestors if packages[i]["Name"].upper() in known_views), ""
            )
        matches = [
            key
            for key, section_config in settings.sections.items()
            if view in [v.upper() for v in section_config.views]
            and (not section_roots[key] or section_roots[key].intersection(ancestors))
        ]
        if len(matches) > 1:
            raise ValueError(f"Documentation diagram matches multiple sections: {row['Name']}")
        section = matches[0] if matches else "other"
        entries.append(
            {
                "guid": guid,
                "diagram_id": row["Diagram_ID"],
                "name": row["Name"] or guid,
                "type": row["Diagram_Type"] or "",
                "view": view,
                "section": section,
                "package": "/".join(packages[i]["Name"] for i in reversed(ancestors)),
                "notes": row.get("Notes") or "",
                "url": f"diagrams/{guid}.html",
                "status": "excluded" if guid in exclusions else "pending",
                "reason": exclusions.get(guid, ""),
            }
        )
    scoped = {entry["guid"] for entry in entries}
    unknown = set(exclusions) - scoped
    if unknown:
        raise ValueError(f"Excluded diagrams outside documentation scope: {sorted(unknown)}")
    if len(scoped) != len(entries):
        raise ValueError("Duplicate diagram GUIDs in documentation scope")
    return sorted(entries, key=lambda entry: (entry["package"], entry["name"], entry["guid"]))


def export_documentation(config, packages, output_dir: Path, env):
    """Render every scoped diagram or record an explicit exclusion/failure."""
    settings = config.documentation
    if not settings.root_packages:
        return []
    extractor = NativeDiagramExtractor.from_url(config.database_url)
    try:
        package_rows = [
            dict(row)
            for row in extractor.session.execute(
                text("SELECT Package_ID, Parent_ID, Name, ea_guid FROM t_package")
            ).mappings()
        ]
        diagram_rows = [
            dict(row)
            for row in extractor.session.execute(
                text("SELECT Diagram_ID, Package_ID, Name, ea_guid, Diagram_Type, Notes, StyleEx FROM t_diagram")
            ).mappings()
        ]
        entries = select_diagrams(package_rows, diagram_rows, settings)
        urls = {}

        def collect(cls, _package):
            if cls.guid:
                urls[normalize_guid(cls.guid)] = f"../classes/{'/'.join(cls.namespace)}/{cls.name}.html"

        traverse_packages(packages, class_visitor=collect)
        diagram_dir = output_dir / "diagrams"
        diagram_dir.mkdir(exist_ok=True)
        published = {entry["guid"] for entry in entries if entry["status"] != "excluded"}
        # Remove catalogue assets from an earlier, broader documentation scope.
        for path in diagram_dir.iterdir():
            if path.suffix in (".html", ".svg") and path.stem not in published:
                path.unlink()
        for entry in entries:
            if entry["status"] == "excluded":
                # A refreshed output must not retain a previously published excluded diagram.
                for suffix in (".html", ".svg"):
                    (diagram_dir / f"{entry['guid']}{suffix}").unlink(missing_ok=True)
                continue
            try:
                diagram = extractor.extract_by_id(entry["diagram_id"])
                svg = render_svg(diagram, config.diagrams.native_diagram_style)
                placeholders = set(re.findall(r"eaidl:(\{[^}]+\})", svg))
                resolved = {guid: urls[normalize_guid(guid)] for guid in placeholders if normalize_guid(guid) in urls}
                svg = rewrite_svg_links(svg, resolved)
                # Context-only elements remain visible without links to absent type pages.
                svg = re.sub(r'\s+(?:xlink:)?href="eaidl:[^"]*"', "", svg)
                if config.diagrams.native_diagram_style.ea_detail_nodes:
                    # The detailed renderer preserves EA's text layout without anchor elements.
                    # Add a transparent header hit area for documented class nodes.
                    root = ET.fromstring(svg)
                    ns = "{http://www.w3.org/2000/svg}"
                    for node in diagram.nodes:
                        url = urls.get(normalize_guid(node.ea_guid or ""))
                        if not url or node.object_type != "Class":
                            continue
                        anchor = ET.SubElement(root, ns + "a", href=url)
                        ET.SubElement(anchor, ns + "title").text = f"Open {node.name} type reference"
                        ET.SubElement(
                            anchor,
                            ns + "rect",
                            x=str(node.rect_left),
                            y=str(-node.rect_top),
                            width=str(max(0, node.rect_right - node.rect_left)),
                            height=str(min(24, max(0, node.rect_top - node.rect_bottom))),
                            fill="transparent",
                            **{"pointer-events": "all"},
                        )
                    ET.register_namespace("", "http://www.w3.org/2000/svg")
                    svg = ET.tostring(root, encoding="unicode")
                if config.diagrams.native_diagram_style.font_family == "Carlito":
                    root = ET.fromstring(svg)
                    font_css = "\n".join(
                        "@font-face {font-family:Carlito;"
                        f"src:url('../assets/fonts/carlito/Carlito-{name}.ttf') format('truetype');"
                        f"font-weight:{weight};font-style:{font_style};" + "}"
                        for name, weight, font_style in [
                            ("Regular", 400, "normal"),
                            ("Bold", 700, "normal"),
                            ("Italic", 400, "italic"),
                            ("BoldItalic", 700, "italic"),
                        ]
                    )
                    ET.SubElement(root, "{http://www.w3.org/2000/svg}style").text = font_css
                    ET.register_namespace("", "http://www.w3.org/2000/svg")
                    svg = ET.tostring(root, encoding="unicode")
                (diagram_dir / f"{entry['guid']}.svg").write_text(svg, encoding="utf-8")
                page = env.get_template("view.jinja2").render(
                    entry=entry,
                    svg=svg,
                    current_namespace=None,
                    index_link="../index.html",
                    assets_path="../assets",
                    search_index_path="../search.json",
                    generate_package_link_from_current=lambda _current, target: (
                        f"../packages/{'/'.join(target)}/index.html"
                    ),
                )
                (output_dir / entry["url"]).write_text(page, encoding="utf-8")
                entry["status"] = "rendered"
            except Exception as error:
                entry["status"] = "failed"
                entry["reason"] = str(error)
                for suffix in (".html", ".svg"):
                    (diagram_dir / f"{entry['guid']}{suffix}").unlink(missing_ok=True)
        counts = dict(Counter(entry["status"] for entry in entries))
        report = {"total": len(entries), "counts": counts, "diagrams": entries}
        (output_dir / "diagram-coverage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        groups = []
        for key, section in settings.sections.items():
            groups.append({"id": key, "title": section.title, "entries": [e for e in entries if e["section"] == key]})
        groups.append(
            {"id": "other", "title": "Other model views", "entries": [e for e in entries if e["section"] == "other"]}
        )
        page = env.get_template("catalogue.jinja2").render(
            groups=groups,
            counts=counts,
            total=len(entries),
            current_namespace=None,
            index_link="index.html",
            assets_path="assets",
            search_index_path="search.json",
        )
        (output_dir / "diagrams.html").write_text(page, encoding="utf-8")
        if counts.get("failed") and settings.fail_on_diagram_error:
            raise RuntimeError(f"{counts['failed']} documentation diagrams failed; see diagram-coverage.json")
        return [
            {
                "name": e["name"],
                "guid": e["guid"],
                "type": "diagram",
                "namespace": [e["view"], e["package"]],
                "content": strip_html(e["notes"]),
                "url": e["url"],
            }
            for e in entries
            if e["status"] == "rendered"
        ]
    finally:
        extractor.close()
