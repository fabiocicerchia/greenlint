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
import ast
import fnmatch
import json
import re
import sys
from pathlib import Path

CONFIG_FILENAME = ".greenlint.toml"

# Rough, order-of-magnitude estimates per occurrence — not a measurement, a
# steer for which findings are worth fixing first. Based on typical marginal
# grid intensity (~400 gCO2e/kWh) and a plausible instance-hours-affected
# guess per pattern; wildly workload-dependent, treat as relative not exact.
CO2E_HINTS = {
    "GL001": "~10-100s gCO2e/day per idle instance (continuous busy-poll CPU)",
    "GL002": "~1-10s gCO2e/day per instance (elevated wake-up rate)",
    "GL003": "~1-5 gCO2e per unnecessary run x 1440 runs/day saved by widening",
    "GL004": "~1-3 gCO2e per full-history clone avoided",
    "GL005": "~0.1-1 gCO2e per query x call volume (excess I/O/network)",
    "GL006": "~5-20 gCO2e per pull avoided (smaller image, less transfer+storage)",
    "GL007": "~0.01-0.1 gCO2e per call (extra allocation/GC churn)",
    "GL008": "~100s-1000s gCO2e/day per oversized instance running idle",
}

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


def _finding(rule, path, line):
    return {
        "rule": rule["id"],
        "severity": rule["severity"],
        "file": str(path),
        "line": line,
        "message": rule["message"],
        "suggestion": rule["suggestion"],
        "co2e_estimate": CO2E_HINTS.get(rule["id"], ""),
    }


def _ast_busy_loop_findings(path, text):
    """AST-based replacement for GL001 on Python: the regex version flags
    `while True:` unless "sleep" appears *anywhere* in the file, which both
    misses loops whose sleep is in an unrelated function and flags loops that
    do sleep but happen to share a file with the word "sleep" elsewhere.
    Walking the loop body directly for a real sleep call fixes both.
    """
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return
    rule = next(r for r in RULES if r["id"] == "GL001")
    for node in ast.walk(tree):
        if not (isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True):
            continue
        sleeps = any(
            isinstance(n, ast.Call)
            and (
                (isinstance(n.func, ast.Attribute) and n.func.attr == "sleep")
                or (isinstance(n.func, ast.Name) and n.func.id == "sleep")
            )
            for body_node in node.body
            for n in ast.walk(body_node)
        )
        if not sleeps:
            yield _finding(rule, path, node.lineno)


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
    if path.suffix == ".py" and "GL001" not in disabled:
        yield from _ast_busy_loop_findings(path, text)
    for rule in RULES:
        if rule["id"] in disabled or rule["id"] == "GL001" or not applicable(rule, path):
            continue
        for m in rule["pattern"].finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            yield _finding(rule, path, line)


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
            if f["co2e_estimate"]:
                print(f"    ~ {f['co2e_estimate']}")
        print(f"\ngreenlint: {len(findings)} finding(s)")
    return 1 if findings and args.fail_on_findings else 0


if __name__ == "__main__":
    sys.exit(main())
