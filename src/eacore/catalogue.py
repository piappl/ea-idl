"""Stereotype catalogue: what a profile defines, as data. Pure models and YAML; no repository access."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TagDef(_Model):
    name: str
    type: str = ""
    default: str = ""
    values: list[str] = Field(default_factory=list)
    description: str = ""
    stereotypes: list[str] = Field(default_factory=list)


class Constraint(_Model):
    role: str
    target: str


class StereotypeDef(_Model):
    name: str
    applies_to: list[str] = Field(default_factory=list)
    abstract: bool = False
    generalizes: list[str] = Field(default_factory=list)
    tags: list[TagDef] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)
    style: dict[str, str | int] = Field(default_factory=dict)
    notes: str = ""
    #: Number of elements an inferred entry was learned from.
    inferred_count: int | None = None


class Relationship(_Model):
    metaclass: str
    target: str


class DiagramDef(_Model):
    name: str
    base: str = ""
    id: str = ""
    alias: str = ""
    toolbox: str = ""


class Toolbox(_Model):
    name: str
    items: list[str] = Field(default_factory=list)


class Source(_Model):
    kind: Literal["mdg", "yaml", "inferred", "eaidl"]
    file: str = ""
    version: str = ""
    errata: list[str] = Field(default_factory=list)


class Catalogue(_Model):
    profile: str
    source: Source
    stereotypes: list[StereotypeDef] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    diagrams: list[DiagramDef] = Field(default_factory=list)
    toolboxes: list[Toolbox] = Field(default_factory=list)

    @classmethod
    def load_yaml(cls, path: str | Path) -> Catalogue:
        with open(path, encoding="utf-8") as f:
            return cls.model_validate(yaml.safe_load(f))

    def save_yaml(self, path: str | Path) -> None:
        save_yaml_all([self], path)


def load_yaml_all(path: str | Path) -> list[Catalogue]:
    """Catalogues in a YAML file holding one catalogue or a list of them."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [Catalogue.model_validate(item) for item in (data if isinstance(data, list) else [data])]


def save_yaml_all(catalogues: Iterable[Catalogue], path: str | Path) -> None:
    """Write one catalogue as a mapping, several as a list (``load_yaml_all`` reads both)."""
    data = [cat.model_dump(exclude_defaults=True) for cat in catalogues]
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data[0] if len(data) == 1 else data, f, sort_keys=False, allow_unicode=True)


class AmbiguousStereotype(LookupError):
    def __init__(self, name: str, candidates: list[str]) -> None:
        super().__init__(f"stereotype {name!r} is ambiguous: {', '.join(candidates)}")
        self.name = name
        self.candidates = candidates


@dataclass(frozen=True)
class ResolvedStereotype:
    fqname: str
    definition: StereotypeDef
    source: Source
    #: Own metaclasses, else those of the nearest ancestor that has any.
    applies_to: list[str]
    #: Own tags first, then ancestors' nearest first; the first definition of a name wins.
    tags: list[TagDef]
    #: Own and all ancestors', de-duplicated, order kept.
    constraints: list[Constraint]


class CatalogueSet:
    def __init__(self, catalogues: Iterable[Catalogue] = ()) -> None:
        self.catalogues: list[Catalogue] = list(catalogues)
        # fqname -> (definition, source); earlier catalogues win, so callers order by precedence.
        self._entries: dict[str, tuple[StereotypeDef, Source]] = {}
        for cat in self.catalogues:
            for definition in cat.stereotypes:
                self._entries.setdefault(f"{cat.profile}::{definition.name}", (definition, cat.source))

    def fqnames(self) -> list[str]:
        return sorted(self._entries)

    def lookup(self, name: str) -> str | None:
        """Fully qualified name for ``Profile::Name`` or a bare name; None if unknown."""
        if "::" in name:
            return name if name in self._entries else None
        found = sorted(fq for fq in self._entries if fq.rpartition("::")[2] == name)
        if len(found) > 1:
            raise AmbiguousStereotype(name, found)
        return found[0] if found else None

    def stereotype(self, name: str) -> StereotypeDef | None:
        fq = self.lookup(name)
        return self._entries[fq][0] if fq else None

    def origin(self, name: str) -> Source | None:
        fq = self.lookup(name)
        return self._entries[fq][1] if fq else None

    def _ancestor(self, name: str, profile: str) -> str | None:
        """A ``generalizes`` entry: qualified, or bare meaning the same profile first, then any."""
        if "::" not in name and f"{profile}::{name}" in self._entries:
            return f"{profile}::{name}"
        return self.lookup(name)

    def resolved(self, name: str) -> ResolvedStereotype | None:
        fq = self.lookup(name)
        if fq is None:
            return None
        definition, source = self._entries[fq]
        # Depth first, nearest first; the visited set guards against cycles.
        chain: list[StereotypeDef] = []
        seen: set[str] = set()

        def walk(current: str) -> None:
            if current in seen:
                return
            seen.add(current)
            entry = self._entries[current][0]
            chain.append(entry)
            for parent in entry.generalizes:
                ancestor = self._ancestor(parent, current.rpartition("::")[0])
                if ancestor:
                    walk(ancestor)

        walk(fq)
        tags: dict[str, TagDef] = {}
        constraints: list[Constraint] = []
        for entry in chain:
            for tag in entry.tags:
                tags.setdefault(tag.name, tag)
            constraints.extend(c for c in entry.constraints if c not in constraints)
        applies_to = next((entry.applies_to for entry in chain if entry.applies_to), [])
        return ResolvedStereotype(fq, definition, source, list(applies_to), list(tags.values()), constraints)
