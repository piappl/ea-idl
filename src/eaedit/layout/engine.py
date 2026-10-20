"""Layout patterns as pure functions: boxes in, rectangles out (SVG orientation, ``(left, top, right, bottom)``).

Every function is deterministic: ties are broken by box key, never by dict or set order.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from eaedit.diagrams.geometry import Rect


@dataclass(frozen=True)
class Box:
    key: str
    width: int
    height: int
    parent: str | None = None


@dataclass(frozen=True)
class Edge:
    """``source`` is laid out above (or before) ``target``."""

    source: str
    target: str


#: Gap between neighbours in a row, gap between rows.
GAP = (40, 60)
#: A4 portrait, the ``cx``/``cy`` of the hand-made uuid/p2/p6 diagrams in nafv4.qea.
PAGE = (791, 1134)
MARGIN = 20
#: An owner's name compartment above its Parts, and the spacing between Parts (as ``place`` leaves them).
NAME_H = 30
SPACING = 10
SIDES = ("above", "below", "left", "right")


def _shift(rects: dict[str, Rect], origin: tuple[int, int]) -> dict[str, Rect]:
    """``rects`` moved together so their bounding box starts at ``origin``."""
    if not rects:
        return {}
    dx = origin[0] - min(r[0] for r in rects.values())
    dy = origin[1] - min(r[1] for r in rects.values())
    return {k: (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy) for k, r in rects.items()}


def _unique(keys: Iterable[str]) -> None:
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            raise ValueError(f"{key!r} is laid out twice")
        seen.add(key)


def layers(
    rows: list[list[str]],
    boxes: dict[str, Box],
    gap: tuple[int, int] = GAP,
    direction: str = "down",
    origin: tuple[int, int] = (MARGIN, MARGIN),
) -> dict[str, Rect]:
    """One row per list, in order, each centred on the widest; ``direction="right"`` makes the rows columns."""
    if direction not in ("down", "right"):
        raise ValueError(f"direction is 'down' or 'right', not {direction!r}")
    _unique(k for row in rows for k in row)
    across, along = gap
    down = direction == "down"

    def extent(key: str) -> tuple[int, int]:
        box = boxes[key]
        return (box.width, box.height) if down else (box.height, box.width)

    rows = [row for row in rows if row]
    lengths = [sum(extent(k)[0] for k in row) + across * (len(row) - 1) for row in rows]
    span = max(lengths, default=0)
    rects: dict[str, Rect] = {}
    v = 0
    for row, length in zip(rows, lengths):
        depth = max(extent(k)[1] for k in row)
        u = (span - length) // 2
        for key in row:
            eu, ev = extent(key)
            top = v + (depth - ev) // 2
            rects[key] = (u, top, u + eu, top + ev) if down else (top, u, top + ev, u + eu)
            u += eu + across
        v += depth + along
    return _shift(rects, origin)


def hub(
    center: str,
    groups: dict[str, list[str]],
    boxes: dict[str, Box],
    gap: tuple[int, int] = GAP,
    origin: tuple[int, int] = (MARGIN, MARGIN),
) -> dict[str, Rect]:
    """``center`` with each group on its side: ``above`` and ``below`` as rows, ``left`` and ``right`` as columns.

    ``gap[0]`` separates neighbours in a group, ``gap[1]`` a group from the centre.
    """
    unknown = sorted(set(groups) - set(SIDES))
    if unknown:
        raise ValueError(f"hub groups are {', '.join(SIDES)}, not {', '.join(unknown)}")
    _unique([center, *(k for side in SIDES for k in groups.get(side, []))])
    near, far = gap
    middle = boxes[center]
    rects: dict[str, Rect] = {center: (0, 0, middle.width, middle.height)}
    for side in ("left", "right"):
        keys = groups.get(side, [])
        top = (middle.height - sum(boxes[k].height for k in keys) - near * (len(keys) - 1)) // 2
        for key in keys:
            box = boxes[key]
            left = -far - box.width if side == "left" else middle.width + far
            rects[key] = (left, top, left + box.width, top + box.height)
            top += box.height + near
    # Rows go beyond the side columns, which may be taller than the centre.
    ceiling = min(r[1] for r in rects.values()) - far
    floor = max(r[3] for r in rects.values()) + far
    for side in ("above", "below"):
        keys = groups.get(side, [])
        left = (middle.width - sum(boxes[k].width for k in keys) - near * (len(keys) - 1)) // 2
        for key in keys:
            box = boxes[key]
            top = ceiling - box.height if side == "above" else floor
            rects[key] = (left, top, left + box.width, top + box.height)
            left += box.width + near
    return _shift(rects, origin)


def contain(
    owner: str, children: list[str], boxes: dict[str, Box], padding: int = 20, origin: tuple[int, int] = (0, 0)
) -> dict[str, Rect]:
    """``children`` in a grid inside ``owner`` (below its name compartment), the owner grown to fit, never shrunk."""
    _unique([owner, *children])
    box = boxes[owner]
    columns = math.ceil(math.sqrt(len(children))) if children else 1
    grid = [children[i : i + columns] for i in range(0, len(children), columns)]
    widths = [max(boxes[row[c]].width for row in grid if c < len(row)) for c in range(columns)] if children else [0]
    heights = [max(boxes[k].height for k in row) for row in grid]
    grid_w = sum(widths) + SPACING * (columns - 1)
    grid_h = sum(heights) + SPACING * (len(heights) - 1)
    width = max(box.width, grid_w + 2 * padding) if children else box.width
    height = max(box.height, NAME_H + grid_h + padding) if children else box.height
    x0, y0 = origin
    rects: dict[str, Rect] = {owner: (x0, y0, x0 + width, y0 + height)}
    top = y0 + NAME_H
    for row, row_h in zip(grid, heights):
        left = x0 + (width - grid_w) // 2
        for column, key in enumerate(row):
            child = boxes[key]
            rects[key] = (left, top, left + child.width, top + child.height)
            left += widths[column] + SPACING
        top += row_h + SPACING
    return rects


def _acyclic(keys: list[str], edges: Iterable[Edge]) -> dict[str, list[str]]:
    """Successors of each key with cycles broken: a depth-first search in key order drops its back edges."""
    successors: dict[str, set[str]] = {k: set() for k in keys}
    for edge in edges:
        if edge.source in successors and edge.target in successors and edge.source != edge.target:
            successors[edge.source].add(edge.target)
    kept: dict[str, list[str]] = {k: [] for k in keys}
    state: dict[str, str] = {}
    for root in keys:
        if root in state:
            continue
        state[root] = "open"
        stack = [(root, iter(sorted(successors[root])))]
        while stack:
            node, pending = stack[-1]
            nxt = next(pending, None)
            if nxt is None:
                state[node] = "done"
                stack.pop()
            elif state.get(nxt) != "open":
                kept[node].append(nxt)
                if nxt not in state:
                    state[nxt] = "open"
                    stack.append((nxt, iter(sorted(successors[nxt]))))
    return kept


def _rank(keys: list[str], kept: dict[str, list[str]]) -> dict[str, int]:
    """Longest-path layering: a key sits one layer below its lowest predecessor."""
    predecessors = {k: 0 for k in keys}
    for targets in kept.values():
        for target in targets:
            predecessors[target] += 1
    layer = {k: 0 for k in keys}
    ready = sorted(k for k in keys if predecessors[k] == 0)
    while ready:
        node = ready.pop(0)
        for target in kept[node]:
            layer[target] = max(layer[target], layer[node] + 1)
            predecessors[target] -= 1
            if predecessors[target] == 0:
                ready.append(target)
        ready.sort()
    return layer


def _order(rows: list[list[str]], neighbours: dict[str, list[str]], sweep: range) -> None:
    """Reorder each row in ``sweep`` by the mean place of its neighbours (centred positions, ties by key)."""
    place: dict[str, float] = {}
    for row in rows:
        for index, key in enumerate(row):
            place[key] = index - (len(row) - 1) / 2
    for i in sweep:
        row = rows[i]

        def barycentre(key: str) -> float:
            near = [place[n] for n in neighbours[key] if n in place]
            return sum(near) / len(near) if near else place[key]

        row.sort(key=lambda k: (barycentre(k), k))
        for index, key in enumerate(row):
            place[key] = index - (len(row) - 1) / 2


def suggest(
    boxes: dict[str, Box],
    edges: Iterable[Edge],
    gap: tuple[int, int] = GAP,
    origin: tuple[int, int] = (MARGIN, MARGIN),
    focus: str | None = None,
) -> dict[str, Rect]:
    """A layered layout in edge direction: sources above targets, unconnected boxes in a last row.

    ``focus``, the box that matters most, is moved to the middle of its layer (spec: important element central).
    """
    keys = sorted(boxes)
    kept = _acyclic(keys, edges)
    linked = {k for k, targets in kept.items() if targets} | {t for targets in kept.values() for t in targets}
    layer = _rank(keys, kept)
    depth = max((layer[k] for k in linked), default=-1) + 1
    rows: list[list[str]] = [[] for _ in range(depth)]
    for key in keys:
        if key in linked:
            rows[layer[key]].append(key)
    upper = {k: [] for k in keys}
    for source, targets in kept.items():
        for target in targets:
            upper[target].append(source)
    # Barycentre sweeps, downwards by predecessors then upwards by successors, ending downwards.
    for _ in range(3):
        _order(rows, upper, range(1, len(rows)))
        _order(rows, kept, range(len(rows) - 2, -1, -1))
    _order(rows, upper, range(1, len(rows)))
    alone = [k for k in keys if k not in linked]
    if focus is not None:
        if focus not in boxes:
            raise ValueError(f"focus {focus!r} is not laid out")
        row = next(r for r in [*rows, alone] if focus in r)
        row.remove(focus)
        row.insert(len(row) // 2, focus)
    return layers([*rows, alone], boxes, gap, "down", origin)


def fits(rects: dict[str, Rect], page: tuple[int, int] = PAGE, margin: int = MARGIN) -> bool:
    """Whether every rectangle lies on the page, ``margin`` clear of each edge."""
    width, height = page
    return all(
        r[0] >= margin and r[1] >= margin and r[2] <= width - margin and r[3] <= height - margin for r in rects.values()
    )


def split_suggestion(
    rects: dict[str, Rect], edges: Iterable[Edge], page: tuple[int, int] = PAGE, margin: int = MARGIN
) -> list[list[str]]:
    """Groups of keys, each fitting a page when laid out with ``suggest``; greedy, keeping connected keys together.

    A group grows by the key with most edges into it (ties by key) while the group still fits; a key too big for a
    page alone gets a group of its own.
    """
    boxes = {k: Box(k, r[2] - r[0], r[3] - r[1]) for k, r in rects.items()}
    edges = [e for e in edges if e.source in boxes and e.target in boxes and e.source != e.target]
    links: dict[str, dict[str, int]] = {k: {} for k in boxes}
    for edge in edges:
        links[edge.source][edge.target] = links[edge.source].get(edge.target, 0) + 1
        links[edge.target][edge.source] = links[edge.target].get(edge.source, 0) + 1
    left = sorted(boxes)
    groups: list[list[str]] = []
    while left:
        group = [left.pop(0)]
        while left:
            best = min(left, key=lambda k: (-sum(links[k].get(g, 0) for g in group), k))
            trial = {k: boxes[k] for k in (*group, best)}
            inside = [e for e in edges if e.source in trial and e.target in trial]
            if not fits(suggest(trial, inside, origin=(margin, margin)), page, margin):
                break
            group.append(best)
            left.remove(best)
        groups.append(group)
    return groups
