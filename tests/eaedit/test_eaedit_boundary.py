"""eaedit and eaidl are sibling layers over eacore and must not import each other.

One exception: eaedit renders its diagrams with eaidl's native diagram renderer, from one module only.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

#: The only eaedit -> eaidl imports: the extractor and SVG renderer behind eaedit diagram previews, and IDL generation.
ALLOWED = {
    ("eaedit/diagrams/render.py", "eaidl.config"),
    ("eaedit/diagrams/render.py", "eaidl.native_diagram_extractor"),
    ("eaedit/diagrams/render.py", "eaidl.native_diagram_svg"),
    ("eaedit/mcp/idl.py", "eaidl.config"),
    ("eaedit/mcp/idl.py", "eaidl.generate"),
    ("eaedit/mcp/idl.py", "eaidl.load"),
    ("eaedit/mcp/idl.py", "eaidl.utils"),
}


def _imported_modules(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_eaedit_and_eaidl_do_not_import_each_other():
    offenders = []
    for package, forbidden in (("eaedit", "eaidl"), ("eaidl", "eaedit")):
        sources = list((SRC / package).rglob("*.py"))
        assert sources, f"no sources under {SRC / package}"
        offenders += [
            f"{path.relative_to(SRC)}: {name}"
            for path in sources
            for name in _imported_modules(path)
            if name.split(".")[0] == forbidden and (path.relative_to(SRC).as_posix(), name) not in ALLOWED
        ]
    assert offenders == []
