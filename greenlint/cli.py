"""The command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .base import BASELINE_FILENAME, CONFIG_FILENAME, Finding
from .baselines import apply_baseline, load_baseline, write_baseline
from .config import load_config
from .discovery import scan
from .rules import RULES

# ------------------------------------------------------------------- cli ---


def _build_parser() -> argparse.ArgumentParser:
    """The command-line surface: every flag greenlint accepts, and its help."""
    p = argparse.ArgumentParser(
        prog="greenlint",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="files or directories to scan (default: the current directory)",
    )
    p.add_argument(
        "--list-rules",
        action="store_true",
        help="print every rule with its energy rationale, then exit",
    )
    p.add_argument(
        "--format",
        choices=["text", "json", "github"],
        default="text",
        help="text for humans, json for tooling, github for workflow annotations",
    )
    p.add_argument("--fail-on-findings", action="store_true", help="exit 1 when anything is found; the CI gate")
    p.add_argument("--config", help=f"path to config (default: ./{CONFIG_FILENAME} if present)")
    p.add_argument(
        "--exclude",
        action="append",
        metavar="GLOB",
        # Same globs and same matching as `ignore` in the config, which is the
        # point: a caller that knows what to skip — an editor with its own
        # exclude list, a CI job scanning one subtree — should say so in the
        # vocabulary the project already uses, not a second one.
        help="skip paths matching this glob; repeatable, added to `ignore` from the config",
    )
    p.add_argument(
        "--baseline",
        metavar="FILE",
        help=f"accept the findings recorded in FILE (default: ./{BASELINE_FILENAME} if present)",
    )
    p.add_argument(
        "--write-baseline",
        nargs="?",
        const=BASELINE_FILENAME,
        metavar="FILE",
        help="record every current finding as accepted and exit",
    )
    return p


def _print_rules() -> None:
    """`--list-rules`: every rule, with the language tags it targets."""
    for r in RULES:
        print(f"{r['id']} [{r['severity']:6s}] ({', '.join(sorted(r['langs']))}): {r['message']}")  # noqa: T201 — the tool's output


def _print_github(findings: list[Finding]) -> None:
    """`--format github`: one workflow annotation per finding."""
    # https://docs.github.com/actions/using-workflows/workflow-commands-for-github-actions#setting-a-notice-message
    level = {"high": "error", "medium": "warning", "low": "notice"}
    for f in findings:
        print(  # noqa: T201 — the tool's output
            f"::{level[f['severity']]} file={f['file']},line={f['line']},"
            f"title=greenlint {f['rule']}::{f['message']} — {f['suggestion']}"
        )


def _print_text(findings: list[Finding], accepted: int, baseline_path: Path) -> None:
    """`--format text`: the human report, and the count a reader looks for."""
    for f in findings:
        print(f"{f['file']}:{f['line']}: [{f['rule']}/{f['severity']}] {f['message']}")  # noqa: T201 — the tool's output
        print(f"    ↳ {f['suggestion']}")  # noqa: T201 — the tool's output
        if f["co2e_estimate"]:
            print(f"    ~ {f['co2e_estimate']}")  # noqa: T201 — the tool's output
    accepted_note = f" ({accepted} accepted by {baseline_path})" if accepted else ""
    print(f"\ngreenlint: {len(findings)} finding(s){accepted_note}")  # noqa: T201 — the tool's output


def _resolve_baseline(explicit: str | None) -> Path:
    """The baseline file to honour, from `--baseline` or the default name.

    An explicit `--baseline` must exist; the default one is used when it happens
    to be there. A typo in a flag should be an error, not a silent no-op.
    """
    path = Path(explicit) if explicit else Path(BASELINE_FILENAME)
    if explicit and not path.is_file():
        raise SystemExit(f"greenlint: no such baseline: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    args = _build_parser().parse_args(argv)

    if args.list_rules:
        _print_rules()
        return 0

    config = load_config(args.config)
    if args.exclude:
        config["ignore"] = [*config["ignore"], *args.exclude]
    findings = scan(args.paths or ["."], config)

    if args.write_baseline:
        path = Path(args.write_baseline)
        count = write_baseline(path, findings, path.parent)
        print(f"greenlint: {count} finding(s) accepted in {path}")  # noqa: T201 — the tool's output
        return 0

    baseline_path = _resolve_baseline(args.baseline)
    before = len(findings)
    findings = apply_baseline(findings, load_baseline(baseline_path), baseline_path.parent)
    if args.format == "json":
        json.dump(findings, sys.stdout, indent=2)
    elif args.format == "github":
        _print_github(findings)
    else:
        _print_text(findings, before - len(findings), baseline_path)
    return 1 if findings and args.fail_on_findings else 0


if __name__ == "__main__":
    sys.exit(main())
