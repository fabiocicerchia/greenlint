#!/usr/bin/env python3
"""greenlint — static analysis for energy-wasteful patterns.

Rules are regex+context based and language-tagged; the rule set is the
product and grows over time. Every finding explains *why it wastes energy*
and what to do instead.

  greenlint src/
  greenlint --list-rules
  greenlint src/ --format json --fail-on-findings
"""

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

CONFIG_FILENAME = ".greenlint.toml"

RULES = [
    # id, languages, regex, message, suggestion, severity
    {
        "id": "GL001",
        "langs": {".py"},
        "severity": "medium",
        "pattern": re.compile(r"while\s+True\s*:\s*$(?!.*sleep)", re.M),
        "message": "busy loop without sleep",
        "suggestion": "poll with a backoff/sleep, or use an event-driven wait",
    },
    {
        "id": "GL002",
        "langs": {".py", ".js", ".ts"},
        "severity": "low",
        "pattern": re.compile(
            r"setInterval\s*\(\s*[^,]+,\s*([0-9]{1,2})\s*\)|time\.sleep\s*\(\s*0?\.0*[0-9]\s*\)"
        ),
        "message": "sub-100ms polling interval",
        "suggestion": "tight polling burns CPU; prefer push/webhooks or longer intervals",
    },
    {
        "id": "GL003",
        "langs": {".yml", ".yaml"},
        "severity": "high",
        "pattern": re.compile(r"cron:\s*['\"]?\*\s+\*\s+\*\s+\*\s+\*"),
        "message": "cron job scheduled every minute",
        "suggestion": "every-minute CI/cron jobs rarely need it; widen the schedule",
    },
    {
        "id": "GL004",
        "langs": {".yml", ".yaml"},
        "severity": "medium",
        "pattern": re.compile(r"fetch-depth:\s*0"),
        "message": "full git history clone in CI",
        "suggestion": "unshallow clones download and store far more than needed",
    },
    {
        "id": "GL005",
        "langs": {".sql", ".py", ".php", ".go", ".js", ".ts"},
        "severity": "medium",
        "pattern": re.compile(r"SELECT\s+\*\s+FROM", re.I),
        "message": "SELECT * query",
        "suggestion": "fetch only needed columns; less I/O, less network, less RAM",
    },
    {
        "id": "GL006",
        "langs": {".dockerfile", "Dockerfile"},
        "severity": "medium",
        "pattern": re.compile(r"^FROM\s+(?:ubuntu|debian)(?::|\s|$)(?!.*slim)", re.M | re.I),
        "message": "full-fat base image",
        "suggestion": "prefer -slim/alpine/distroless: smaller pulls, less storage, faster cold starts",
    },
    {
        "id": "GL007",
        "langs": {".py"},
        "severity": "low",
        "pattern": re.compile(r"\.append\s*\(.*\)\s*$\s+.*for\s+", re.M),
        "message": "append inside loop (possible O(n) rebuild pattern)",
        "suggestion": "consider comprehensions/generators; less allocation churn",
    },
    {
        "id": "GL008",
        "langs": {".tf"},
        "severity": "high",
        "pattern": re.compile(r'instance_type\s*=\s*"(?:m|c|r)[0-9]\.(?:8|12|16|24)xlarge"'),
        "message": "very large instance type hardcoded",
        "suggestion": "check utilization; rightsize or use autoscaling instead of peak-sizing",
    },
]


def _parse_simple_toml(text):
    """Parse the flat subset of TOML greenlint's config needs: `key = "value"`
    or `key = ["a", "b"]`, one per line, `#` comments. No tables, no nesting.
    """
    data = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        else:
            data[key] = value.strip("\"'")
    return data


def load_config(path=None):
    """Load `.greenlint.toml` (rule disable list + ignore globs). Missing
    file → no-op config. `path` overrides the default cwd lookup.
    """
    cfg_path = Path(path) if path else Path.cwd() / CONFIG_FILENAME
    if not cfg_path.is_file():
        return {"disable": set(), "ignore": []}
    data = _parse_simple_toml(cfg_path.read_text())
    return {"disable": set(data.get("disable", [])), "ignore": list(data.get("ignore", []))}


def applicable(rule, path):
    """Return True if the rule targets the file's language/extension."""
    if path.name == "Dockerfile" and "Dockerfile" in rule["langs"]:
        return True
    return path.suffix in rule["langs"]


def scan_file(path, disabled=frozenset()):
    """Yield findings for every enabled rule that matches the file's contents."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return
    for rule in RULES:
        if rule["id"] in disabled or not applicable(rule, path):
            continue
        for m in rule["pattern"].finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            yield {
                "rule": rule["id"],
                "severity": rule["severity"],
                "file": str(path),
                "line": line,
                "message": rule["message"],
                "suggestion": rule["suggestion"],
            }


def scan(paths, config=None):
    """Scan files/directories and return findings sorted by severity."""
    config = config or {"disable": set(), "ignore": []}
    findings = []
    for root in paths:
        p = Path(root)
        files = (
            [p]
            if p.is_file()
            else [
                f
                for f in p.rglob("*")
                if f.is_file() and ".git" not in f.parts and "node_modules" not in f.parts
            ]
        )
        for f in files:
            if any(fnmatch.fnmatch(str(f), pat) for pat in config["ignore"]):
                continue
            findings.extend(scan_file(f, config["disable"]))
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda x: (order[x["severity"]], x["file"], x["line"]))
    return findings


def main(argv=None):
    """CLI entry point; returns the process exit code."""
    p = argparse.ArgumentParser(
        prog="greenlint", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("paths", nargs="*", default=["."])
    p.add_argument("--list-rules", action="store_true")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--fail-on-findings", action="store_true")
    p.add_argument("--config", help=f"path to config (default: ./{CONFIG_FILENAME} if present)")
    args = p.parse_args(argv)

    if args.list_rules:
        for r in RULES:
            print(
                f"{r['id']} [{r['severity']:6s}] ({', '.join(sorted(r['langs']))}): {r['message']}"
            )
        return 0

    findings = scan(args.paths or ["."], load_config(args.config))
    if args.format == "json":
        json.dump(findings, sys.stdout, indent=2)
    else:
        for f in findings:
            print(f"{f['file']}:{f['line']}: [{f['rule']}/{f['severity']}] {f['message']}")
            print(f"    ↳ {f['suggestion']}")
        print(f"\ngreenlint: {len(findings)} finding(s)")
    return 1 if findings and args.fail_on_findings else 0


if __name__ == "__main__":
    sys.exit(main())
