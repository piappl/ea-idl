"""Change packages: a reviewable directory of what a session would change, and the way back in.

``export_changes`` writes the package without touching the model; ``apply_changes`` replays its change file into a
new session; ``commit_with_report`` commits and keeps the report.
"""

from __future__ import annotations

import re
import shutil
import tempfile
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
    session = workspace.require_session()
    out_dir = workspace.config.out_dir
    target = out_dir / _safe_name(name)
    if target.exists() and not overwrite:
        raise EaeditError(f"{target.name} already exists; pick another name or pass overwrite=True")
    # Everything is computed and written beside the target first, so a failure leaves an old package intact.
    preview = session.preview(render=False)
    stems = diagram_file_stems(session, preview.changes)
    diffs = _idl_diffs(session, workspace.config.idl_configs)
    separate = len(diffs) > 1  # one config: its diff is embedded in the report, and also written as idl.diff
    report = change_report(session, diagrams_dir="diagrams", idl_diffs=diffs or None, idl_files=separate)
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=out_dir))
    try:
        changefile.save(session, staging / CHANGES_FILE)
        (staging / "report.md").write_text(report, encoding="utf-8")
        (staging / "check.txt").write_text(_check_text(preview), encoding="utf-8")
        if stems:
            (staging / "diagrams").mkdir()
            for guid, stem in stems.items():
                (staging / "diagrams" / f"{stem}.svg").write_text(export_svg(session, guid), encoding="utf-8")
        for stem, text in diffs.items():
            (staging / ("idl-" + stem + ".diff" if separate else "idl.diff")).write_text(text + "\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def apply_changes(workspace: Workspace, path: Path) -> OpenResult:
    """Replay a change package (or a change file) into a new session; the caller previews and commits.

    All or nothing: if any operation fails, the session is discarded and the error names that operation.
    """
    path = Path(path)
    source = path / CHANGES_FILE if path.is_dir() else path
    if not source.is_file():
        raise EaeditError(f"no change file at {source}")
    ops = changefile.load(source)
    workspace.open_session()  # refuses when a session is open or a saved one exists
    try:
        for index, op in enumerate(ops, 1):
            try:
                changefile.replay(workspace.require_session(), [op])
            except Exception as exc:
                raise EaeditError(f"op {index} ({op.name}) of {source.name} failed: {exc}") from None
        workspace.save()
    except BaseException:
        workspace.discard()
        raise
    return OpenResult(f"replayed {len(ops)} of {len(ops)}", len(ops), len(ops))


def commit_with_report(workspace: Workspace) -> str:
    session = workspace.require_session()
    report = change_report(session, idl_diffs=_idl_diffs(session, workspace.config.idl_configs) or None)
    stamp = session.clock().strftime("%Y-%m-%dT%H-%M-%S")
    workspace.commit()
    try:
        reports = workspace.config.out_dir / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / f"{stamp}.md").write_text(report, encoding="utf-8")
    except OSError as exc:  # the model is already committed: hand the report back anyway
        report += f"\n(The report could not be written to the output directory: {exc})\n"
    return report
