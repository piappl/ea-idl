"""Stereotype catalogue sources for eaedit."""

from pathlib import Path
from typing import Iterable

from eacore.backends.sql import load_file
from eacore.catalogue import Catalogue, CatalogueSet
from eacore.records import RecordSet

from eaedit.catalogue.infer import infer
from eaedit.catalogue.mdg import parse_mdg
from eaedit.catalogue.merge import merge


def load_catalogues(
    sources: Iterable[str | Path | Catalogue],
    rs: RecordSet | None = None,
    infer_from_model: bool = False,
) -> CatalogueSet:
    """Load every source and merge by precedence; ``infer_from_model`` adds what ``rs`` itself uses."""
    loaded: list[Catalogue] = []
    for source in sources:
        if isinstance(source, Catalogue):
            loaded.append(source)
            continue
        path = Path(source)
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            loaded.append(Catalogue.load_yaml(path))
        elif suffix == ".xml":
            loaded.extend(parse_mdg(path))
        elif suffix in (".qea", ".qeax"):
            model = load_file(path)
            model.meta["path"] = str(path)
            loaded.extend(infer(model))
        else:
            raise ValueError(f"unsupported catalogue source {str(source)!r}")
    if infer_from_model and rs is not None:
        loaded.extend(infer(rs))
    return merge(*loaded)
