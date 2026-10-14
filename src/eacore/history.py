"""Versions of a repository file in git history."""

import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path


def _git(path: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=path.parent, check=True, capture_output=True).stdout


def git_versions(path: Path) -> list[tuple[str, str]]:
    """(sha, subject) of every commit that changed ``path``, oldest first."""
    out = _git(path, "log", "--reverse", "--format=%H%x09%s", "--", path.name).decode("utf-8")
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if line]


def extract_version(rev: str, path: Path, dest: Path) -> Path:
    """Write ``path`` as of ``rev`` to ``dest``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_git(path, "show", f"{rev}:./{path.name}"))
    return dest


STYLE_COLUMNS = (
    ("t_diagramobjects", "attr_objectstyle"),
    ("t_diagramlinks", "attr_style"),
    ("t_diagramlinks", "attr_geometry"),
    ("t_object", "attr_style"),
    ("t_object", "attr_styleex"),
    ("t_connector", "attr_styleex"),
    ("t_attribute", "attr_styleex"),
    ("t_diagram", "attr_styleex"),
    ("t_diagram", "attr_pdata"),
)


def run_history(path: Path, out: Path, template: Path | None = None) -> dict:
    """Diff and check every version of ``path`` in git; write per-commit diffs and a summary."""
    from eacore.backends.sql import load_file
    from eacore.diff import diff
    from eacore.embedded import parse_kv
    from eacore.integrity import check
    from eacore.report import render_text, to_json
    from eacore.verify import diff_apply, roundtrip

    versions = git_versions(path)
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {"file": path.name, "versions": [], "pairs": []}
    column_changes: Counter = Counter()
    style_keys: dict[str, set[str]] = {f"{t}.{c}": set() for t, c in STYLE_COLUMNS}
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        files = [extract_version(sha, path, tmp / f"{i:03d}.qea") for i, (sha, _) in enumerate(versions)]
        loaded = [load_file(f) for f in files]
        for index, ((sha, subject), rs, file) in enumerate(zip(versions, loaded, files)):
            issues = check(rs)
            ok = None
            if template is not None:
                source, rebuilt = roundtrip(file, template, tmp / f"rt{index:03d}")
                ok = rebuilt.same_records(source)
            errors = sum(i.severity == "error" for i in issues)
            summary["versions"].append(
                {"sha": sha, "subject": subject, "errors": errors, "warnings": len(issues) - errors, "roundtrip": ok}
            )
            for table, column in STYLE_COLUMNS:
                for record in rs.records(table):
                    style_keys[f"{table}.{column}"].update(parse_kv(record.values.get(column)).keys())
        for index in range(1, len(versions)):
            sha, subject = versions[index]
            changes = diff(loaded[index - 1], loaded[index])
            stem = out / f"{index:03d}_{sha[:8]}"
            header = f"# {sha[:8]} {subject}\n\n"
            stem.with_suffix(".txt").write_text(
                header + render_text(changes, loaded[index - 1], loaded[index]), encoding="utf-8"
            )
            stem.with_suffix(".json").write_text(to_json(changes), encoding="utf-8")
            expected, actual = diff_apply(files[index - 1], files[index], tmp / f"da{index:03d}")
            tables: dict[str, Counter] = {}
            for insert in changes.inserts:
                tables.setdefault(insert.record.table, Counter())["insert"] += 1
            for delete in changes.deletes:
                tables.setdefault(delete.table, Counter())["delete"] += 1
            for update in changes.updates:
                tables.setdefault(update.table, Counter())["update"] += 1
                column_changes.update(f"{update.table}.{column}" for column in update.changes)
            summary["pairs"].append(
                {
                    "sha": sha,
                    "subject": subject,
                    "changes": len(changes),
                    "diff_apply": actual.same_records(expected),
                    "tables": {t: dict(c) for t, c in sorted(tables.items())},
                }
            )
    summary["column_changes"] = dict(column_changes.most_common())
    summary["style_keys"] = {name: sorted(keys) for name, keys in style_keys.items()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.md").write_text(_summary_md(summary), encoding="utf-8")
    return summary


def _summary_md(summary: dict) -> str:
    lines = [
        f"# History of {summary['file']}",
        "",
        "## Versions",
        "",
        "| sha | subject | errors | warnings | round-trip |",
    ]
    lines.append("|---|---|---|---|---|")
    for v in summary["versions"]:
        lines.append(f"| {v['sha'][:8]} | {v['subject']} | {v['errors']} | {v['warnings']} | {v['roundtrip']} |")
    lines += [
        "",
        "## Changes per commit",
        "",
        "| sha | subject | changes | diff/apply | tables |",
        "|---|---|---|---|---|",
    ]
    for p in summary["pairs"]:
        tables = ", ".join(f"{t} {dict(c)}" for t, c in p["tables"].items())
        lines.append(f"| {p['sha'][:8]} | {p['subject']} | {p['changes']} | {p['diff_apply']} | {tables} |")
    lines += ["", "## Most changed columns", "", "| column | updates |", "|---|---|"]
    lines += [f"| {c} | {n} |" for c, n in list(summary["column_changes"].items())[:40]]
    lines += ["", "## Style keys seen", ""]
    lines += [f"- `{name}`: {', '.join(keys) or '-'}" for name, keys in summary["style_keys"].items()]
    return "\n".join(lines) + "\n"
