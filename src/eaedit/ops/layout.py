"""The ``layout`` operation: a described or suggested layout applied to a diagram through ``place``/``set_bounds``."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from eacore.embedded import duid
from eacore.records import Record, Ref
from eaedit.diagrams.geometry import Rect, from_ea
from eaedit.errors import InvalidOperationError
from eaedit.layout.engine import (
    CHILD_GAP,
    MARGIN,
    PAGE,
    Box,
    Edge,
    contain,
    fits,
    hub,
    layers,
    split_suggestion,
    suggest,
)
from eaedit.ops import operation
from eaedit.ops.diagrams import _SIZE, _SIZES, _diagram, diagram_objects, place, set_bounds, shown_element
from eaedit.resolve import guid_of

#: Spec keys each pattern takes, besides ``pattern`` and ``page``.
_ARGS = {
    "layers": {"rows", "direction", "gap"},
    "hub": {"center", "above", "below", "left", "right", "gap"},
    "contain": {"owner", "children", "padding"},
    "suggest": {"elements", "focus", "gap"},
}
#: Header of an EA-detail node with a stereotype line, and its attribute rows (eaidl's ``_ea_attribute_rows``).
_HEADER_H = 37
_ROW_H = 13
_FIRST_ROW = 14
_STEREOTYPE_ROW = 17
_BOTTOM = 6
_PADDING_X = 10

#: Space on each side of a connector label between two Parts.
LABEL_MARGIN = 20


@dataclass
class LayoutReport:
    """Where each element goes (by element GUID), whether it fits the page, a split when it does not, and the
    elements left alone because they are on the diagram more than once."""

    rects: dict[str, Rect]
    fits: bool
    split: list[list[str]] | None
    skipped: list[str] = field(default_factory=list)


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


#: Connector types drawn with the target above the source: the general or abstract end on top, as UML draws them.
_TARGET_ABOVE = {"Generalization", "Realization", "Realisation", "Abstraction"}
#: Connector types drawn with the whole above the part; the whole is the end marked ``...IsAggregate``, else the
#: target (eaedit's own ``connect`` marks neither end, and UML puts the diamond at the target).
_WHOLE_ABOVE = {"Aggregation", "Composition"}


def _edge(values: dict, source: str, target: str) -> Edge:
    """The layout edge of a connector: the end to draw above first."""
    kind = values.get("attr_connector_type")
    if kind in _TARGET_ABOVE:
        return Edge(target, source)
    if kind in _WHOLE_ABOVE and not values.get("attr_sourceisaggregate"):
        return Edge(target, source)
    return Edge(source, target)


class _Plan:
    """What ``plan_layout`` gathers: the diagram, its objects by element, and the boxes of the elements laid out."""

    def __init__(self, session, diagram: str):
        self.session = session
        self.diagram = diagram
        self.record = _diagram(session, diagram)
        self.shown: dict[str, list[Record]] = {}
        #: Rectangles of dangling objects (their element is gone): never moved, but the layout keeps clear of them.
        self.dangling: list[Rect] = []
        for obj in diagram_objects(session, Ref("t_diagram", self.record.key)):
            element = shown_element(session, obj)
            if element is None:
                self.dangling.append(from_ea(obj.values))
            else:
                self.shown.setdefault(element.key, []).append(obj)
        #: Elements shown more than once: which object to move is ambiguous, so they are left alone.
        self.twice = {k for k, objects in self.shown.items() if len(objects) > 1}
        self.skipped: list[str] = []
        self.boxes: dict[str, Box] = {}
        #: Rectangles inside each box, relative to the box placed at (0, 0): the element itself, its Parts and the
        #: Notes beside it.
        self.inner: dict[str, dict[str, Rect]] = {}

    def keys(self, values, what: str) -> list[str]:
        """Element keys named by ``values``; elements shown twice are skipped (``layout`` warns)."""
        if isinstance(values, str) or not isinstance(values, (list, tuple)):
            raise InvalidOperationError(f"{what} is a list of elements, not {values!r}")
        keys = [self.session.find(v, kinds=("element",)).key for v in values]
        for key in keys:
            if key in self.twice and key not in self.skipped:
                self.skipped.append(key)
        return [k for k in keys if k not in self.twice]

    def element(self, key: str) -> Record:
        return self.session.working.get("t_object", key)

    def current(self, key: str) -> Rect | None:
        objects = self.shown.get(key, [])
        return from_ea(objects[0].values) if objects else None

    def parts(self, owner: str, members: set[str]) -> list[str]:
        """The owner's Parts that are on the diagram (once) or laid out, in key order."""
        ref = Ref("t_object", owner)
        return sorted(
            r.key
            for r in self.session.working.records("t_object")
            if r.values.get("attr_parentid") == ref
            and r.values.get("attr_object_type") == "Part"
            and (r.key in self.shown or r.key in members)
            and r.key not in self.twice
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
            self.inner[key] = contain(key, children, self.boxes, padding, spacing=self.child_gap(children))
            owner = self.inner[key][key]
            self.boxes[key] = Box(key, owner[2] - owner[0], owner[3] - owner[1])
        return self.boxes[key]

    def child_gap(self, children: list[str]) -> tuple[int, int]:
        """Room between Parts: at least ``CHILD_GAP``, and wide enough for the label of a connector between two of them."""
        from eaedit.diagrams.render import text_width  # the only module allowed to reach the renderer

        refs = {Ref("t_object", k) for k in children}
        width = CHILD_GAP[0]
        for connector in self.session.working.records("t_connector"):
            values = connector.values
            if values.get("attr_start_object_id") in refs and values.get("attr_end_object_id") in refs:
                label = values.get("attr_btm_mid_label") or values.get("attr_name") or ""
                lines = [line for line in label.splitlines() if line]
                if lines:
                    width = max(width, int(max(text_width(line, 8) for line in lines)) + 2 * LABEL_MARGIN)
        return width, CHILD_GAP[1]

    def beside(self, keys: list[str], gap: int) -> list[str]:
        """Notes linked to a laid-out element join that element's box, to its right; ``keys`` without them."""
        notes = [k for k in keys if self.element(k).values.get("attr_object_type") == "Note"]
        others = set(keys) - set(notes)
        attached: dict[str, list[str]] = {}
        for connector in sorted(self.session.working.records("t_connector"), key=lambda r: r.key):
            values = connector.values
            if values.get("attr_connector_type") != "NoteLink":
                continue
            ends = [values.get(c) for c in ("attr_start_object_id", "attr_end_object_id")]
            if not all(isinstance(e, Ref) for e in ends):
                continue
            # Hand-made NoteLinks run element -> Note (all 6 in nafv4.qea); either direction is read.
            for note, element in (ends, reversed(ends)):
                if note.key in notes and element.key in others and not any(note.key in v for v in attached.values()):
                    attached.setdefault(element.key, []).append(note.key)
        for element, linked in attached.items():
            box = self.boxes[element]
            inner = self.inner.setdefault(element, {element: (0, 0, box.width, box.height)})
            left, top = box.width + gap, 0
            for note in linked:
                size = self.boxes[note]
                inner[note] = (left, top, left + size.width, top + size.height)
                top += size.height + gap
            self.boxes[element] = Box(element, max(r[2] for r in inner.values()), max(r[3] for r in inner.values()))
        placed = {n for linked in attached.values() for n in linked}
        return [k for k in keys if k not in placed]

    def owned(self, key: str, members: set[str]) -> bool:
        """A Part whose owner is laid out goes inside the owner, not into the pattern."""
        parent = self.element(key).values.get("attr_parentid")
        return (
            self.element(key).values.get("attr_object_type") == "Part"
            and isinstance(parent, Ref)
            and parent.key in members
        )

    def edges(self, keys: list[str]) -> list[Edge]:
        """Connectors among ``keys`` (inner ends count as their outermost laid-out box), in connector order."""
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
                edges.append(_edge(values, source, target))
        return edges

    def expand(self, rects: dict[str, Rect]) -> dict[str, Rect]:
        """Each box's contents moved into the box's rectangle, outer elements before inner ones."""
        result: dict[str, Rect] = {}
        pending = list(rects.items())
        while pending:
            key, rect = pending.pop(0)
            inner = self.inner.get(key, {})
            own = inner.get(key, (0, 0, rect[2] - rect[0], rect[3] - rect[1]))
            result[key] = (own[0] + rect[0], own[1] + rect[1], own[2] + rect[0], own[3] + rect[1])
            for child, box in inner.items():
                if child != key:
                    pending.append((child, (box[0] + rect[0], box[1] + rect[1], box[2] + rect[0], box[3] + rect[1])))
        return result

    def unnamed(self, laid_out: dict[str, Rect]) -> list[Rect]:
        """Rectangles of the diagram's objects the layout was not given."""
        given = [from_ea(o.values) for k, objects in sorted(self.shown.items()) if k not in laid_out for o in objects]
        return given + self.dangling


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


def _padding(spec: dict) -> int:
    padding = spec.get("padding", 20)
    if isinstance(padding, bool) or not isinstance(padding, int):
        raise InvalidOperationError(f"padding is a whole number of pixels, not {padding!r}")
    return padding


def _overlap(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _anchor(rects: dict[str, Rect], below: list[Rect], gap: int) -> dict[str, Rect]:
    """``rects`` moved, together, below every object in ``below`` (the objects the layout was not given)."""
    if not rects or not below:
        return rects
    dx = MARGIN - min(r[0] for r in rects.values())
    dy = max(r[3] for r in below) + gap - min(r[1] for r in rects.values())
    return {k: (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy) for k, r in rects.items()}


def plan_layout(session, diagram: str, spec: dict) -> LayoutReport:
    """The rectangles ``layout`` would apply; nothing is staged.

    ``spec`` is ``{"pattern": ..., ...}`` naming elements by qualified name or GUID:
    ``layers`` (``rows``, ``direction`` "down"/"right", ``gap``), ``hub`` (``center``, ``above``/``below``/``left``/
    ``right``), ``contain`` (``owner``, ``children`` default its Parts, ``padding``), ``suggest`` (``elements``
    default everything on the diagram, ``focus`` centred in its layer). Any pattern takes ``page`` (width, height).
    Elements already on the diagram keep their size; others get ``size_for``. Parts whose owner is laid out are
    contained in it; ``suggest`` puts a Note linked to a laid-out element to that element's right. Objects the
    layout is not given stay put, and the layout goes below them. Elements shown twice are skipped.
    """
    if not isinstance(spec, dict) or spec.get("pattern") not in _ARGS:
        raise InvalidOperationError(f"spec needs a pattern, one of {', '.join(_ARGS)}: {spec!r}")
    pattern = spec["pattern"]
    unknown = sorted(set(spec) - _ARGS[pattern] - {"pattern", "page"})
    if unknown:
        raise InvalidOperationError(f"pattern {pattern!r} takes {', '.join(sorted(_ARGS[pattern]))}, not {unknown}")
    plan = _Plan(session, diagram)
    gap = _gap(spec)
    anchored = True
    try:
        if pattern == "layers":
            rows = [plan.keys(row, "a row") for row in spec.get("rows") or []]
            members = {k for row in rows for k in row}
            rows = [[k for k in row if not plan.owned(k, members)] for row in rows]
            for key in (k for row in rows for k in row):
                plan.box(key, members)
            rects = layers(rows, plan.boxes, gap, spec.get("direction", "down"))
        elif pattern == "hub":
            if "center" not in spec:
                raise InvalidOperationError("hub needs a center")
            center = plan.keys([spec["center"]], "center")
            sides = ("above", "below", "left", "right")
            groups = {side: plan.keys(spec[side], side) for side in sides if side in spec}
            members = {*center, *(k for keys in groups.values() for k in keys)}
            groups = {side: [k for k in keys if not plan.owned(k, members)] for side, keys in groups.items()}
            for key in [*center, *(k for keys in groups.values() for k in keys)]:
                plan.box(key, members)
            rects = hub(center[0], groups, plan.boxes, gap) if center else {}
        elif pattern == "contain":
            if "owner" not in spec:
                raise InvalidOperationError("contain needs an owner")
            padding = _padding(spec)
            owner = plan.keys([spec["owner"]], "owner")
            rects = {}
            if owner:
                (owner,) = owner
                children = plan.keys(spec["children"], "children") if "children" in spec else _all_parts(plan, owner)
                box = plan.box(owner, {owner, *children}, children, padding)
                left, top = (plan.current(owner) or (MARGIN, MARGIN))[:2]
                rects = {owner: (left, top, left + box.width, top + box.height)}
                # An owner already on the diagram grows in place unless it would then cover an object not given.
                laid_out = plan.expand(rects)
                anchored = plan.current(owner) is None or any(
                    _overlap(r, o) for r in laid_out.values() for o in plan.unnamed(laid_out)
                )
        else:
            given = "elements" in spec
            keys = plan.keys(spec["elements"], "elements") if given else sorted(set(plan.shown) - plan.twice)
            if not given:
                plan.skipped += sorted(plan.twice)
            focus = None
            if spec.get("focus") is not None:
                found = plan.keys([spec["focus"]], "focus")
                if not found:
                    raise InvalidOperationError(f"focus {spec['focus']!r} is on the diagram more than once")
                focus = found[0]
            members = set(keys)
            keys = [k for k in keys if not plan.owned(k, members)]
            for key in keys:
                plan.box(key, members)
            keys = plan.beside(keys, gap[0])
            rects = suggest({k: plan.boxes[k] for k in keys}, plan.edges(keys), gap, focus=focus)
    except ValueError as exc:
        raise InvalidOperationError(str(exc)) from None
    if anchored:
        rects = _anchor(rects, plan.unnamed(plan.expand(rects)), gap[1])
    page = _page(plan, spec)
    everything = plan.expand(rects)
    if fits(everything, page):
        return LayoutReport(everything, True, None, plan.skipped)
    groups = split_suggestion(rects, plan.edges(list(rects)), page)
    split = [list(plan.expand({g: rects[g] for g in group})) for group in groups]
    return LayoutReport(everything, False, split, plan.skipped)


def _all_parts(plan: _Plan, owner: str) -> list[str]:
    """Every Part of ``owner`` in the model, in key order: ``contain`` without ``children`` shows them all."""
    ref = Ref("t_object", owner)
    return sorted(
        r.key
        for r in plan.session.working.records("t_object")
        if r.values.get("attr_parentid") == ref
        and r.values.get("attr_object_type") == "Part"
        and r.key not in plan.twice
    )


def _name(session, key: str) -> str:
    return session.working.get("t_object", key).values.get("attr_name") or key


@operation("layout")
def layout(session, diagram: str, spec: dict) -> str:
    report = plan_layout(session, diagram, spec)
    record = _diagram(session, diagram)
    this = Ref("t_diagram", record.key)
    shown = {}
    for obj in diagram_objects(session, this):
        element = shown_element(session, obj)
        if element is not None:
            shown[element.key] = obj
    for key in report.skipped:
        element = session.working.get("t_object", key)
        message = f"{_name(session, key)!r} is on the diagram more than once: not moved"
        session.warn("layout-skipped", message, guid_of(element))
    # Owners come before their Parts in ``report.rects``, so each Part is set inside its owner's new rectangle.
    for key, rect in report.rects.items():
        obj = shown.get(key)
        if obj is None:
            place(session, diagram, key, rect)
        elif from_ea(obj.values) != rect:
            set_bounds(session, diagram, duid(obj.values.get("attr_objectstyle")) or key, rect)
    if not report.fits:
        names = " | ".join(", ".join(_name(session, k) for k in group) for group in report.split or [])
        session.warn(
            "page-overflow",
            f"the layout does not fit one page; split suggestion ({len(report.split or [])} diagrams): {names}",
            guid_of(record),
        )
    return guid_of(record)
