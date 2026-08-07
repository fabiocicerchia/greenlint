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

import tomllib

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
    "GL009": "~1-5 gCO2e per pull x pulls/day from avoidable recommended-package bloat",
    "GL010": "~1-5 gCO2e per pull x pulls/day from cached wheel files baked into the image",
    "GL011": "~0.01-0.1 gCO2e per unseen image loaded on page view",
    "GL012": "~0.01-0.1 gCO2e per extra round-trip x (N-1) avoidable queries",
    "GL013": "~10s-100s gCO2e/month per bucket left in hot storage indefinitely",
    "GL014": "~10s-100s gCO2e/day per unbounded container encouraging node over-provisioning",
    "GL015": "~1-5 gCO2e per pull x pulls/day from an outdated, less efficient runtime",
    "GL016": "~10s-100s gCO2e/day per instance (ARM/Graviton is ~3-4x more power-efficient than x86)",
    "GL017": "~1-10 gCO2e per view avoided by using MP4/WebP/AVIF instead of an animated GIF",
    "GL018": "~0.01-1 gCO2e per call x n (quadratic vs. linear compute growth)",
    "GL019": "~0.1-1 gCO2e per avoidable round-trip x (N-1) calls (network + remote CPU wake)",
    "GL020": "~0.001-0.01 gCO2e per call (string work done even when the log level is disabled)",
    "GL021": "~0.1-10 gCO2e per run x rows (10-100x more interpreter cycles than a vectorised op)",
    "GL022": "~0.05-0.5 gCO2e per avoidable open/read x (N-1) iterations",
    "GL023": "~0.01-1 gCO2e per call x n² vs n log n compute growth",
    "GL024": "~100s-1000s gCO2e/day per instance kept always-on instead of scaling down",
    "GL025": "~1-10 gCO2e/day per volume (marginally higher power draw per IOP than gp3)",
    "GL026": "~1-10 gCO2e/month per GB of logs retained indefinitely",
    "GL027": "~0.1-1 gCO2e per re-fetch a cache header would have avoided",
    "GL028": "~0.001-0.01 gCO2e per import (extra modules loaded/bound at startup)",
    "GL029": "~1-5 gCO2e per pull x pulls/day per avoidable extra image layer",
    "GL030": "~0.001-0.01 gCO2e per iteration (building/unpacking the unused tuple half)",
    "GL031": "~0.01-0.1 gCO2e per iteration (raising and unwinding on every pass)",
    "GL032": "~0.01-0.1 gCO2e per call (repeated allocator overhead per iteration)",
    "GL033": "~100s-1000s gCO2e/day per replica kept always-on instead of scaling down",
    "GL034": "~10s-100s gCO2e/day per unbounded service encouraging host over-provisioning",
    "GL035": "~0.001-0.05 gCO2e per call x sequence length (full enumeration vs. short-circuit)",
    "GL036": "~0.001-0.05 gCO2e per call x hash size (O(n) scan vs. O(1) lookup)",
    "GL037": "~0.001-0.05 gCO2e per call x collection size (two passes vs. one)",
    "GL038": "~0.001-0.01 gCO2e per render (extra allocation + defeated memoisation)",
}

RULES = [
    # id, languages, regex, message, suggestion, severity
    {
        "id": "GL001",
        "langs": {".py"},
        "severity": "medium",
        "pattern": re.compile(r"while\s+True\s*:\s*$(?!.*sleep)", re.MULTILINE),
        "message": "busy loop without sleep",
        "suggestion": "poll with a backoff/sleep, or use an event-driven wait",
    },
    {
        "id": "GL002",
        "langs": {
            ".py",
            ".js",
            ".ts",
            ".sh",
            ".go",
            ".rs",
            ".java",
            ".php",
            ".pl",
            ".c",
            ".h",
            ".cpp",
            ".cc",
            ".hpp",
            ".kt",
            ".swift",
            ".cs",
        },
        "severity": "low",
        "pattern": re.compile(
            r"setInterval\s*\(\s*[^,]+,\s*([0-9]{1,2})\s*\)"
            # `0.0x` only: `sleep(0.1)` is exactly 100ms, which this rule is
            # not about, and was being flagged by the older `0.0*[0-9]`.
            r"|time\.sleep\s*\(\s*0?\.0+[0-9]\s*\)"
            r"|sleep\s+0?\.0+[0-9]\b"  # bash
            r"|time\.Sleep\(\s*[0-9]{1,2}\s*\*\s*time\.Millisecond\s*\)"  # go
            r"|thread::sleep\(\s*Duration::from_millis\(\s*[0-9]{1,2}\s*\)\s*\)"  # rust
            r"|Thread\.sleep\(\s*[0-9]{1,2}\s*\)"  # java/kotlin/c#
            r"|usleep\(\s*[0-9]{1,5}\s*\)"  # php/perl/c/c++ (microseconds, <100ms)
            r"|\bdelay\(\s*[0-9]{1,2}\)"  # kotlin coroutines
            r"|Timer\.scheduledTimer\(withTimeInterval:\s*0?\.0+[0-9]"  # swift
        ),
        "message": "sub-100ms polling interval",
        "suggestion": "tight polling burns CPU; prefer push/webhooks or longer intervals",
    },
    {
        "id": "GL003",
        "langs": {".yml", ".yaml"},
        "severity": "high",
        "pattern": re.compile(r"(?:cron|schedule):\s*['\"]?\*\s+\*\s+\*\s+\*\s+\*"),
        "message": "cron job scheduled every minute",
        "suggestion": "every-minute CI/cron/Kubernetes CronJob schedules rarely need it; widen the schedule",
    },
    {
        "id": "GL004",
        "langs": {".yml", ".yaml"},
        "severity": "medium",
        "pattern": None,  # whole-file check; see _fetch_depth_findings
        "message": "full git history clone in CI",
        "suggestion": "unshallow clones download and store far more than needed",
    },
    {
        "id": "GL005",
        "langs": {
            ".sql",
            ".py",
            ".php",
            ".go",
            ".js",
            ".ts",
            ".rs",
            ".java",
            ".c",
            ".h",
            ".cpp",
            ".cc",
            ".hpp",
            ".pl",
            ".sh",
        },
        "severity": "medium",
        "pattern": re.compile(r"SELECT\s+\*\s+FROM", re.IGNORECASE),
        "message": "SELECT * query",
        "suggestion": "fetch only needed columns; less I/O, less network, less RAM",
    },
    {
        "id": "GL006",
        "langs": {".dockerfile", "Dockerfile"},
        "severity": "medium",
        "pattern": re.compile(
            r"^FROM\s+(?:ubuntu|debian)(?::|\s|$)(?!.*slim)", re.MULTILINE | re.IGNORECASE
        ),
        "message": "full-fat base image",
        "suggestion": "prefer -slim/alpine/distroless: smaller pulls, less storage, faster cold starts",
    },
    {
        "id": "GL007",
        "langs": {".py"},
        "severity": "low",
        "pattern": None,  # whole-file check; see _ast_quadratic_rebuild_findings
        "message": "quadratic rebuild in a loop (whole sequence copied each iteration)",
        "suggestion": "`x = x + [i]` / `x += [i]` on a list, or `s += t` on a string, copies everything accumulated so far on every pass — O(n^2) allocation. Use list.append() (amortised O(1)) or collect the parts and ''.join() them once",
    },
    {
        "id": "GL008",
        "langs": {".tf", ".tofu"},
        "severity": "high",
        "pattern": re.compile(r'instance_type\s*=\s*"(?:m|c|r)[0-9]\.(?:8|12|16|24)xlarge"'),
        "message": "very large instance type hardcoded",
        "suggestion": "check utilization; rightsize or use autoscaling instead of peak-sizing",
    },
    {
        "id": "GL009",
        "langs": {".dockerfile", "Dockerfile"},
        "severity": "low",
        "pattern": re.compile(
            r"apt-get\s+install(?!.*--no-install-recommends)[^\n]*", re.IGNORECASE
        ),
        "message": "apt-get install without --no-install-recommends",
        "suggestion": "recommended/suggested packages bloat the image; skip them to cut pull, transfer, and storage energy",
    },
    {
        "id": "GL010",
        "langs": {".dockerfile", "Dockerfile"},
        "severity": "low",
        "pattern": re.compile(r"pip3?\s+install(?!.*--no-cache-dir)[^\n]*", re.IGNORECASE),
        "message": "pip install without --no-cache-dir",
        "suggestion": "the wheel cache gets baked into the image layer; skip it to shrink pulls and storage",
    },
    {
        "id": "GL011",
        "langs": {".html"},
        "severity": "low",
        "pattern": re.compile(r"<img\b(?![^>]*\bloading=)[^>]*>", re.IGNORECASE),
        "message": "img tag missing lazy loading",
        "suggestion": 'loading="lazy" defers offscreen image loads; less bandwidth and render work up front',
    },
    {
        "id": "GL012",
        "langs": {".py"},
        "severity": "medium",
        "pattern": re.compile(r"for\s+\w+\s+in\s+[^:\n]+:\n[ \t]+\S*\.execute\(", re.MULTILINE),
        "message": "database query executed inside a loop (N+1 pattern)",
        "suggestion": "batch into one query (e.g. WHERE id IN (...)) instead of one round-trip per item; cuts DB CPU and network energy",
    },
    {
        "id": "GL013",
        "langs": {".tf", ".tofu"},
        "severity": "low",
        "pattern": None,  # whole-resource-block check; see _tf_s3_lifecycle_findings
        "message": "S3 bucket without a lifecycle policy",
        "suggestion": "stale objects sit in hot storage forever; add a lifecycle_rule (or aws_s3_bucket_lifecycle_configuration) to tier or expire old data",
    },
    {
        "id": "GL014",
        "langs": {".yml", ".yaml"},
        "severity": "medium",
        "pattern": None,  # whole-file check; see _k8s_resources_findings
        "message": "Kubernetes workload without CPU/memory requests or limits",
        "suggestion": "unbounded containers get scheduled without guardrails, encouraging over-provisioned, underutilised nodes; set resources.requests/limits to right-size",
    },
    {
        "id": "GL015",
        "langs": {".dockerfile", "Dockerfile"},
        "severity": "medium",
        "pattern": re.compile(
            r"^FROM\s+(?:python:2(?:\.\d+)?\b"
            r"|node:(?:6|8|10|12|14)(?:\.\d+)*(?:-\w+)?\b"
            r"|ubuntu:(?:14\.04|16\.04|18\.04)\b"
            r"|debian:(?:7|8|9|wheezy|jessie|stretch)\b"
            r"|centos:(?:6|7)\b)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "message": "base image pinned to an end-of-life runtime/OS version",
        "suggestion": "older runtimes lack the perf/efficiency work in newer releases and pull more security-patch layers over time; move to a current stable version",
    },
    {
        "id": "GL016",
        "langs": {".tf", ".tofu"},
        "severity": "low",
        "pattern": re.compile(
            r'instance_type\s*=\s*"(?:t2|t3|m4|m5|c4|c5|r4|r5)\.[a-z0-9]+"', re.IGNORECASE
        ),
        "message": "x86 instance family with an ARM/Graviton equivalent available",
        "suggestion": "ARM-based instances (t4g/m6g/c6g/r6g) deliver ~3-4x better performance-per-watt for compatible workloads",
    },
    {
        "id": "GL017",
        "langs": {".html", ".css"},
        "severity": "low",
        "pattern": re.compile(
            r"""(?:<img\b[^>]*\bsrc\s*=\s*["']|url\(\s*["']?)[^"'\)\s]+\.gif\b""", re.IGNORECASE
        ),
        "message": "GIF referenced for image/animation",
        "suggestion": "GIFs are an obsolete, inefficient animation format; MP4/WebP/AVIF (or SVG/CSS animation) give smaller files and less energy per view",
    },
    {
        "id": "GL018",
        "langs": {".py"},
        "severity": "low",
        "pattern": None,  # AST check; see _ast_nested_loop_findings
        "message": "nested loop iterating over the same collection (possible O(n²) pattern)",
        "suggestion": "a manual all-pairs scan over the same list costs O(n²); use a set/dict for membership tests or itertools.combinations instead",
    },
    {
        "id": "GL019",
        "langs": {".py"},
        "severity": "medium",
        "pattern": re.compile(
            r"for\s+\w+\s+in\s+[^:\n]+:\n[ \t]+(?:\w+\s*=\s*)?requests\.(?:get|post|put|patch|delete)\(",
            re.MULTILINE,
        ),
        "message": "HTTP request executed inside a loop (N+1-style network calls)",
        "suggestion": "batch the calls, reuse a requests.Session, or gather them concurrently instead of one request per iteration; cuts round-trips and idle-wait energy",
    },
    {
        "id": "GL020",
        "langs": {".py"},
        "severity": "low",
        "pattern": re.compile(
            r"""logging\.(?:debug|info)\(\s*(?:f['"]|['"][^'"]*['"]\s*\.\s*format\()"""
        ),
        "message": "logging call built eagerly with an f-string or .format()",
        "suggestion": "the interpolation runs even when the log level is disabled; use logging.debug('x=%s', x) for lazy formatting",
    },
    {
        "id": "GL021",
        "langs": {".py"},
        "severity": "medium",
        "pattern": re.compile(r"\.iterrows\(\)|\.apply\([^)]*axis\s*=\s*1"),
        "message": "row-wise pandas iteration (iterrows/apply(axis=1))",
        "suggestion": "row-wise pandas ops run one Python-level call per row; use vectorised column operations for 10-100x fewer CPU cycles",
    },
    {
        "id": "GL022",
        "langs": {".py"},
        "severity": "low",
        "pattern": re.compile(
            r"for\s+\w+\s+in\s+[^:\n]+:\n[ \t]+(?:\w+\s*=\s*)?(?:open\(|pd\.read_csv\(|pd\.read_json\()",
            re.MULTILINE,
        ),
        "message": "file opened/read inside a loop",
        "suggestion": "repeated opens/reads add a syscall and parse pass per iteration; load once outside the loop or read in chunks",
    },
    {
        "id": "GL023",
        "langs": {".py"},
        "severity": "medium",
        "pattern": None,  # AST check; see _ast_bubble_sort_findings
        "message": "nested loop with an element swap (manual O(n²) sort)",
        "suggestion": "built-in sorted()/list.sort() use Timsort (O(n log n), implemented in C); replace the manual swap-based sort",
    },
    {
        "id": "GL024",
        "langs": {".tf", ".tofu"},
        "severity": "medium",
        "pattern": None,  # whole-resource-block check; see _tf_asg_static_size_findings
        "message": "autoscaling group with min_size == max_size",
        "suggestion": "a fixed-size 'autoscaling' group is provisioned for peak load 24/7; widen the range so it can actually scale down under low demand",
    },
    {
        "id": "GL025",
        "langs": {".tf", ".tofu"},
        "severity": "low",
        "pattern": re.compile(r'volume_type\s*=\s*"gp2"'),
        "message": "EBS volume using gp2 instead of gp3",
        "suggestion": "gp3 gives the same baseline performance at lower cost and power draw per IOP than gp2; migrate unless you need gp2's specific burst behaviour",
    },
    {
        "id": "GL026",
        "langs": {".tf", ".tofu"},
        "severity": "medium",
        "pattern": None,  # whole-resource-block check; see _tf_log_retention_findings
        "message": "CloudWatch log group without a retention period",
        "suggestion": "logs are kept forever by default, growing storage and its energy footprint indefinitely; set retention_in_days",
    },
    {
        "id": "GL027",
        "langs": {".js", ".ts"},
        "severity": "low",
        "pattern": re.compile(r"express\.static\([^,)]*\)"),
        "message": "static assets served without a cache duration (Express)",
        "suggestion": "express.static() without maxAge sends no Cache-Control, so browsers re-fetch unchanged files every visit; set { maxAge: '1y', immutable: true } for hashed assets",
    },
    {
        "id": "GL028",
        "langs": {".py"},
        "severity": "low",
        "pattern": re.compile(r"^from\s+\S+\s+import\s+\*", re.MULTILINE),
        "message": "wildcard import",
        "suggestion": "star imports bind every public name in the module, bloating the namespace and import time; import only the names you use",
    },
    {
        "id": "GL029",
        "langs": {".dockerfile", "Dockerfile"},
        "severity": "low",
        "pattern": None,  # whole-file count check; see _dockerfile_layer_bloat_findings
        "message": "separate RUN install layer (image layer bloat)",
        "suggestion": "each RUN install creates a new image layer that must be pulled and stored; chain installs with && into one RUN to shrink transfer/storage footprint",
    },
    {
        "id": "GL030",
        "langs": {".py"},
        "severity": "low",
        "pattern": None,  # AST check; see _ast_dict_iterator_findings
        "message": "dict .items() iteration discards the key or value",
        "suggestion": "use .keys() or .values() directly instead of .items() when only one side is needed; skips building/unpacking the discarded half",
    },
    {
        "id": "GL031",
        "langs": {".py"},
        "severity": "low",
        "pattern": None,  # AST check; see _ast_try_in_loop_findings
        "message": "exception swallowed every iteration (exceptions as control flow)",
        "suggestion": "a handler that just passes/continues means the raise fires on ordinary input; raising and unwinding costs far more than an if-check. Test the condition instead of catching it",
    },
    {
        "id": "GL032",
        "langs": {".c", ".h", ".cpp", ".cc", ".hpp"},
        "severity": "medium",
        "pattern": re.compile(
            r"(?:for|while)\s*\([^\n]*\)\s*\{?\s*\n[ \t]*[^\n]*\b(?:malloc|calloc|realloc)\s*\("
            r"|(?:for|while)\s*\([^\n]*\)\s*\{?\s*\n[ \t]*[^\n]*\bnew\s+\w",
            re.MULTILINE,
        ),
        "message": "heap allocation inside a loop",
        "suggestion": "malloc/calloc/realloc/new repeats allocator overhead every iteration; allocate once before the loop and reuse the buffer (or reserve()/resize() for containers)",
    },
    {
        "id": "GL033",
        "langs": {".yml", ".yaml"},
        "severity": "medium",
        "pattern": None,  # whole-file check; see _k8s_hpa_static_findings
        "message": "HorizontalPodAutoscaler with minReplicas == maxReplicas",
        "suggestion": "a fixed-range HPA can't scale down under low demand; widen minReplicas/maxReplicas so it actually elasticity-scales",
    },
    {
        "id": "GL034",
        "langs": {".yml", ".yaml"},
        "severity": "medium",
        "pattern": None,  # whole-file check; see _compose_resources_findings
        "message": "docker-compose service(s) without resource limits",
        "suggestion": "unbounded containers can consume a whole host's CPU/RAM; set deploy.resources.limits (Swarm) or mem_limit/cpus (Compose v2) to right-size",
    },
    {
        "id": "GL035",
        "langs": {".cs"},
        "severity": "low",
        "pattern": re.compile(r"\.Count\(\)\s*(?:==\s*0|!=\s*0|>\s*0)"),
        "message": "LINQ .Count() used just to check emptiness",
        "suggestion": "Count() enumerates the whole sequence; use .Any() (or !sequence.Any()) which short-circuits on the first element",
    },
    {
        "id": "GL036",
        "langs": {".rb"},
        "severity": "low",
        "pattern": re.compile(r"\.(?:keys|values)\.include\?\("),
        "message": "Hash membership check via keys/values.include?",
        "suggestion": "materialises the whole keys/values array for an O(n) scan; use .key?/.value? for an O(1) hash lookup",
    },
    {
        "id": "GL037",
        "langs": {".rb"},
        "severity": "low",
        "pattern": re.compile(
            r"\.select\s*(?:\(&:\w+[?!]?\)|\{[^{}]*\})\s*\.map\s*(?:\(&:\w+[?!]?\)|\{[^{}]*\})"
        ),
        "message": "select().map() chain (two passes over the collection)",
        "suggestion": "use filter_map to select and transform in a single pass instead of two full iterations",
    },
    {
        "id": "GL038",
        "langs": {".jsx", ".tsx"},
        "severity": "low",
        "pattern": re.compile(r"\w+=\{(?:\(\)\s*=>|\{)"),
        "message": "inline function or object literal passed as a JSX prop",
        "suggestion": "a new function/object is allocated every render, defeating memo/PureComponent; hoist it with useCallback/useMemo or move it outside the component",
    },
]

RULES_BY_ID = {r["id"]: r for r in RULES}


def _as_list(value, key):
    """Coerce a config value to a list of strings, refusing a bare string.

    `disable = "GL005"` is the easy typo, and `set("GL005")` is the set of five
    characters — a config that looks applied and disables nothing. TOML gives
    us the real type, so the mistake is worth naming rather than silently
    iterating.
    """
    if value is None:
        return []
    if isinstance(value, str):
        raise SystemExit(
            f"greenlint: {CONFIG_FILENAME}: `{key}` must be a list, not a string — "
            f'write `{key} = ["{value}"]`'
        )
    return [str(v) for v in value]


def load_config(path=None):
    """Load `.greenlint.toml` (rule disable list + ignore globs). Missing
    file → no-op config. `path` overrides the default cwd lookup.

    A malformed config aborts rather than degrading to "no rules disabled":
    silently ignoring the file is how a config that looks applied turns out
    not to be.
    """
    cfg_path = Path(path) if path else Path.cwd() / CONFIG_FILENAME
    if not cfg_path.is_file():
        return {"disable": set(), "ignore": []}
    try:
        with cfg_path.open("rb") as fh:  # tomllib decodes UTF-8 itself, per spec
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"greenlint: {cfg_path}: invalid TOML — {exc}") from exc
    return {
        "disable": set(_as_list(data.get("disable"), "disable")),
        "ignore": _as_list(data.get("ignore"), "ignore"),
    }


# Line- and block-comment syntax per extension. Dockerfile/unknown default to `#`.
_SLASH = ("//", ("/*", "*/"))
COMMENT_SYNTAX = {
    ".go": _SLASH, ".js": _SLASH, ".ts": _SLASH, ".jsx": _SLASH, ".tsx": _SLASH,
    ".c": _SLASH, ".h": _SLASH, ".cpp": _SLASH, ".cc": _SLASH, ".hpp": _SLASH,
    ".java": _SLASH, ".rs": _SLASH, ".kt": _SLASH, ".swift": _SLASH, ".cs": _SLASH,
    ".php": _SLASH, ".scala": _SLASH,
    ".sql": ("--", ("/*", "*/")),
    ".py": ("#", None), ".sh": ("#", None), ".bash": ("#", None), ".rb": ("#", None),
    ".yml": ("#", None), ".yaml": ("#", None), ".tf": ("#", None), ".tofu": ("#", None),
    ".toml": ("#", None), ".pl": ("#", None), ".dockerfile": ("#", None),
}


def _blank_comments(text, path):
    """Return `text` with comment bodies replaced by spaces.

    Length and every newline are preserved, so line numbers and match offsets
    computed against the result still point at the real file. Quoted strings
    are respected, so a `#` inside a SQL string is not mistaken for a comment.

    Without this, every regex rule fires on prose that *warns against* the
    pattern — `# never write SELECT * here` reported as a SELECT * query. That
    was six false positives out of six in a six-line probe.

    Quote tracking is reset at every newline, and a `'` between two letters is
    read as an apostrophe rather than an opening quote. `echo don't` otherwise
    opened a string that never closed, and *every comment in the rest of the
    file* stayed visible to the rules — reintroducing the false positives this
    function exists to remove, on any shell, YAML or Ruby file containing an
    ordinary English contraction.

    The cost is that a genuinely multi-line string containing a comment token
    gets blanked. That is a false negative, which is the safe direction: this
    whole pass exists because a linter that cries wolf gets switched off.
    """
    line_tok, block = COMMENT_SYNTAX.get(
        path.suffix, ("#", None) if path.name == "Dockerfile" else (None, None)
    )
    if not line_tok:
        return text
    out = list(text)
    i, n, quote = 0, len(text), None
    while i < n:
        ch = text[i]
        if ch == "\n":
            quote = None
            i += 1
            continue
        if quote:
            # A trailing backslash is a line continuation, not an escape of the
            # newline we use to resynchronise.
            if ch == "\\" and i + 1 < n and text[i + 1] != "\n":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            if ch == "'" and 0 < i < n - 1 and text[i - 1].isalpha() and text[i + 1].isalpha():
                i += 1  # don't / it's / won't
                continue
            quote = ch
            i += 1
            continue
        if text.startswith(line_tok, i):
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if block and text.startswith(block[0], i):
            end = text.find(block[1], i + len(block[0]))
            end = n if end == -1 else end + len(block[1])
            for j in range(i, end):
                if out[j] != "\n":
                    out[j] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def _blank_python_docstrings(code, tree):
    """Blank module/class/function docstrings, preserving offsets.

    A docstring is prose, and prose about a pattern is not the pattern — the
    same reason comments are blanked. Ordinary string literals are left alone:
    `q = "SELECT * FROM t"` is a real query.
    """
    lines = code.splitlines(keepends=True)
    starts, off = [], 0
    for ln in lines:
        starts.append(off)
        off += len(ln)
    out = list(code)
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        doc = node.body[0] if node.body else None
        if not (
            isinstance(doc, ast.Expr)
            and isinstance(doc.value, ast.Constant)
            and isinstance(doc.value.value, str)
        ):
            continue
        s = starts[doc.lineno - 1] + doc.col_offset
        e = starts[doc.end_lineno - 1] + doc.end_col_offset
        for j in range(s, min(e, len(out))):
            if out[j] != "\n":
                out[j] = " "
    return "".join(out)


def _is_go_template(text):
    """True for a Helm/Go-template YAML file. What such a file *renders to* is
    what matters, and greenlint does not render it — so manifest rules that ask
    "is key X present" cannot answer honestly here.
    """
    return "{{" in text and "}}" in text


# `foo_test.go`, `test_foo.py`, `foo.test.ts`, `foo.spec.ts`.
TEST_FILENAME = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.|_spec\.)", re.IGNORECASE)


def _is_test_file(path):
    """True for test code. Tight sleeps and busy waits in a test are bounded by
    the test run and are usually the point (waiting for a condition quickly),
    so the energy rules that target long-lived loops do not apply.

    Matched on the filename plus an exact `test`/`tests`/`spec` directory
    component — not a substring of the whole path, which would exempt every
    file in a checkout that happens to sit under a directory containing "test".
    """
    if TEST_FILENAME.search(path.name):
        return True
    return any(part.lower() in ("test", "tests", "spec", "specs") for part in path.parts[:-1])


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


def _parse_python(path, text):
    """Parse `text` into an AST, or None on a syntax error. Shared by every
    AST-based Python rule so each file is only parsed once per scan.
    """
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError:
        return None


# A nested function, lambda or class body is its own scope: its statements and
# its name bindings belong to it, not to the code that encloses it.
SCOPE_BOUNDARIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _walk_own(node):
    """Like `ast.walk`, but never descends into a nested scope.

    `ast.walk` treats a `def` inside a loop as part of the loop, which made a
    `return` in a callback read as "this loop can exit" and a `total = 0` in
    one function silence a rebuild in another.
    """
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        for child in ast.iter_child_nodes(cur):
            if isinstance(child, SCOPE_BOUNDARIES):
                continue
            stack.append(child)


def _loop_can_exit(loop):
    """True if the loop body can leave the loop on a data-dependent condition —
    a `break` belonging to this loop, or a `return`/`raise`.

    `while True:` that drains a paginated API, reads a socket until EOF, or
    consumes an iterator all look like infinite loops and are not: each pass
    does work and the exit depends on what came back. What the energy rule is
    actually after is a loop with no way out and nothing to wait on, which
    pegs a core for as long as the process lives.
    """
    for stmt in loop.body:
        if isinstance(stmt, SCOPE_BOUNDARIES):
            continue  # a callback defined in the loop cannot end it
        for n in _walk_own(stmt):
            if isinstance(n, (ast.Return, ast.Raise)):
                return True
            if isinstance(n, ast.Break) and _nearest_loop(loop, n) is loop:
                return True
    return False


def _nearest_loop(root, target):
    """The innermost For/While in `root`'s body that encloses `target`, or
    `root` itself. A `break` inside a nested loop exits that one, not this one.
    """
    found = root
    stack = [(root, root)]
    while stack:
        node, owner = stack.pop()
        for child in ast.iter_child_nodes(node):
            if child is target:
                found = owner
                stack.clear()
                break
            # A nested function's `return` belongs to that function, not here.
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            nxt = child if isinstance(child, (ast.For, ast.While)) else owner
            stack.append((child, nxt))
    return found


def _ast_busy_loop_findings(path, tree):
    """AST-based replacement for GL001 on Python: the regex version flags
    `while True:` unless "sleep" appears *anywhere* in the file, which both
    misses loops whose sleep is in an unrelated function and flags loops that
    do sleep but happen to share a file with the word "sleep" elsewhere.
    Walking the loop body directly for a real sleep call fixes both.
    """
    rule = RULES_BY_ID["GL001"]
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.While)
            and isinstance(node.test, ast.Constant)
            and node.test.value is True
        ):
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
        if sleeps or _loop_can_exit(node):
            continue
        yield _finding(rule, path, node.lineno)


def _ast_nested_loop_findings(path, tree):
    """GL018: an inner `for` loop iterating over the same named collection as
    an enclosing `for` loop — a manual all-pairs O(n^2) scan (e.g. checking
    every element against every other). Only matches when both loops iterate
    a plain variable name, so `range(n)`/`enumerate(...)` nested loops (often
    legitimate matrix/grid code, not a same-collection rescan) are left alone.
    `seen` dedupes an inner loop matched from more than one enclosing loop
    when loops are nested three or more deep.
    """
    rule = RULES_BY_ID["GL018"]
    seen = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.For) and isinstance(node.iter, ast.Name)):
            continue
        for inner in ast.walk(node):
            if (
                inner is not node
                and isinstance(inner, ast.For)
                and isinstance(inner.iter, ast.Name)
                and inner.iter.id == node.iter.id
                and inner.lineno not in seen
            ):
                seen.add(inner.lineno)
                yield _finding(rule, path, inner.lineno)


def _is_tuple_swap(stmt):
    """True for the idiomatic Python swap `a[i], a[j] = a[j], a[i]` — two
    subscripts assigned from two subscripts. That shape only shows up when
    someone is hand-rolling an in-place swap, i.e. a manual sort.
    """
    return (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Tuple)
        and len(stmt.targets[0].elts) == 2
        and all(isinstance(e, ast.Subscript) for e in stmt.targets[0].elts)
        and isinstance(stmt.value, ast.Tuple)
        and len(stmt.value.elts) == 2
        and all(isinstance(e, ast.Subscript) for e in stmt.value.elts)
    )


def _ast_bubble_sort_findings(path, tree):
    """GL023: a `for` loop nested inside another `for` loop whose body
    contains an element swap — the textbook shape of a hand-rolled bubble or
    selection sort.
    """
    rule = RULES_BY_ID["GL023"]
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        for inner in ast.walk(node):
            if inner is node or not isinstance(inner, ast.For) or inner.lineno in seen:
                continue
            if any(_is_tuple_swap(stmt) for stmt in ast.walk(inner)):
                seen.add(inner.lineno)
                yield _finding(rule, path, inner.lineno)


def _ast_dict_iterator_findings(path, tree):
    """GL030: `for k, v in d.items()` where the key or the value is discarded
    (bound to `_`) — the discarded half didn't need building/unpacking at all.
    """
    rule = RULES_BY_ID["GL030"]
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Tuple)
            and len(node.target.elts) == 2
        ):
            continue
        if not (
            isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Attribute)
            and node.iter.func.attr == "items"
        ):
            continue
        key, value = node.target.elts
        if any(isinstance(e, ast.Name) and e.id == "_" for e in (key, value)):
            yield _finding(rule, path, node.lineno)


# Builtins/constructors whose result is a number or a duration, never a
# sequence — `n += len(x)` is a counter, not a rebuild.
SCALAR_CALLS = frozenset(
    {"len", "sum", "int", "float", "round", "abs", "ord", "timedelta", "Decimal"}
)
# Operators that only numbers support, so an expression using one is numeric.
SCALAR_OPS = (ast.Div, ast.FloorDiv, ast.Sub, ast.Mod, ast.Pow)


def _is_scalar_expr(node):
    """True when the expression is certainly numeric, so `x += node` is a
    counter rather than a sequence rebuild. Conservative: unknown names are
    not scalar, because `data += chunk` is exactly the case worth catching.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float, complex)) and not isinstance(
            node.value, bool
        )
    if isinstance(node, ast.Call):
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        return name in SCALAR_CALLS
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, SCALAR_OPS):
            return True
        return _is_scalar_expr(node.left) or _is_scalar_expr(node.right)
    if isinstance(node, ast.UnaryOp):
        return _is_scalar_expr(node.operand)
    return False


def _names_bound_to_lists(nodes):
    """(list_names, scalar_names) — names seen initialised to a list, and names
    seen initialised to a number, among `nodes`.

    `nodes` is one scope's own statements, never the whole module: `total = 0`
    in one function said nothing about `total` in the next, but sharing one
    namespace let any counter anywhere in the file silence a genuine rebuild
    everywhere else — and `total`, `out`, `result` and `s` collide constantly.

    `xs += <anything>` on a list is `list.extend`: in place, O(k). It is only
    quadratic when the target is immutable (str, bytes, tuple), because those
    build a whole new object each time. Knowing how the name was initialised is
    what tells the two apart — `lines = []` a few lines up is the difference
    between `lines += render(x)` being fine and being O(n^2), and `errors = 0`
    is the difference between `errors += e` being a counter and a rebuild.
    """
    lists, scalars = set(), set()
    for node in nodes:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = {t.id for t in targets if isinstance(t, ast.Name)}
        if isinstance(value, (ast.List, ast.ListComp)):
            lists |= names
        elif (
            isinstance(value, ast.Constant)
            and isinstance(value.value, (int, float))
            and not isinstance(value.value, bool)
        ):
            scalars |= names
    return lists, scalars


def _ast_quadratic_rebuild_findings(path, tree):
    """GL007: accumulating with `+`/`+=` inside a loop, which copies the whole
    sequence built so far on every iteration — O(n^2) allocation where
    `list.append` / `''.join` are linear.

    Deliberately narrow: only `x += <expr>` and `x = x + <expr>` where the
    target is a plain name. `list.append()` in a loop is idiomatic and
    amortised O(1) — the previous version of this rule flagged it, which made
    the rule fire on almost every Python file that builds a list.
    """
    rule = RULES_BY_ID["GL007"]
    seen = set()
    # One pass per scope, each judged against only its own name bindings.
    scopes = [tree] + [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for scope in scopes:
        own = list(_walk_own(scope))
        list_names, scalar_names = _names_bound_to_lists(own)
        for node in own:
            if not isinstance(node, (ast.For, ast.While)):
                continue
            for stmt in _walk_own(node):
                if not isinstance(stmt, (ast.AugAssign, ast.Assign)) or stmt.lineno in seen:
                    continue
                target = value = None
                if isinstance(stmt, ast.AugAssign) and isinstance(stmt.op, ast.Add):
                    target, value = stmt.target, stmt.value
                elif (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.value, ast.BinOp)
                    and isinstance(stmt.value.op, ast.Add)
                ):
                    target, value = stmt.targets[0], stmt.value
                if not isinstance(target, ast.Name):
                    continue
                # `x = x + ...` only — `x = y + z` rebinds, not accumulates.
                if isinstance(stmt, ast.Assign):
                    left = stmt.value.left
                    if not (isinstance(left, ast.Name) and left.id == target.id):
                        continue
                # A numeric counter (`total += 1`, `seen += len(chunk)`, `kwh +=
                # watts * hours / 1000`) accumulates in O(1) — not a rebuild.
                if _is_scalar_expr(value) or target.id in scalar_names:
                    continue
                # `xs += ...` is `list.extend` when xs is a list: in place,
                # O(k), no copy. Either the list literal on the right proves it
                # (`+=` a list is a TypeError for str/bytes/tuple), or the name
                # was seen being initialised to one. Only the rebinding form
                # (`xs = xs + [a]`) copies everything accumulated so far.
                if isinstance(stmt, ast.AugAssign) and (
                    isinstance(value, (ast.List, ast.ListComp))
                    or target.id in list_names
                ):
                    continue
                seen.add(stmt.lineno)
                yield _finding(rule, path, stmt.lineno)


# Conversions whose failure is routinely used as a type test, where a
# non-throwing check exists (`.isdigit()`, a regex, a guard).
PROBE_CALLS = frozenset({"int", "float", "complex", "Decimal"})


def _has_cheap_alternative(body):
    """True when the guarded work is a lookup or a numeric conversion — the
    cases where the exception is standing in for a test that costs nothing:
    `d[k]` where `d.get(k)` works, `int(s)` where a guard works.

    Anything else (opening a file, parsing a document, a subprocess, a network
    call) can legitimately fail on good input, and catching it is the correct
    way to write that — not a pattern to flag.
    """
    if len(body) != 1:
        return False
    stmt = body[0]
    value = getattr(stmt, "value", None)
    if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.Expr)) and value is not None:
        if isinstance(value, ast.Subscript):
            return True
        if isinstance(value, ast.Call):
            name = getattr(value.func, "id", None) or getattr(value.func, "attr", None)
            return name in PROBE_CALLS
    return False


def _ast_try_in_loop_findings(path, tree):
    """GL031: exceptions used as per-iteration control flow inside a loop —
    a handler whose whole body is `pass` or `continue`, i.e. the exception is
    expected to fire on ordinary input and the raise/unwind cost is paid every
    time round.

    Not "a try inside a loop". Since Python 3.11 a try block that does not
    raise costs nothing at runtime, so the old form of this rule was measuring
    something that stopped existing — and it fired on every retry loop,
    per-item error collector and `except OSError: break` read loop in the
    portfolio, all of which need the handler exactly where it is.

    `seen` dedupes a `try` matched from more than one enclosing loop when
    loops are nested.
    """
    rule = RULES_BY_ID["GL031"]
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.While)):
            continue
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Try) or stmt.lineno in seen:
                continue
            swallowed = any(
                all(isinstance(b, (ast.Pass, ast.Continue)) for b in h.body)
                for h in stmt.handlers
            )
            if swallowed and _has_cheap_alternative(stmt.body):
                seen.add(stmt.lineno)
                yield _finding(rule, path, stmt.lineno)


def _tf_resource_blocks(text, resource_type):
    """Yield (match, block_text, lineno) for every `resource "<resource_type>"
    "..." { ... }` in `text`. Block end is approximated as the next line that
    is just `}`, which matches typical `terraform fmt` output; not a real HCL
    parse, but enough to check whether a given argument is set inside it.
    Shared by every whole-resource-block Terraform check.
    """
    for m in re.finditer(rf'resource\s+"{resource_type}"\s+"[^"]+"\s*\{{', text):
        end = text.find("\n}", m.end())
        block = text[m.end() : end if end != -1 else len(text)]
        yield m, block, text.count("\n", 0, m.start()) + 1


def _tf_s3_lifecycle_findings(path, text):
    """GL013: an `aws_s3_bucket` resource block with no lifecycle rule anywhere
    inside it.
    """
    rule = RULES_BY_ID["GL013"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_s3_bucket"):
        if "lifecycle" not in block.lower():
            yield _finding(rule, path, lineno)


def _tf_asg_static_size_findings(path, text):
    """GL024: an `aws_autoscaling_group` whose min_size and max_size are the
    same literal value — a fixed-size group provisioned for peak load, not an
    elastic one.
    """
    rule = RULES_BY_ID["GL024"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_autoscaling_group"):
        min_m = re.search(r"min_size\s*=\s*(\d+)", block)
        max_m = re.search(r"max_size\s*=\s*(\d+)", block)
        if min_m and max_m and min_m.group(1) == max_m.group(1):
            yield _finding(rule, path, lineno)


def _tf_log_retention_findings(path, text):
    """GL026: an `aws_cloudwatch_log_group` with no `retention_in_days` set —
    logs are kept forever by default.
    """
    rule = RULES_BY_ID["GL026"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_cloudwatch_log_group"):
        if "retention_in_days" not in block:
            yield _finding(rule, path, lineno)


def _dockerfile_layer_bloat_findings(path, text):
    """GL029: more than one separate `RUN ... install` line in a Dockerfile —
    each is its own image layer. Flags every occurrence after the first.

    Counted per build stage, not per file: layers created in a stage that the
    final image does not inherit from are thrown away, so chaining installs
    across a `FROM ... AS build` boundary saves nothing and is usually
    impossible anyway.
    """
    rule = RULES_BY_ID["GL029"]
    stage_starts = [m.start() for m in re.finditer(r"^FROM\s+", text, re.MULTILINE)]
    installs = [
        m.start()
        for m in re.finditer(
            r"^RUN\s+.*\b(?:apt(?:-get)?|pip3?|npm|yum)\s+install\b",
            text,
            re.MULTILINE | re.IGNORECASE,
        )
    ]
    seen_stages = set()
    for pos in installs:
        stage = sum(1 for s in stage_starts if s < pos)
        if stage in seen_stages:
            yield _finding(rule, path, text.count("\n", 0, pos) + 1)
        seen_stages.add(stage)


def _k8s_resources_findings(path, text):
    """GL014: a Pod-spec-bearing manifest with no `resources:` block anywhere
    in the file. File-wide, not per-container; a real gap for single-manifest
    repos, a false negative for values shared via Helm/Kustomize overlays.

    Go-template files are skipped: in a Helm chart the pod spec usually lives
    in an included partial and `resources:` comes from `values.yaml`, so the
    unrendered template says nothing about whether the workload is bounded.
    """
    rule = RULES_BY_ID["GL014"]
    if _is_go_template(text):
        return
    m = re.search(r"^kind:\s*(Deployment|StatefulSet|DaemonSet|Pod)\s*$", text, re.MULTILINE)
    if m and "resources:" not in text:
        yield _finding(rule, path, text.count("\n", 0, m.start()) + 1)


def _k8s_hpa_static_findings(path, text):
    """GL033: a `HorizontalPodAutoscaler` manifest whose minReplicas and
    maxReplicas are the same literal value — a fixed-range HPA, not an
    elastic one.
    """
    rule = RULES_BY_ID["GL033"]
    if not re.search(r"^kind:\s*HorizontalPodAutoscaler\s*$", text, re.MULTILINE):
        return
    min_m = re.search(r"minReplicas:\s*(\d+)", text)
    max_m = re.search(r"maxReplicas:\s*(\d+)", text)
    if min_m and max_m and min_m.group(1) == max_m.group(1):
        yield _finding(rule, path, text.count("\n", 0, min_m.start()) + 1)


# Tools that read commit history, not just the working tree: a shallow clone
# makes them wrong (or makes them fail), so `fetch-depth: 0` is the correct
# setting and GL004 must not nag about it. Matched case-insensitively against
# the whole workflow file.
NEEDS_FULL_HISTORY = re.compile(
    r"gitleaks|trufflehog|sonar|codecov|scorecard|release-please|semantic-release"
    r"|git-cliff|gitversion|conventional-changelog|git\s+log|git\s+describe"
    # goreleaser builds its changelog from the tag history.
    r"|goreleaser"
    # Reviewers that diff a PR against its merge-base need both branches.
    r"|gandalf|merge-base",
    re.IGNORECASE,
)


def _job_span(text, pos):
    """(start, end) of the `jobs:` entry containing `pos`, or the whole file.

    Crude on purpose — indentation, not a YAML parse, because greenlint has no
    YAML dependency and this only needs to find a block boundary. Any workflow
    it cannot segment falls back to the whole file, which is what the rule did
    everywhere before.
    """
    jobs = re.search(r"^jobs:[ \t]*$", text, re.MULTILINE)
    if not jobs or pos < jobs.end():
        return 0, len(text)
    body = text[jobs.end():]
    # The first key under `jobs:` sets the indent at which a sibling job starts.
    first = re.search(r"^([ \t]+)[\w-]+:[ \t]*$", body, re.MULTILINE)
    if not first:
        return 0, len(text)
    starts = [
        jobs.end() + m.start()
        for m in re.finditer(rf"^{re.escape(first.group(1))}[\w-]+:[ \t]*$", body, re.MULTILINE)
    ]
    before = [s for s in starts if s <= pos]
    after = [s for s in starts if s > pos]
    return (before[-1] if before else jobs.end()), (after[0] if after else len(text))


def _fetch_depth_findings(path, text):
    """GL004: a full-history clone in CI.

    Skipped when the **same job** runs something that genuinely needs the
    history — a secret scanner walking every commit, or a release tool deriving
    a version from tags. Telling those workflows to shallow-clone trades a
    working scan for a broken one, which is not a saving.

    Per job, not per file: one `gitleaks` job used to exempt every other job in
    the same workflow, including the ones cloning all of history for nothing.
    """
    rule = RULES_BY_ID["GL004"]
    for m in re.finditer(r"fetch-depth:\s*0", text):
        start, end = _job_span(text, m.start())
        if NEEDS_FULL_HISTORY.search(text, start, end):
            continue
        # A commented-out or discussed setting is not a setting. Prose about
        # `fetch-depth: 0` is common in the docs of tools that avoid needing it.
        line_start = text.rfind("\n", 0, m.start()) + 1
        if "#" in text[line_start : m.start()]:
            continue
        yield _finding(rule, path, text.count("\n", 0, m.start()) + 1)


def _compose_resources_findings(path, text):
    """GL034: a docker-compose/swarm file (`services:` top-level key) with no
    resource limit anywhere in the file — neither the Swarm-mode
    `deploy.resources` block nor the classic `mem_limit`/`cpus` keys.
    """
    rule = RULES_BY_ID["GL034"]
    m = re.search(r"^services:\s*$", text, re.MULTILINE)
    if m and not re.search(r"mem_limit|nano_cpus|cpus\s*:|memory\s*:", text):
        yield _finding(rule, path, text.count("\n", 0, m.start()) + 1)


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
    # Everything that pattern-matches works on this view, in which comment
    # bodies are spaces. Offsets and line numbers still line up with the file.
    # GL004 is the exception: it reads comments deliberately, to spot the tool
    # that needs the full history.
    code = _blank_comments(text, path)
    # Parsed once and reused: the docstring pass and the AST rules both need
    # this tree, and `ast.parse` on every Python file twice is exactly the kind
    # of waste this tool exists to point at.
    tree = _parse_python(path, text) if path.suffix == ".py" else None
    if tree is not None:
        code = _blank_python_docstrings(code, tree)
    # Rules about long-lived loops, applied to test code, only ever produce
    # noise: a test's tight wait is bounded by the test run and is the point.
    if _is_test_file(path):
        disabled = disabled | {"GL001", "GL002", "GL007"}
    ast_rules = {"GL001", "GL007", "GL018", "GL023", "GL030", "GL031"}
    if ast_rules - disabled:
        if tree is not None:
            if "GL001" not in disabled:
                yield from _ast_busy_loop_findings(path, tree)
            if "GL007" not in disabled:
                yield from _ast_quadratic_rebuild_findings(path, tree)
            if "GL018" not in disabled:
                yield from _ast_nested_loop_findings(path, tree)
            if "GL023" not in disabled:
                yield from _ast_bubble_sort_findings(path, tree)
            if "GL030" not in disabled:
                yield from _ast_dict_iterator_findings(path, tree)
            if "GL031" not in disabled:
                yield from _ast_try_in_loop_findings(path, tree)
    if path.suffix in (".tf", ".tofu"):
        if "GL013" not in disabled:
            yield from _tf_s3_lifecycle_findings(path, code)
        if "GL024" not in disabled:
            yield from _tf_asg_static_size_findings(path, code)
        if "GL026" not in disabled:
            yield from _tf_log_retention_findings(path, code)
    if path.suffix in (".yml", ".yaml"):
        if "GL004" not in disabled:
            yield from _fetch_depth_findings(path, text)
        if "GL014" not in disabled:
            yield from _k8s_resources_findings(path, code)
        if "GL033" not in disabled:
            yield from _k8s_hpa_static_findings(path, code)
        if "GL034" not in disabled:
            yield from _compose_resources_findings(path, code)
    if (path.suffix == ".dockerfile" or path.name == "Dockerfile") and "GL029" not in disabled:
        yield from _dockerfile_layer_bloat_findings(path, code)
    for rule in RULES:
        if (
            rule["id"] in disabled
            or rule["id"] in ast_rules
            or rule["pattern"] is None
            or not applicable(rule, path)
        ):
            continue
        for m in rule["pattern"].finditer(code):
            line = code.count("\n", 0, m.start()) + 1
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
            # Matched against the path both as given and with a leading `/`.
            # `greenlint .` produces `tests/x.py`, which `*/tests/*` cannot
            # match — so the obvious way to write an ignore glob silently did
            # nothing, including in greenlint's own .greenlint.toml. Trying
            # both keeps bare patterns like `tests/*` working too.
            rel = f.as_posix()
            forms = (rel, rel if rel.startswith("/") else "/" + rel)
            if any(fnmatch.fnmatch(s, pat) for pat in config["ignore"] for s in forms):
                continue
            findings.extend(scan_file(f, config["disable"]))
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda x: (order[x["severity"]], x["file"], x["line"]))
    return findings


def main(argv=None):
    """CLI entry point; returns the process exit code."""
    p = argparse.ArgumentParser(
        prog="greenlint",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("paths", nargs="*", default=["."])
    p.add_argument("--list-rules", action="store_true")
    p.add_argument("--format", choices=["text", "json", "github"], default="text")
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
    elif args.format == "github":
        # https://docs.github.com/actions/using-workflows/workflow-commands-for-github-actions#setting-a-notice-message
        level = {"high": "error", "medium": "warning", "low": "notice"}
        for f in findings:
            print(
                f"::{level[f['severity']]} file={f['file']},line={f['line']},"
                f"title=greenlint {f['rule']}::{f['message']} — {f['suggestion']}"
            )
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
