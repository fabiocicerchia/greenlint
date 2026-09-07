"""The rule table -- every pattern greenlint knows, read top to bottom."""

from __future__ import annotations

import re
from typing import cast

from .base import Rule

# ----------------------------------------------------------------- rules ---

RULES: list[Rule] = [
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
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
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
        "pattern": re.compile(r"^FROM\s+(?:ubuntu|debian)(?::|\s|$)(?!.*slim)", re.MULTILINE | re.IGNORECASE),
        "message": "full-fat base image",
        "suggestion": "prefer -slim/alpine/distroless: smaller pulls, less storage, faster cold starts",
    },
    {
        "id": "GL007",
        "langs": {".py"},
        "severity": "low",
        "pattern": None,  # whole-file check; see _ast_quadratic_rebuild_findings
        "message": "quadratic rebuild in a loop (whole sequence copied each iteration)",
        "suggestion": (
            "`x = x + [i]` / `x += [i]` on a list, or `s += t` on a string, copies everything accumulated so far on "
            "every pass — O(n^2) allocation. Use list.append() (amortised O(1)) or collect the parts and ''.join() "
            "them once"
        ),
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
        "pattern": re.compile(r"apt-get\s+install(?!.*--no-install-recommends)[^\n]*", re.IGNORECASE),
        "message": "apt-get install without --no-install-recommends",
        "suggestion": (
            "recommended/suggested packages bloat the image; skip them to cut pull, transfer, and storage energy"
        ),
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
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".py"},
        "severity": "medium",
        "pattern": re.compile(r"for\s+\w+\s+in\s+[^:\n]+:\n[ \t]+\S*\.execute\(", re.MULTILINE),
        "message": "database query executed inside a loop (N+1 pattern)",
        "suggestion": (
            "batch into one query (e.g. WHERE id IN (...)) instead of one round-trip per item; cuts DB CPU and network "
            "energy"
        ),
    },
    {
        "id": "GL013",
        "langs": {".tf", ".tofu"},
        "severity": "low",
        "pattern": None,  # whole-resource-block check; see _tf_s3_lifecycle_findings
        "message": "S3 bucket without a lifecycle policy",
        "suggestion": (
            "stale objects sit in hot storage forever; add a lifecycle_rule (or aws_s3_bucket_lifecycle_configuration) "
            "to tier or expire old data"
        ),
    },
    {
        "id": "GL014",
        "langs": {".yml", ".yaml"},
        "severity": "medium",
        "pattern": None,  # whole-file check; see _k8s_resources_findings
        "message": "Kubernetes workload without CPU/memory requests or limits",
        "suggestion": (
            "unbounded containers get scheduled without guardrails, encouraging over-provisioned, underutilised nodes; "
            "set resources.requests/limits to right-size"
        ),
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
        "suggestion": (
            "older runtimes lack the perf/efficiency work in newer releases and pull more security-patch layers over "
            "time; move to a current stable version"
        ),
    },
    {
        "id": "GL016",
        "langs": {".tf", ".tofu"},
        "severity": "low",
        "pattern": re.compile(r'instance_type\s*=\s*"(?:t2|t3|m4|m5|c4|c5|r4|r5)\.[a-z0-9]+"', re.IGNORECASE),
        "message": "x86 instance family with an ARM/Graviton equivalent available",
        "suggestion": (
            "ARM-based instances (t4g/m6g/c6g/r6g) draw roughly 40% less for equal work; AWS publishes 'up to 60% less "
            "energy', independent benchmarks land nearer 45-50%, so 40% is the conservative end"
        ),
    },
    {
        "id": "GL017",
        "langs": {".html", ".css"},
        "severity": "low",
        "pattern": re.compile(r"""(?:<img\b[^>]*\bsrc\s*=\s*["']|url\(\s*["']?)[^"'\)\s]+\.gif\b""", re.IGNORECASE),
        "message": "GIF referenced for image/animation",
        "suggestion": (
            "GIFs are an obsolete, inefficient animation format; MP4/WebP/AVIF (or SVG/CSS animation) give smaller "
            "files and less energy per view"
        ),
    },
    {
        "id": "GL018",
        "langs": {".py"},
        "severity": "low",
        "pattern": None,  # AST check; see _ast_nested_loop_findings
        "message": "nested loop iterating over the same collection (possible O(n²) pattern)",
        "suggestion": (
            "a manual all-pairs scan over the same list costs O(n²); use a set/dict for membership tests or "
            "itertools.combinations instead"
        ),
    },
    {
        "id": "GL019",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".py"},
        "severity": "medium",
        "pattern": re.compile(
            r"for\s+\w+\s+in\s+[^:\n]+:\n[ \t]+(?:\w+\s*=\s*)?requests\.(?:get|post|put|patch|delete)\(",
            re.MULTILINE,
        ),
        "message": "HTTP request executed inside a loop (N+1-style network calls)",
        "suggestion": (
            "batch the calls, reuse a requests.Session, or gather them concurrently instead of one request per "
            "iteration; cuts round-trips and idle-wait energy"
        ),
    },
    {
        "id": "GL020",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".py"},
        "severity": "low",
        "pattern": re.compile(r"""logging\.(?:debug|info)\(\s*(?:f['"]|['"][^'"]*['"]\s*\.\s*format\()"""),
        "message": "logging call built eagerly with an f-string or .format()",
        "suggestion": (
            "the interpolation runs even when the log level is disabled; use logging.debug('x=%s', x) for lazy "
            "formatting"
        ),
    },
    {
        "id": "GL021",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".py"},
        "severity": "medium",
        "pattern": re.compile(r"\.iterrows\(\)|\.apply\([^)]*axis\s*=\s*1"),
        "message": "row-wise pandas iteration (iterrows/apply(axis=1))",
        "suggestion": (
            "row-wise pandas ops run one Python-level call per row; use vectorised column operations for 10-100x fewer "
            "CPU cycles"
        ),
    },
    {
        "id": "GL022",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".py"},
        "severity": "low",
        "pattern": re.compile(
            r"for\s+\w+\s+in\s+[^:\n]+:\n[ \t]+(?:\w+\s*=\s*)?(?:open\(|pd\.read_csv\(|pd\.read_json\()",
            re.MULTILINE,
        ),
        "message": "file opened/read inside a loop",
        "suggestion": (
            "repeated opens/reads add a syscall and parse pass per iteration; load once outside the loop or read in "
            "chunks"
        ),
    },
    {
        "id": "GL023",
        "langs": {".py"},
        "severity": "medium",
        "pattern": None,  # AST check; see _ast_bubble_sort_findings
        "message": "nested loop with an element swap (manual O(n²) sort)",
        "suggestion": (
            "built-in sorted()/list.sort() use Timsort (O(n log n), implemented in C); replace the manual swap-based "
            "sort"
        ),
    },
    {
        "id": "GL024",
        "langs": {".tf", ".tofu"},
        "severity": "medium",
        "pattern": None,  # whole-resource-block check; see _tf_asg_static_size_findings
        "message": "autoscaling group with min_size == max_size",
        "suggestion": (
            "a fixed-size 'autoscaling' group is provisioned for peak load 24/7; widen the range so it can actually "
            "scale down under low demand"
        ),
    },
    {
        "id": "GL025",
        "langs": {".tf", ".tofu"},
        "severity": "low",
        "pattern": re.compile(r'volume_type\s*=\s*"gp2"'),
        "message": "EBS volume using gp2 instead of gp3",
        "suggestion": (
            "gp3 gives the same baseline performance at lower cost and power draw per IOP than gp2; migrate unless you "
            "need gp2's specific burst behaviour"
        ),
    },
    {
        "id": "GL026",
        "langs": {".tf", ".tofu"},
        "severity": "medium",
        "pattern": None,  # whole-resource-block check; see _tf_log_retention_findings
        "message": "CloudWatch log group without a retention period",
        "suggestion": (
            "logs are kept forever by default, growing storage and its energy footprint indefinitely; set "
            "retention_in_days"
        ),
    },
    {
        "id": "GL027",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".js", ".ts"},
        "severity": "low",
        "pattern": re.compile(r"express\.static\([^,)]*\)"),
        "message": "static assets served without a cache duration (Express)",
        "suggestion": (
            "express.static() without maxAge sends no Cache-Control, so browsers re-fetch unchanged files every visit; "
            "set { maxAge: '1y', immutable: true } for hashed assets"
        ),
    },
    {
        "id": "GL028",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".py"},
        "severity": "low",
        "pattern": re.compile(r"^from\s+\S+\s+import\s+\*", re.MULTILINE),
        "message": "wildcard import",
        "suggestion": (
            "star imports bind every public name in the module, bloating the namespace and import time; import only "
            "the names you use"
        ),
    },
    {
        "id": "GL029",
        "langs": {".dockerfile", "Dockerfile"},
        "severity": "low",
        "pattern": None,  # whole-file count check; see _dockerfile_layer_bloat_findings
        "message": "separate RUN install layer (image layer bloat)",
        "suggestion": (
            "each RUN install creates a new image layer that must be pulled and stored; chain installs with && into "
            "one RUN to shrink transfer/storage footprint"
        ),
    },
    {
        "id": "GL030",
        "langs": {".py"},
        "severity": "low",
        "pattern": None,  # AST check; see _ast_dict_iterator_findings
        "message": "dict .items() iteration discards the key or value",
        "suggestion": (
            "use .keys() or .values() directly instead of .items() when only one side is needed; skips "
            "building/unpacking the discarded half"
        ),
    },
    {
        "id": "GL031",
        "langs": {".py"},
        "severity": "low",
        "pattern": None,  # AST check; see _ast_try_in_loop_findings
        "message": "exception swallowed every iteration (exceptions as control flow)",
        "suggestion": (
            "a handler that just passes/continues means the raise fires on ordinary input; raising and unwinding costs "
            "far more than an if-check. Test the condition instead of catching it"
        ),
    },
    {
        "id": "GL032",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".c", ".h", ".cpp", ".cc", ".hpp"},
        "severity": "medium",
        "pattern": re.compile(
            r"(?:for|while)\s*\([^\n]*\)\s*\{?\s*\n[ \t]*[^\n]*\b(?:malloc|calloc|realloc)\s*\("
            r"|(?:for|while)\s*\([^\n]*\)\s*\{?\s*\n[ \t]*[^\n]*\bnew\s+\w",
            re.MULTILINE,
        ),
        "message": "heap allocation inside a loop",
        "suggestion": (
            "malloc/calloc/realloc/new repeats allocator overhead every iteration; allocate once before the loop and "
            "reuse the buffer (or reserve()/resize() for containers)"
        ),
    },
    {
        "id": "GL033",
        "langs": {".yml", ".yaml"},
        "severity": "medium",
        "pattern": None,  # whole-file check; see _k8s_hpa_static_findings
        "message": "HorizontalPodAutoscaler with minReplicas == maxReplicas",
        "suggestion": (
            "a fixed-range HPA can't scale down under low demand; widen minReplicas/maxReplicas so it actually "
            "elasticity-scales"
        ),
    },
    {
        "id": "GL034",
        "langs": {".yml", ".yaml"},
        "severity": "medium",
        "pattern": None,  # whole-file check; see _compose_resources_findings
        "message": "docker-compose service(s) without resource limits",
        "suggestion": (
            "unbounded containers can consume a whole host's CPU/RAM; set deploy.resources.limits (Swarm) or "
            "mem_limit/cpus (Compose v2) to right-size"
        ),
    },
    {
        "id": "GL035",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".cs"},
        "severity": "low",
        "pattern": re.compile(r"\.Count\(\)\s*(?:==\s*0|!=\s*0|>\s*0)"),
        "message": "LINQ .Count() used just to check emptiness",
        "suggestion": (
            "Count() enumerates the whole sequence; use .Any() (or !sequence.Any()) which short-circuits on the first "
            "element"
        ),
    },
    {
        "id": "GL036",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".rb"},
        "severity": "low",
        "pattern": re.compile(r"\.(?:keys|values)\.include\?\("),
        "message": "Hash membership check via keys/values.include?",
        "suggestion": (
            "materialises the whole keys/values array for an O(n) scan; use .key?/.value? for an O(1) hash lookup"
        ),
    },
    {
        "id": "GL037",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".rb"},
        "severity": "low",
        "pattern": re.compile(r"\.select\s*(?:\(&:\w+[?!]?\)|\{[^{}]*\})\s*\.map\s*(?:\(&:\w+[?!]?\)|\{[^{}]*\})"),
        "message": "select().map() chain (two passes over the collection)",
        "suggestion": "use filter_map to select and transform in a single pass instead of two full iterations",
    },
    # C# section. Two rules was "barely checked" -- see docs/rules.md coverage.
    {
        "id": "GL039",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".cs"},
        "severity": "medium",
        "pattern": re.compile(r"\bnew\s+HttpClient\s*\("),
        "message": "new HttpClient per call",
        "suggestion": (
            "reuse one client (IHttpClientFactory or a static instance); each new client opens a fresh connection and "
            "repeats the TLS handshake, which is CPU on both ends"
        ),
    },
    {
        "id": "GL040",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".cs"},
        "severity": "medium",
        "pattern": re.compile(r"\.(?:Result\b|Wait\(\))"),
        "message": "blocking on a Task (.Result / .Wait())",
        "suggestion": (
            "await it; blocking a pool thread makes the pool grow, and the extra threads cost memory and context "
            "switches for work that was already asynchronous"
        ),
    },
    {
        "id": "GL041",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".cs"},
        "severity": "low",
        # .*? rather than [^)]*: the collection expression usually contains
        # its own parentheses (a lambda), which a negated-class scan cannot
        # cross.
        "pattern": re.compile(r"foreach\s*\(.*?\bin\b.*?\.ToList\(\)"),
        "message": "ToList() materialised just to iterate it once",
        "suggestion": (
            "iterate the sequence directly; ToList() allocates the whole collection to walk it once and then throws it "
            "away"
        ),
    },
    # --- Kotlin ---
    {
        "id": "GL042",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".kt"},
        "severity": "medium",
        "pattern": re.compile(r"\bGlobalScope\.(?:launch|async)\b"),
        "message": "GlobalScope coroutine",
        "suggestion": (
            "use a scoped CoroutineScope; a GlobalScope coroutine is never cancelled with its caller, so work "
            "continues after nobody wants the result"
        ),
    },
    {
        "id": "GL043",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".kt"},
        "severity": "low",
        "pattern": re.compile(r"\.filter\s*\{[^{}]*\}\s*\.map\s*\{"),
        "message": "filter{}.map{} chain (two passes over the collection)",
        "suggestion": (
            "use mapNotNull, or asSequence() before the chain, so the collection is walked once and no intermediate "
            "list is allocated"
        ),
    },
    {
        "id": "GL044",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".kt"},
        "severity": "medium",
        "pattern": re.compile(r"\brunBlocking\s*(?:\([^)]*\))?\s*\{"),
        "message": "runBlocking",
        "suggestion": (
            "runBlocking parks a real thread until the coroutine finishes; suspend the caller instead, outside of "
            "main() and tests where it is the entry point"
        ),
    },
    # --- Swift ---
    {
        "id": "GL045",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".swift"},
        "severity": "low",
        "pattern": re.compile(r"\.filter\s*\{[^{}]*\}\s*\.map\s*\{"),
        "message": "filter{}.map{} chain (two passes over the collection)",
        "suggestion": (
            "use compactMap, or .lazy before the chain, so the sequence is walked once without an intermediate array"
        ),
    },
    {
        "id": "GL046",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".swift"},
        "severity": "medium",
        "pattern": re.compile(r"DispatchQueue\.\w+\.sync\s*\{"),
        "message": "DispatchQueue.sync",
        "suggestion": (
            "blocks the calling thread until the block returns, so a thread sits idle burning its stack and scheduler "
            "slot; use async with a completion or async/await"
        ),
    },
    {
        "id": "GL047",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".swift"},
        "severity": "low",
        "pattern": re.compile(r"URLSession\(configuration:\s*\.default\)"),
        "message": "a new URLSession per request",
        "suggestion": (
            "reuse URLSession.shared or one stored session; a fresh session drops the connection pool, so every "
            "request pays a new handshake"
        ),
    },
    # --- Ruby ---
    {
        "id": "GL048",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".rb"},
        "severity": "medium",
        # The += has to look like string building — a literal, an
        # interpolation, or a to_s — so `total += price` (a number, which is
        # not quadratic) does not fire.
        "pattern": re.compile(
            r"\.each\s*(?:do\s*\|[^|]*\||\{\s*\|[^|]*\|)[^\n]*\n"
            r"(?:[^\n]*\n){0,4}?[^\n]*\b\w+\s*\+=\s*[^\n]*(?:[\"']|to_s\b|#\{)"
        ),
        "message": "string built with += inside a loop",
        "suggestion": (
            "use << or an array joined at the end; += allocates a new string each iteration, so the loop is quadratic "
            "in the length it builds"
        ),
    },
    {
        "id": "GL049",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".rb"},
        "severity": "medium",
        "pattern": re.compile(
            r"\.(?:where|find_by|find)\([^)]*\)[^\n]*\n(?:[^\n]*\n){0,3}?[^\n]*\.each\b|\.each\s*(?:do\s*\|[^|]*\||\{\s*\|[^|]*\|)[^\n]{0,80}\n[^\n]*\.(?:where|find_by)\("
        ),
        "message": "query inside an each loop (N+1)",
        "suggestion": (
            "load the association up front with includes/preload; one query per row is one network round trip and one "
            "remote query plan per row"
        ),
    },
    {
        "id": "GL050",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".rb"},
        "severity": "low",
        "pattern": re.compile(r"\.map\s*(?:\(&:\w+[?!]?\)|\{[^{}]*\})\s*\.(?:flatten|compact)\b"),
        "message": "map().flatten() / map().compact() (an intermediate array)",
        "suggestion": (
            "use flat_map or filter_map; the intermediate array is allocated and walked only to be thrown away"
        ),
    },
    {
        "id": "GL038",
        # Code shape, not embedded content: a match inside a string literal is
        # documentation or a fixture, not the pattern. See _blank_strings.
        "code_only": True,
        "langs": {".jsx", ".tsx"},
        "severity": "low",
        "pattern": re.compile(r"\w+=\{(?:\(\)\s*=>|\{)"),
        "message": "inline function or object literal passed as a JSX prop",
        "suggestion": (
            "a new function/object is allocated every render, defeating memo/PureComponent; hoist it with "
            "useCallback/useMemo or move it outside the component"
        ),
    },
]

RULES_BY_ID = {r["id"]: r for r in RULES}

# The rules `scan_file` dispatches by name rather than by pattern.
AST_RULE_IDS = frozenset({"GL001", "GL007", "GL018", "GL023", "GL030", "GL031"})


def _pattern_rules_by_lang() -> dict[str, list[Rule]]:
    """Pattern rules bucketed by the language tag they target.

    Built once, because the alternative is asking every rule whether it applies
    to every file: ~50 `applicable()` calls per file, of which all but a handful
    answer no. A scan of a large tree spent more time on that question than on
    several of the rules.
    """
    index: dict[str, list[Rule]] = {}
    for rule in RULES:
        if rule["pattern"] is None or rule["id"] in AST_RULE_IDS:
            continue
        langs: list[str] = rule["langs"]
        for lang in langs:
            index.setdefault(lang, []).append(rule)
    return index


PATTERN_RULES_BY_LANG = _pattern_rules_by_lang()

# Every language tag any rule mentions, for `scannable()`.
SCANNABLE_LANGS: frozenset[str] = frozenset(lang for rule in RULES for lang in cast("list[str]", rule["langs"]))


