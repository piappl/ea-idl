"""eacore is the bottom layer: it must not import eaidl or eaedit."""

import ast
from pathlib import Path

EACORE = Path(__file__).resolve().parents[2] / "src" / "eacore"
FORBIDDEN = ("eaidl", "eaedit")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_eacore_does_not_import_upper_layers():
    offenders = [
        f"{path.relative_to(EACORE)}: {name}"
        for path in EACORE.rglob("*.py")
        for name in _imported_modules(path)
        if name.split(".")[0] in FORBIDDEN
    ]
    assert offenders == []
