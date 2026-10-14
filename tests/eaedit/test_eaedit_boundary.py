"""eaedit and eaidl are sibling layers over eacore and must not import each other."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


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
            if name.split(".")[0] == forbidden
        ]
    assert offenders == []
