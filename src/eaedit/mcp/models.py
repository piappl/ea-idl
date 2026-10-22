"""Models: the workspaces the server has open, by name, and which one a call without ``model`` goes to.

Each open model is its own :class:`Workspace` (catalogues, IDL configs, focus, session and working file). Only the
author and the timezone are shared: they describe the user, not the model. A model opened at runtime keeps its
working file in ``<model dir>/eaedit-out-<file stem>``, unless the file was open before during this run, in which
case it gets the output directory it had then, so its saved edits are found again.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from pathlib import Path

from eaedit.errors import EaeditError
from eaedit.mcp.workspace import Config, Workspace
from eaedit.scope import POLICIES


class Models:
    def __init__(self, author: str | None = None, timezone: str | None = None) -> None:
        self.author = author
        self.timezone = timezone
        self.default: str | None = None
        self._open: dict[str, Workspace] = {}
        #: The output directory each model file last had in this run (by resolved path).
        self._out_dirs: dict[Path, Path] = {}

    @classmethod
    def of(cls, workspace: Workspace) -> Models:
        """A registry holding just ``workspace``, as its default."""
        models = cls(workspace.config.author, workspace.config.timezone)
        models._register(workspace, None, default=True)
        return models

    def names(self) -> list[str]:
        return list(self._open)

    def add(self, config: Config, name: str | None = None, default: bool = False) -> str:
        """Register a model configured in full by the caller (the startup model); nothing is loaded yet."""
        return self._register(Workspace(config), name, default)

    def open(
        self,
        path: str | Path,
        name: str | None = None,
        catalogues: Iterable[str] = (),
        idl_configs: Iterable[str] = (),
        focus: Iterable[str] = (),
        policy: str = "connected",
        out: str | None = None,
        read_only: bool = False,
        default: bool = False,
    ) -> str:
        """Open a model file and load it at once, so a bad file or catalogue fails here and registers nothing.

        A relative ``path`` is under the default model's folder (else the working directory); relative catalogue
        and IDL config paths are under the opened model's folder.
        """
        model = Path(path)
        if not model.is_absolute() and self.default is not None:
            model = self._open[self.default].config.model.parent / model
        if not model.is_file():
            raise EaeditError(f"{model} is not a file")
        if policy not in POLICIES:
            raise EaeditError(f"policy {policy!r} is not one of {', '.join(POLICIES)}")
        here = model.parent
        out_dir = Path(out) if out else self._out_dirs.get(model.resolve(), here / f"eaedit-out-{model.stem}")
        if not out_dir.is_absolute():
            out_dir = here / out_dir
        config = Config(
            model,
            catalogues=[_under(here, p) for p in catalogues],
            idl_configs=[_under(here, p) for p in idl_configs],
            author=self.author,
            timezone=self.timezone,
            focus=list(focus),
            policy=policy,
            out_dir=out_dir,
            read_only=read_only,
        )
        workspace = Workspace(config)
        self._check(workspace, name or model.stem)
        try:
            workspace.snapshot()
        except BaseException:
            workspace.close()
            raise
        return self._register(workspace, name, default)

    def get(self, name: str | None) -> Workspace:
        """The workspace called ``name``; ``None`` is the default model."""
        if not self._open:
            raise EaeditError("no model is open; call open_model")
        if name is None:
            if self.default is None:
                raise EaeditError(f"no default model; pass model= one of: {', '.join(self._open)}")
            return self._open[self.default]
        if name in self._open:
            return self._open[name]
        near = difflib.get_close_matches(name, self._open, n=3, cutoff=0.5)
        near += [n for n in difflib.get_close_matches(Path(name).stem, self._open, n=3, cutoff=0.5) if n not in near]
        hint = f"; did you mean {', '.join(near)}?" if near else ""
        raise EaeditError(f"no open model {name!r}; open models: {', '.join(self._open)}{hint}")

    def close(self, name: str) -> int:
        """Close a model; returns how many staged operations its working file keeps for a later resume."""
        workspace = self.get(name)
        workspace.close()
        del self._open[name]
        if self.default == name:
            self.default = None
        if workspace.config.read_only or not workspace.working_file.is_file():
            return 0
        try:
            return len(workspace.saved_ops())
        except EaeditError:
            return 0

    def _check(self, workspace: Workspace, name: str) -> None:
        config = workspace.config
        if name in self._open:
            raise EaeditError(f"a model named {name!r} is already open; give another name")
        for other_name, other in self._open.items():
            if other.config.model.resolve() == config.model.resolve():
                raise EaeditError(f"{config.model} is already open as {other_name!r}")
            if (
                not config.read_only
                and not other.config.read_only
                and other.config.out_dir.resolve() == config.out_dir.resolve()
            ):
                raise EaeditError(f"out {config.out_dir} is used by {other_name!r}; give another out")

    def _register(self, workspace: Workspace, name: str | None, default: bool) -> str:
        name = name or workspace.config.model.stem
        self._check(workspace, name)
        self._open[name] = workspace
        if not workspace.config.read_only:
            self._out_dirs[workspace.config.model.resolve()] = workspace.config.out_dir
        if default or self.default is None:
            self.default = name
        return name


def _under(folder: Path, path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else folder / path
