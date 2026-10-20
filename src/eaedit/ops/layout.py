"""The ``layout`` operation: a described or suggested layout applied to a diagram through ``place``/``set_bounds``."""

from __future__ import annotations

import math
from dataclasses import dataclass

from eacore.embedded import duid
from eacore.records import Record, Ref
from eaedit.diagrams.geometry import Rect, from_ea
from eaedit.errors import InvalidOperationError
from eaedit.layout.engine import MARGIN, PAGE, Box, Edge, contain, fits, hub, layers, split_suggestion, suggest
from eaedit.ops import operation
from eaedit.ops.diagrams import _SIZE, _SIZES, _diagram, _objects, place, set_bounds
from eaedit.resolve import guid_of

#: Spec keys each pattern takes, besides ``pattern`` and ``page``.
_ARGS = {
    "layers": {"rows", "direction", "gap"},
    "hub": {"center", "above", "below", "left", "right", "gap"},
    "contain": {"owner", "children", "padding"},
    "suggest": {"elements", "gap"},
}
#: Header of an EA-detail node with a stereotype line, and its attribute rows (eaidl's ``_ea_attribute_rows``).
_HEADER_H = 37
_ROW_H = 13
_FIRST_ROW = 14
_STEREOTYPE_ROW = 17
_BOTTOM = 6
_PADDING_X = 10


@dataclass
class LayoutReport:
    """Where each element goes (by element GUID), whether it fits the page, and a split when it does not."""

    rects: dict[str, Rect]
    fits: bool
    split: list[list[str]] | None


def _attributes(session, element: Record) -> list[Record]:
    ref = Ref("t_object", element.key)
    return [r for r in session.working.records("t_attribute") if r.values.get("attr_object_id") == ref]


def size_for(session, element: str, diagram: str | None = None) -> tuple[int, int]:
    """A box for ``element`` fitting its stereotype, name and attributes (none when ``diagram`` hides them).

    Never smaller than the default size ``place`` gives the element's kind.
    """
    from eaedit.diagrams.render import text_width  # the only module allowed to reach the renderer

    record = session.working.resolve(session.find(element, kinds=("element",)))
    kind = record.values.get("attr_object_type")
    least_w, least_h = _SIZES.get(kind, _SIZE)
    lines = [record.values.get("attr_name") or ""]
    if record.values.get("attr_stereotype"):
        lines.append(f"«{record.values['attr_stereotype']}»")
    attributes = [] if kind in _SIZES else _attributes(session, record)
    if diagram is not None and "HideAtts=1" in (_diagram(session, diagram).values.get("attr_pdata") or ""):
        attributes = []
    lines += [f"+ {a.values.get('attr_name')}: {a.values.get('attr_type') or ''}" for a in attributes]
    width = math.ceil(max(text_width(line) for line in lines)) + 2 * _PADDING_X
    height = least_h
    if attributes:
        headings = len({a.values.get("attr_stereotype") for a in attributes if a.values.get("attr_stereotype")})
        height = _HEADER_H + _FIRST_ROW + _ROW_H * (len(attributes) - 1) + _STEREOTYPE_ROW * headings + _BOTTOM
    return max(width, least_w), max(height, least_h)


class _Plan:
    """What ``plan_layout`` gathers: the diagram, its objects by element, and the boxes of the elements laid out."""

    def __init__(self, session, diagram: str):
        self.session = session
        self.diagram = diagram
        self.record = _diagram(session, diagram)
        self.shown: dict[str, list[Record]] = {}
        for obj in _objects(session, Ref("t_diagram", self.record.key)):
            self.shown.setdefault(obj.values["attr_object_id"].key, []).append(obj)
        self.boxes: dict[str, Box] = {}
        #: Rectangles of each owner's Parts, relative to the owner placed at (0, 0).
        self.inner: dict[str, dict[str, Rect]] = {}

    def key(self, identifier: str) -> str:
        return self.session.find(identifier, kinds=("element",)).key

    def element(self, key: str) -> Record:
        return self.session.working.get("t_object", key)

    def current(self, key: str) -> Rect | None:
        objects = self.shown.get(key, [])
        if len(objects) > 1:
            name = self.element(key).values.get("attr_name")
            raise InvalidOperationError(f"{name!r} is on the diagram {len(objects)} times: lay out one diagram each")
        return from_ea(objects[0].values) if objects else None

    def parts(self, owner: str, members: set[str]) -> list[str]:
        """The owner's Parts that are on the diagram or laid out, in key order."""
        ref = Ref("t_object", owner)
        return sorted(
            r.key
            for r in self.session.working.records("t_object")
            if r.values.get("attr_parentid") == ref
            and r.values.get("attr_object_type") == "Part"
            and (r.key in self.shown or r.key in members)
        )

    def box(self, key: str, members: set[str], children: list[str] | None = None, padding: int = 20) -> Box:
        """``key``'s box, grown to contain its Parts (each laid out the same way first)."""
        rect = self.current(key)
        if rect is not None:
            width, height = rect[2] - rect[0], rect[3] - rect[1]
        else:
            width, height = size_for(self.session, key, self.diagram)
        self.boxes[key] = Box(key, width, height)
        children = self.parts(key, members) if children is None else children
        if children:
            for child in children:
                self.box(child, members)
            self.inner[key] = contain(key, children, self.boxes, padding)
            owner = self.inner[key][key]
            self.boxes[key] = Box(key, owner[2] - owner[0], owner[3] - owner[1])
        return self.boxes[key]

    def owned(self, key: str, members: set[str]) -> bool:
        """A Part whose owner is laid out goes inside the owner, not into the pattern."""
        parent = self.element(key).values.get("attr_parentid")
        return (
            self.element(key).values.get("attr_object_type") == "Part"
            and isinstance(parent, Ref)
            and parent.key in members
        )

    def edges(self, keys: list[str]) -> list[Edge]:
        """Connectors among ``keys`` (a Part's ends count as its outermost laid-out owner), in connector order."""
        top: dict[str, str] = {k: k for k in keys}
        for owner in keys:
            stack = [owner]
            while stack:
                for child in self.inner.get(stack.pop(), {}):
                    if child not in top:
                        top[child] = owner
                        stack.append(child)
        edges = []
        for connector in sorted(self.session.working.records("t_connector"), key=lambda r: r.key):
            values = connector.values
            if values.get("attr_connector_type") == "Sequence":
                continue
            ends = [values.get(c) for c in ("attr_start_object_id", "attr_end_object_id")]
            if not all(isinstance(e, Ref) and e.key in top for e in ends):
                continue
            source, target = (top[e.key] for e in ends)
            if source != target:
                edges.append(Edge(source, target))
        return edges

    def expand(self, rects: dict[str, Rect]) -> dict[str, Rect]:
        """``rects`` with each owner's Parts moved into it, owners before their Parts."""
        result: dict[str, Rect] = {}
        pending = list(rects.items())
        while pending:
            key, rect = pending.pop(0)
            result[key] = rect
            for child, inner in self.inner.get(key, {}).items():
                if child != key:
                    pending.append(
                        (child, (inner[0] + rect[0], inner[1] + rect[1], inner[2] + rect[0], inner[3] + rect[1]))
                    )
        return result


def _keys(plan: _Plan, values, what: str) -> list[str]:
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise InvalidOperationError(f"{what} is a list of elements, not {values!r}")
    return [plan.key(v) for v in values]


def _gap(spec: dict) -> tuple[int, int]:
    gap = spec.get("gap", (40, 60))
    try:
        across, along = (int(v) for v in gap)
    except (TypeError, ValueError):
        raise InvalidOperationError(f"gap is (between neighbours, between rows), not {gap!r}") from None
    return across, along


def _page(plan: _Plan, spec: dict) -> tuple[int, int]:
    """``spec["page"]``, else the diagram's own ``cx``/``cy`` (what EA stores as the page), else A4 portrait."""
    page = spec.get("page")
    if page is not None:
        try:
            width, height = (int(v) for v in page)
        except (TypeError, ValueError):
            raise InvalidOperationError(f"page is (width, height), not {page!r}") from None
        return width, height
    width, height = plan.record.values.get("attr_cx"), plan.record.values.get("attr_cy")
    return (width, height) if width and height else PAGE


def plan_layout(session, diagram: str, spec: dict) -> LayoutReport:
    """The rectangles ``layout`` would apply; nothing is staged.

    ``spec`` is ``{"pattern": ..., ...}`` naming elements by qualified name or GUID:
    ``layers`` (``rows``, ``direction`` "down"/"right", ``gap``), ``hub`` (``center``, ``above``/``below``/``left``/
    ``right``), ``contain`` (``owner``, ``children`` default its Parts, ``padding``), ``suggest`` (``elements``
    default everything on the diagram). Any pattern takes ``page`` (width, height). Elements already on the diagram
    keep their size; others get ``size_for``. Parts whose owner is laid out are contained in it.
    """
    if not isinstance(spec, dict) or spec.get("pattern") not in _ARGS:
        raise InvalidOperationError(f"spec needs a pattern, one of {', '.join(_ARGS)}: {spec!r}")
    pattern = spec["pattern"]
    unknown = sorted(set(spec) - _ARGS[pattern] - {"pattern", "page"})
    if unknown:
        raise InvalidOperationError(f"pattern {pattern!r} takes {', '.join(sorted(_ARGS[pattern]))}, not {unknown}")
    plan = _Plan(session, diagram)
    try:
        if pattern == "layers":
            rows = [_keys(plan, row, "a row") for row in spec.get("rows") or []]
            members = {k for row in rows for k in row}
            rows = [[k for k in row if not plan.owned(k, members)] for row in rows]
            for key in (k for row in rows for k in row):
                plan.box(key, members)
            rects = layers(rows, plan.boxes, _gap(spec), spec.get("direction", "down"))
        elif pattern == "hub":
            if "center" not in spec:
                raise InvalidOperationError("hub needs a center")
            center = plan.key(spec["center"])
            groups = {
                side: _keys(plan, spec[side], side) for side in ("above", "below", "left", "right") if side in spec
            }
            members = {center, *(k for keys in groups.values() for k in keys)}
            groups = {side: [k for k in keys if not plan.owned(k, members)] for side, keys in groups.items()}
            for key in [center, *(k for keys in groups.values() for k in keys)]:
                plan.box(key, members)
            rects = hub(center, groups, plan.boxes, _gap(spec))
        elif pattern == "contain":
            if "owner" not in spec:
                raise InvalidOperationError("contain needs an owner")
            owner = plan.key(spec["owner"])
            children = _keys(plan, spec["children"], "children") if "children" in spec else _all_parts(plan, owner)
            box = plan.box(owner, {owner, *children}, children, int(spec.get("padding", 20)))
            left, top = (plan.current(owner) or (MARGIN, MARGIN))[:2]
            rects = {owner: (left, top, left + box.width, top + box.height)}
        else:
            keys = _keys(plan, spec["elements"], "elements") if "elements" in spec else sorted(plan.shown)
            members = set(keys)
            keys = [k for k in keys if not plan.owned(k, members)]
            for key in keys:
                plan.box(key, members)
            rects = suggest({k: plan.boxes[k] for k in keys}, plan.edges(keys), _gap(spec))
    except ValueError as exc:
        raise InvalidOperationError(str(exc)) from None
    page = _page(plan, spec)
    everything = plan.expand(rects)
    if fits(everything, page):
        return LayoutReport(everything, True, None)
    groups = split_suggestion(rects, plan.edges(list(rects)), page)
    split = [[k for k in plan.expand({g: rects[g] for g in group})] for group in groups]
    return LayoutReport(everything, False, split)


def _all_parts(plan: _Plan, owner: str) -> list[str]:
    """Every Part of ``owner`` in the model, in key order: ``contain`` without ``children`` shows them all."""
    ref = Ref("t_object", owner)
    return sorted(
        r.key
        for r in plan.session.working.records("t_object")
        if r.values.get("attr_parentid") == ref and r.values.get("attr_object_type") == "Part"
    )


@operation("layout")
def layout(session, diagram: str, spec: dict) -> str:
    report = plan_layout(session, diagram, spec)
    record = _diagram(session, diagram)
    this = Ref("t_diagram", record.key)
    shown = {o.values["attr_object_id"].key: o for o in _objects(session, this)}
    # Owners come before their Parts in ``report.rects``, so each Part is set inside its owner's new rectangle.
    for key, rect in report.rects.items():
        obj = shown.get(key)
        if obj is None:
            place(session, diagram, key, rect)
        elif from_ea(obj.values) != rect:
            set_bounds(session, diagram, duid(obj.values.get("attr_objectstyle")) or key, rect)
    if not report.fits:
        names = " | ".join(
            ", ".join(session.working.get("t_object", k).values.get("attr_name") or k for k in group)
            for group in report.split or []
        )
        session.warn(
            "page-overflow",
            f"the layout does not fit one page; split suggestion ({len(report.split or [])} diagrams): {names}",
            guid_of(record),
        )
    return guid_of(record)
