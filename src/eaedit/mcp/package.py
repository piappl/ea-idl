"""Change packages: a reviewable directory of what a session would change, and the way back in.

``export_changes`` writes the package without touching the model; ``apply_changes`` replays its change file into a
new session; ``commit_with_report`` commits and keeps the report.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from eaedit import changefile
from eaedit.diagrams.svg import export_svg
from eaedit.errors import EaeditError
from eaedit.mcp.idl import idl_diff
from eaedit.mcp.report import change_report, diagram_file_stems
from eaedit.mcp.workspace import OpenResult, Workspace

CHANGES_FILE = "changes.yaml"


def _safe_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip(".")
    if not safe:
        raise EaeditError("give the change package a name")
    return safe


def _check_text(preview) -> str:
    lines = [f"{i.severity} {i.rule}: {i.message}" for i in preview.new_issues]
    lines += [f"warning {w}" for w in preview.warnings]
    return "\n".join(lines) + "\n" if lines else "no new issues\n"


def _idl_diffs(session, configs: list[Path]) -> dict[str, str]:
    """Config stem -> diff text (a stem used twice gets a number)."""
    diffs: dict[str, str] = {}
    for path in configs:
        stem, count = path.stem, 1
        while stem in diffs:
            count += 1
            stem = f"{path.stem}-{count}"
        diffs[stem] = idl_diff(session, path).text()
    return diffs


def export_changes(workspace: Workspace, name: str, overwrite: bool = False) -> Path:
    session = workspace._require()
    target = workspace.config.out_dir / _safe_name(name)
    if target.exists():
        if not overwrite:
            raise EaeditError(f"{target.name} already exists; pick another name or pass overwrite=True")
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    preview = session.preview(render=False)
    stems = diagram_file_stems(session, preview.changes)
    diffs = _idl_diffs(session, workspace.config.idl_configs)
    separate = len(diffs) > 1  # one config: its diff is embedded in the report, and also written as idl.diff
    report = change_report(session, diagrams_dir="diagrams", idl_diffs=diffs or None, idl_files=separate)
    target.mkdir(parents=True)
    changefile.save(session, target / CHANGES_FILE)
    (target / "report.md").write_text(report, encoding="utf-8")
    (target / "check.txt").write_text(_check_text(preview), encoding="utf-8")
    if stems:
        (target / "diagrams").mkdir()
        for guid, stem in stems.items():
            (target / "diagrams" / f"{stem}.svg").write_text(export_svg(session, guid), encoding="utf-8")
    for stem, text in diffs.items():
        (target / ("idl-" + stem + ".diff" if separate else "idl.diff")).write_text(text + "\n", encoding="utf-8")
    return target


def apply_changes(workspace: Workspace, path: Path) -> OpenResult:
    path = Path(path)
    source = path / CHANGES_FILE if path.is_dir() else path
    if not source.is_file():
        raise EaeditError(f"no change file at {source}")
    ops = changefile.load(source)
    # Open first (refuses when a session is open), then park the ops as the working file and resume them.
    workspace.open_session()
    session = workspace.session
    try:
        for index, op in enumerate(ops, 1):
            try:
                changefile.replay(session, [op])
            except Exception as exc:
                workspace.discard()
                raise EaeditError(f"op {index} ({op.name}) of {source.name} failed: {exc}") from None
        workspace._save()
    except BaseException:
        if workspace.session is not None:
            workspace.discard()
        raise
    return OpenResult(f"replayed {len(ops)} of {len(ops)}", len(ops), len(ops))


def commit_with_report(workspace: Workspace) -> str:
    session = workspace._require()
    report = change_report(session, idl_diffs=_idl_diffs(session, workspace.config.idl_configs) or None)
    stamp = session.clock().strftime("%Y-%m-%dT%H-%M-%S")
    workspace.commit()
    reports = workspace.config.out_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{stamp}.md").write_text(report, encoding="utf-8")
    return report
