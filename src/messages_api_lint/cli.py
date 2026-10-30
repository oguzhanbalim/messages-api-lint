"""Command line entry point."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from collections.abc import Iterator, Sequence
from pathlib import Path

from . import __version__
from .catalog import RULES, RULES_SOURCE, RULES_WRITTEN
from .python_engine import PythonLinter
from .rules import Finding
from .ts_engine import TypeScriptLinter

SEVERITIES = ("info", "warning", "error")
EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2
TS_SUFFIXES = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".tox"}
IGNORE_RE = re.compile(r"messages-api-lint:\s*ignore(?:\[([A-Z0-9,\s]+)\])?")
STALE_AFTER_DAYS = 180


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="messages-api-lint",
        description="Find stale Claude Messages API usage in Python and TypeScript.",
        epilog=f"Rules written {RULES_WRITTEN} from: {RULES_SOURCE}.",
    )
    parser.add_argument("paths", nargs="*", type=Path, help="files or directories")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--assume-model", help="model to judge against when a call's model cannot be resolved"
    )
    parser.add_argument("--select", default="", help="comma-separated rule IDs to run")
    parser.add_argument("--ignore", default="", help="comma-separated rule IDs to skip")
    parser.add_argument(
        "--fail-on",
        choices=(*SEVERITIES, "never"),
        default="error",
        help="lowest severity that makes the exit code 1 (default: error)",
    )
    parser.add_argument(
        "--list-rules", action="store_true", help="print rules with their citations and exit"
    )
    parser.add_argument(
        "--check-citations",
        type=Path,
        metavar="SKILL_DIR",
        help="check that every cited section still exists in a copy of the reference",
    )
    parser.add_argument(
        "--version", action="version", version=f"{__version__} (rules written {RULES_WRITTEN})"
    )
    return parser


def iter_files(paths: Sequence[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_file():
            yield path
            continue
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file() or SKIP_DIRS & set(candidate.relative_to(path).parts):
                continue
            if candidate.suffix == ".py" or candidate.suffix in TS_SUFFIXES:
                yield candidate


def suppressed(finding: Finding, lines: list[str]) -> bool:
    if not 0 < finding.line <= len(lines):
        return False
    match = IGNORE_RE.search(lines[finding.line - 1])
    if not match:
        return False
    return match.group(1) is None or finding.rule_id in re.split(r"[,\s]+", match.group(1))


def lint_file(path: Path, assume_model: str | None) -> list[Finding]:
    source = path.read_text(encoding="utf-8", errors="replace")
    linter = PythonLinter if path.suffix == ".py" else TypeScriptLinter
    findings = linter(str(path), source, assume_model).run()
    lines = source.splitlines()
    kept = [f for f in findings if not suppressed(f, lines)]
    # A module-level dict spread into a call in a function is visited from both places.
    unique = {(f.line, f.rule_id, f.message): f for f in kept}
    return [unique[key] for key in sorted(unique)]


def check_citations(root: Path) -> int:
    """Each citation is a heading in a reference file. Report the ones that no longer exist."""
    missing = 0
    checked = 0
    for rule in RULES.values():
        for citation in rule.citations:
            checked += 1
            path = root / citation.file
            headings: set[str] = set()
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("#"):
                        headings.add(line.lstrip("#").strip())
            if citation.section not in headings:
                missing += 1
                print(f"{rule.id}: not found: {citation}")
    print(f"{checked - missing} of {checked} citations found in {root}")
    return EXIT_FINDINGS if missing else EXIT_OK


def print_rules() -> None:
    print(f"Rules written {RULES_WRITTEN} from: {RULES_SOURCE}")
    for rule in RULES.values():
        print(f"{rule.id}  {rule.title}")
        for citation in rule.citations:
            print(f"       {citation}")


def rules_age_note(today: dt.date | None = None) -> str | None:
    today = today or dt.date.today()
    age = (today - dt.date.fromisoformat(RULES_WRITTEN)).days
    if age > STALE_AFTER_DAYS:
        return f"note: these rules are {age} days old (written {RULES_WRITTEN}); the API changes"
    return None


def _ids(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_rules:
        print_rules()
        return EXIT_OK
    if args.check_citations:
        return check_citations(args.check_citations)
    if not args.paths:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    select, ignore = _ids(args.select), _ids(args.ignore)
    unknown = (select | ignore) - set(RULES)
    if unknown:
        print(f"unknown rule IDs: {', '.join(sorted(unknown))}", file=sys.stderr)
        return EXIT_USAGE
    for path in args.paths:
        if not path.exists():
            print(f"{path}: no such file or directory", file=sys.stderr)
            return EXIT_USAGE

    findings: list[Finding] = []
    file_count = 0
    for path in iter_files(args.paths):
        file_count += 1
        try:
            findings.extend(lint_file(path, args.assume_model))
        except SyntaxError as exc:
            print(f"{path}: skipped, invalid Python: {exc.msg}", file=sys.stderr)
    findings = [
        f for f in findings if (not select or f.rule_id in select) and f.rule_id not in ignore
    ]

    note = rules_age_note()
    if note:
        print(note, file=sys.stderr)

    counts = Counter(f.severity for f in findings)
    if args.format == "json":
        payload = {
            "version": 1,
            "rules_written": RULES_WRITTEN,
            "rules_source": RULES_SOURCE,
            "files": file_count,
            "summary": dict(counts),
            "findings": [f.to_dict() for f in findings],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for finding in findings:
            tag = " (regex)" if finding.engine == "regex" else ""
            print(
                f"{finding.path}:{finding.line}: {finding.rule_id} {finding.severity}: "
                f"{finding.message}{tag}"
            )
        summary = ", ".join(f"{counts[s]} {s}" for s in reversed(SEVERITIES))
        print(f"{file_count} files: {summary} (rules written {RULES_WRITTEN})")

    if args.fail_on == "never":
        return EXIT_OK
    threshold = SEVERITIES.index(args.fail_on)
    failed = any(SEVERITIES.index(f.severity) >= threshold for f in findings)
    return EXIT_FINDINGS if failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
