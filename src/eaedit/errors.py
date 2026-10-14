"""Exceptions and warnings raised by eaedit."""

from __future__ import annotations

from dataclasses import dataclass


class EaeditError(Exception):
    """Base class for every eaedit failure."""


class NotFoundError(EaeditError, LookupError):
    pass


class AmbiguousNameError(EaeditError, LookupError):
    def __init__(self, name: str, candidates: list[str]) -> None:
        self.name = name
        self.candidates = sorted(candidates)
        super().__init__(f"{name!r} is ambiguous: {', '.join(self.candidates)}")


class ScopeError(EaeditError):
    """A change falls outside the session's focus."""


class InvalidOperationError(EaeditError, ValueError):
    pass


class CommitRefusedError(EaeditError):
    def __init__(self, issues: list) -> None:
        self.issues = issues
        super().__init__(f"commit refused: {len(issues)} integrity error(s)")


@dataclass(frozen=True)
class EditWarning:
    code: str
    message: str
    target: str | None = None
    rule_source: str | None = None

    def __str__(self) -> str:
        text = f"{self.code}: {self.message}"
        if self.target:
            text += f" [{self.target}]"
        if self.rule_source:
            text += f" ({self.rule_source})"
        return text
