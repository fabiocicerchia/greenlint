#!/usr/bin/env python3
"""greenlint — static analysis for energy-wasteful patterns.

Rules are regex+context based and language-tagged; the rule set is the
product and grows over time. Every finding explains *why it wastes energy*
and what to do instead.

  greenlint src/
  greenlint --list-rules
  greenlint src/ --format json --fail-on-findings
  greenlint . --exclude '*/vendor/*' --exclude '*/dist/*'
"""

import argparse
import ast
import fnmatch
import functools
import hashlib
import json
import os
import re
import sys
import tomllib
from collections import deque
from pathlib import Path

CONFIG_FILENAME = ".greenlint.toml"
BASELINE_FILENAME = ".greenlint-baseline.json"

# Order-of-magnitude steers for which findings are worth fixing first — not
# measurements. Two anchors make them checkable rather than plausible-sounding:
#
#   1 gCO2e ~= 500 seconds of one busy CPU core   (see core_seconds_per_gram)
#   1 GB transferred ~= 15 gCO2e                  (~0.03 kWh/GB x grid)
#
# Where a rule saves a real physical quantity — an instance-day, a GB pulled,
# a GB-month stored — the hint is a number. Where it saves a few microseconds
# per call, it is *not*: a function call costs nanojoules, so any per-call gram
# figure is fiction. Those hints state the scaling instead, which is the thing
# that actually decides whether the rule is worth acting on.
#
# Everything here is wildly workload-dependent. Treat as relative, not exact.
#
# Every figure below is one of these constants times a stated assumption, and
# each hint carries that arithmetic as a comment. Where a constant is published
# the source is linked; where it is derived the derivation is the whole of it.
#
#   480 gCO2e/kWh — published. World average power-sector intensity for 2023:
#     "CO2 intensity reached a new record low of 480 gCO2/kWh, down 1.2% from
#     486 gCO2/kWh in 2022" — Ember, Global Electricity Review 2024. It is on
#     the "Electricity transition in 2023" chapter, not the report landing page:
#     https://ember-energy.org/latest-insights/global-electricity-review-2024/electricity-transition-in-2023/
#     The figure drifts a few percent a year (486 in 2022, 480 in 2023, 473 in
#     2024), which is far inside the error bars on everything below. 480 is also
#     what the sibling carbon-badge tool uses, and the two agreeing matters more
#     here than either tracking the latest annual revision.
#   0.03 kWh/GB transferred — derived. Aslan et al. 2018 measured 0.06 kWh/GB
#     for 2015 fixed-line transmission, halving roughly every 2 years, which
#     puts the network alone well under 0.01 today; 0.03 is that plus its share
#     of data-centre and CDN energy. https://doi.org/10.1111/jiec.12630
#   0.65 Wh/TBh stored — published. "0.65 Watt-Hours per Terabyte-Hour for HDD"
#     — Cloud Carbon Footprint (CCF below), methodology, under "Storage"; CCF is
#     an open-source cloud-emissions estimator. They follow Etsy's
#     Cloud Jewels method but re-derive the coefficient for 2020 from the 2016
#     U.S. Data Center Usage Report. (Cloud Jewels' own older HDD figure is
#     higher; this is the one on the page linked.)
#     https://www.cloudcarbonfootprint.org/docs/methodology/
#   1.135-1.56 PUE — published. Hyperscale is the low end (Cloud Carbon
#     Footprint quotes 1.135 for AWS, 1.1 for GCP, 1.125 for Azure); the
#     industry-wide average is 1.56, flat for five years (Uptime Institute,
#     Global Data Center Survey 2024).
#     https://uptimeinstitute.com/resources/research-and-reports/uptime-institute-global-data-center-survey-results-2024
#   15 W per busy core — derived from the two above. Cloud Carbon Footprint's
#     AWS coefficient is 3.5 W per vCPU at 100% CPU; a vCPU is one hyperthread,
#     so a fully loaded physical core is ~7 W of silicon. x PUE that is 8 W
#     hyperscale, 11 W at the industry average, and the core's share of memory,
#     storage, network and idle host draw is on top — CCF meters those
#     separately, we do not. 15 W is the round number above that band, chosen
#     deliberately: it makes every compute figure below the generous end of
#     plausible rather than the mean.
#     The sibling carbon-badge tool prices a busy core at ~4.7 W, which looks
#     like the two disagreeing 3x. They do not. It starts from Eco-CI's
#     SPECpower curve for the one machine GitHub runs CI on (2.05 W/vCPU
#     against CCF's cross-fleet 3.5 — a 1.7x spread between two published
#     sources), and it knows those jobs ran on Azure, so it takes the
#     hyperscale PUE and no safety margin. It is measuring a known machine; we
#     are bounding an unknown one. Do not port its constant here, or ours
#     there. See its docs/assumptions.md, "Reconciling with greenlint".
GRID_INTENSITY_G_PER_KWH = 480.0
BUSY_CORE_WATTS = 15.0
KWH_PER_GB_TRANSFERRED = 0.03
G_CO2E_PER_GB = KWH_PER_GB_TRANSFERRED * GRID_INTENSITY_G_PER_KWH  # 14.4, quoted as ~15


def core_seconds_per_gram(grid_g_per_kwh=GRID_INTENSITY_G_PER_KWH, watts=BUSY_CORE_WATTS):
    """Seconds of one busy CPU core that add up to 1 gCO2e.

    The sanity check behind every hint below: at 480 gCO2e/kWh a gram is 7.5 kJ,
    which is ~500 seconds of a 15 W core. Any rule claiming ~0.001 gCO2e per
    call is therefore claiming half a core-second per call — which is why the
    per-call hints below describe scaling rather than quoting a figure.
    """
    joules_per_gram = 3_600_000 / grid_g_per_kwh
    return joules_per_gram / watts


# Shared phrasing for costs too small to quote per occurrence.
_HOT_PATH = "negligible per call; ~1 gCO2e per 500 core-seconds of work removed"

CO2E_HINTS = {
    # --- Compute left running: real instance-hours, so real numbers. ---
    # One instance model behind all of these, so they stay comparable instead of
    # each carrying its own invented watt band:
    #   busy vCPU  7.5 W = BUSY_CORE_WATTS / 2 (a vCPU is one hyperthread)
    #   idle vCPU  1.6 W = CCF's 0.74 W idle x the same ~2.1 overhead factor
    #   a typical instance here is 4-16 vCPU; a cluster node 8-32
    # Each hint is then (watts freed) x (hours) x 0.48 gCO2e/Wh.
    "GL001": "~150-200 gCO2e/day per instance (one core pegged continuously)",  # 15 W x 24 h
    # Polling denies the core its deep C-states without loading it, so the cost
    # sits inside the 1.6 -> 7.5 W idle-to-busy span; 1-3 W x 24 h.
    "GL002": "~10-40 gCO2e/day per instance (wake-ups blocking CPU idle states)",
    # Runtime / 500, so no invented band: a 2 core-second job x 1440 runs/day is
    # 2880 core-seconds, ~6 gCO2e. Widening to */5 removes 80% of that.
    "GL003": "~1 gCO2e per 500 core-seconds of runtime; a 2 s job x 1440 runs/day is ~6 gCO2e/day",
    # Downsizing frees the idle vCPUs it was paying for: 4-16 x 1.6 W x 24 h.
    "GL008": "~70-300 gCO2e/day per oversized instance (4-16 vCPU of idle capacity)",
    # One extra node is one extra 8-32 vCPU VM idling: 13-51 W x 24 h.
    "GL014": "~150-600 gCO2e/day if it forces one extra node; nothing if the cluster has slack",
    # 0.4 x a 4-16 vCPU instance at ~50% load (4.6 W/vCPU) x 24 h. AWS publishes
    # "up to 60% less energy for the same performance"
    # (https://aws.amazon.com/ec2/graviton/); independent benchmarks land nearer
    # 45-50%, so 40% is the conservative end.
    "GL016": "~80-350 gCO2e/day per instance (ARM draws roughly 40% less for equal work)",
    # The whole 4-16 vCPU instance idling, x ~16 non-working hours.
    "GL024": "~50-200 gCO2e/day per instance left running outside working hours",
    # The one figure here with no model behind it: io1/io2 draw somewhat more per
    # IOP than gp3, but by how much is a guess. 1-10 gCO2e/day is 0.1-0.9 W.
    "GL025": "~1-10 gCO2e/day per volume (marginally higher draw per IOP; weakly grounded)",
    "GL033": "~50-200 gCO2e/day per replica left running outside working hours",  # as GL024
    "GL034": "~150-600 gCO2e/day if it forces one extra host; nothing if the host has slack",
    # --- Storage: per GB-month. ---
    # 0.65 Wh/TBh x 730 h x 0.48 gCO2e/Wh / 1000 GB = 0.23 gCO2e per GB-month of
    # spinning disk, x ~1.5 for erasure-coded durability (stored bytes, not
    # logical bytes) x ~1.5 PUE (the coefficient is drive-level) = ~0.5.
    "GL013": "~0.5 gCO2e per GB per month left in hot storage",
    "GL026": "~0.5 gCO2e per GB per month of logs retained",
    # --- Transfer: GB x 0.03 kWh x 480 gCO2e/kWh = 14.4, quoted as ~15 gCO2e/GB.
    # The size of the payload is then the whole story. ---
    "GL004": "~15 gCO2e per GB of history; a 200 MB repo is ~3 gCO2e per clone avoided",
    "GL006": "~15 gCO2e per GB not transferred, per pull",
    "GL009": "~15 gCO2e per GB of recommended packages avoided, per pull",
    "GL010": "~15 gCO2e per GB of cached wheels not baked into the image, per pull",
    "GL011": "~15 gCO2e per GB; a 200 KB unseen image is ~0.003 gCO2e per page view",  # 0.0002 GB
    "GL015": "~15 gCO2e per GB, per pull (older runtimes are usually larger)",
    # 5 MB GIF -> ~0.5 MB MP4, so 0.0045 GB saved
    "GL017": "~15 gCO2e per GB saved; a 5 MB GIF as MP4 is ~0.07 gCO2e per view",
    "GL027": "~15 gCO2e per GB re-fetched that a cache header would have avoided",
    "GL029": "~15 gCO2e per GB in the avoidable layer, per pull",
    # --- Hot-path micro-costs: scaling, not fictional per-call grams. ---
    # No per-occurrence arithmetic to give: the only number that applies is the
    # anchor, 1 gCO2e per 500 core-seconds (see core_seconds_per_gram).
    "GL005": f"~15 gCO2e per GB of columns never read; {_HOT_PATH}",
    "GL007": f"allocation and GC churn; {_HOT_PATH}",
    "GL012": f"one round trip per row instead of one per query; {_HOT_PATH}",
    "GL018": "grows as n squared; passes ~1 gCO2e once the extra work reaches ~500 core-seconds",
    "GL019": f"network wait and a remote CPU wake per call; {_HOT_PATH}",
    "GL020": f"string work done even when the level is disabled; {_HOT_PATH}",
    "GL021": f"10-100x the interpreter work of a vectorised op; {_HOT_PATH}",
    "GL022": f"reopening and rereading per iteration; {_HOT_PATH}",
    "GL023": "n squared instead of n log n; passes ~1 gCO2e once the extra work reaches ~500 core-seconds",
    "GL028": f"modules loaded and bound at every start; {_HOT_PATH}",
    "GL030": f"building and discarding half a tuple per iteration; {_HOT_PATH}",
    "GL031": f"raising and unwinding on every pass; {_HOT_PATH}",
    "GL032": f"repeated allocator overhead per iteration; {_HOT_PATH}",
    "GL035": f"full enumeration where a short-circuit would do; {_HOT_PATH}",
    "GL036": f"an O(n) scan where a hash lookup is O(1); {_HOT_PATH}",
    "GL037": f"two passes over the collection instead of one; {_HOT_PATH}",
    "GL038": f"extra allocation and a defeated memoisation per render; {_HOT_PATH}",
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
        "suggestion": "ARM-based instances (t4g/m6g/c6g/r6g) draw roughly 40% less for equal work; AWS publishes 'up to 60% less energy', independent benchmarks land nearer 45-50%, so 40% is the conservative end",
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
    ".go": _SLASH,
    ".js": _SLASH,
    ".ts": _SLASH,
    ".jsx": _SLASH,
    ".tsx": _SLASH,
    ".c": _SLASH,
    ".h": _SLASH,
    ".cpp": _SLASH,
    ".cc": _SLASH,
    ".hpp": _SLASH,
    ".java": _SLASH,
    ".rs": _SLASH,
    ".kt": _SLASH,
    ".swift": _SLASH,
    ".cs": _SLASH,
    ".php": _SLASH,
    ".scala": _SLASH,
    ".sql": ("--", ("/*", "*/")),
    ".py": ("#", None),
    ".sh": ("#", None),
    ".bash": ("#", None),
    ".rb": ("#", None),
    ".yml": ("#", None),
    ".yaml": ("#", None),
    ".tf": ("#", None),
    ".tofu": ("#", None),
    ".toml": ("#", None),
    ".pl": ("#", None),
    ".dockerfile": ("#", None),
}


# Everything but a newline, for blanking a span while keeping offsets and line
# numbers pointing at the real file.
_NOT_NEWLINE = re.compile(r"[^\n]")


def _blank_spans(text, spans):
    """Replace each `(start, end)` span with spaces, newlines kept.

    Spliced from slices rather than edited character by character: the blanked
    regions are a small fraction of a file, and `re.sub` does the per-character
    part in C. Nothing to blank means the original string is handed straight
    back, with nothing allocated at all.
    """
    if not spans:
        return text
    pieces, prev = [], 0
    for start, end in spans:
        pieces.append(text[prev:start])
        pieces.append(_NOT_NEWLINE.sub(" ", text[start:end]))
        prev = end
    pieces.append(text[prev:])
    return "".join(pieces)


@functools.cache
def _comment_scanners(line_tok, block):
    """(outside-a-string, {quote: inside-that-string}) jump patterns.

    Outside a string the only characters that matter are a quote, a line
    comment token and a block opener — a newline resets nothing, since there is
    no open quote to reset. Inside one, only the closing quote, a backslash and
    a newline. Alternation order matters: the old loop tested quotes before
    comment tokens, and at a position that could be either, `re` takes the
    first alternative, so the order here keeps that precedence.

    Cached because there is one pattern per language, not one per file.
    """
    alternatives = ["[\"']", re.escape(line_tok)]
    if block:
        alternatives.append(re.escape(block[0]))
    outside = re.compile("|".join(alternatives))
    inside = {quote: re.compile(f"[\\n\\\\{quote}]") for quote in "\"'"}
    return outside, inside


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
    # Two C-speed substring searches before any character-at-a-time work: a
    # file with no comment token in it has nothing to blank, and in a scan of a
    # real tree that is a large share of the files. The loop below is the only
    # part of a scan whose cost is per character rather than per match.
    if line_tok not in text and not (block and block[0] in text):
        return text
    # Spans to blank, rather than a mutable copy of the file: `list(text)` is
    # one pointer per character — 8 bytes of list for every byte of source —
    # allocated for every file scanned, and thrown away by the join.
    # Jump between the characters that can change anything instead of visiting
    # every one. Source is overwhelmingly ordinary code: on the standard
    # library this loop ran once per character and was the single largest cost
    # in a scan. `re` does the skipping in C; the Python below still runs once
    # per interesting position, and the decisions it makes are unchanged.
    outside, inside = _comment_scanners(line_tok, block)
    spans = []
    i, n, quote = 0, len(text), None
    while i < n:
        if quote:
            match = inside[quote].search(text, i)
            if match is None:
                break
            i = match.start()
            ch = text[i]
            if ch == "\n":
                quote = None
            elif ch == "\\":
                # A trailing backslash is a line continuation, not an escape of
                # the newline we use to resynchronise.
                if i + 1 < n and text[i + 1] != "\n":
                    i += 1
            else:  # the closing quote
                quote = None
            i += 1
            continue
        match = outside.search(text, i)
        if match is None:
            break
        i = match.start()
        ch = text[i]
        if ch in "\"'":
            if ch == "'" and 0 < i < n - 1 and text[i - 1].isalpha() and text[i + 1].isalpha():
                i += 1  # don't / it's / won't
                continue
            quote = ch
            i += 1
            continue
        if text.startswith(line_tok, i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            spans.append((i, end))
            i = end
            continue
        end = text.find(block[1], i + len(block[0]))
        end = n if end == -1 else end + len(block[1])
        spans.append((i, end))
        i = end
    return _blank_spans(text, spans)


def _blank_python_docstrings(code, index):
    """Blank module/class/function docstrings, preserving offsets.

    A docstring is prose, and prose about a pattern is not the pattern — the
    same reason comments are blanked. Ordinary string literals are left alone:
    `q = "SELECT * FROM t"` is a real query.

    Reads its docstring holders off the shared index rather than walking the
    tree for them, so a Python file is traversed once for this and every AST
    rule together.
    """
    holders = [index.tree, *index.functions, *index.classes]
    spans = []
    starts = None
    for node in holders:
        doc = node.body[0] if node.body else None
        if not (
            isinstance(doc, ast.Expr)
            and isinstance(doc.value, ast.Constant)
            and isinstance(doc.value.value, str)
        ):
            continue
        if starts is None:
            # Only built once a docstring is actually found: a file with none
            # (every generated or one-liner module in a tree) pays nothing.
            starts, off = [], 0
            for line in code.splitlines(keepends=True):
                starts.append(off)
                off += len(line)
        start = starts[doc.lineno - 1] + doc.col_offset
        end = starts[doc.end_lineno - 1] + doc.end_col_offset
        spans.append((start, min(end, len(code))))
    # Docstrings come off the index in traversal order, which is not file
    # order once functions nest; splicing needs them left to right.
    spans.sort()
    return _blank_spans(code, spans)


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


# The same boundaries `SCOPE_BOUNDARIES` names, as a set of exact types for the
# indexing pass — which tests `type(node) in ...` rather than `isinstance`.
_SCOPE_KINDS = frozenset((ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef))


class PythonIndex:
    """The nodes every Python AST rule needs, collected in one traversal.

    Six rules each called `ast.walk(tree)` to pick out the handful of node
    types they care about, so a scan walked each file's tree six times over.
    Profiling a 4,000-file scan put ~65% of the entire run inside
    `ast.iter_child_nodes`, which was that redundancy and nothing else.

    `enclosing` is the other half: the rules that ask "is this inside a loop?"
    used to answer it by walking the subtree of every loop, which is quadratic
    in nesting depth. Carrying the loop stack down during the one traversal
    answers the same question by looking up.
    """

    __slots__ = ("classes", "fors", "functions", "loop_scopes", "tree", "tries", "whiles")

    def __init__(self, tree):
        self.tree = tree
        # (node, enclosing loops) pairs, outermost first.
        self.fors = []
        self.whiles = []
        self.tries = []
        self.functions = []
        self.classes = []
        # Scopes containing at least one loop of their own. A scope with none
        # cannot produce a GL007 finding, and most functions have none, so this
        # is what lets that rule skip them without walking them to find out.
        self.loop_scopes = set()


def index_python(tree):
    """Build a `PythonIndex` from one breadth-first pass.

    Breadth-first because that is `ast.walk`'s order, and the rules used to
    read their nodes from `ast.walk` — keeping it means each rule still sees
    its nodes in the order it always did.
    """
    index = PythonIndex(tree)
    queue = deque([(tree, (), tree)])
    while queue:
        node, loops, scope = queue.popleft()
        kind = type(node)
        # Exact types, not isinstance: `AsyncFor` and `TryStar` are siblings of
        # `For` and `Try` rather than subclasses, and the rules never matched
        # them. This keeps that true rather than quietly widening them.
        if kind is ast.For:
            index.fors.append((node, loops))
            index.loop_scopes.add(scope)
            loops = (*loops, node)
        elif kind is ast.While:
            index.whiles.append((node, loops))
            index.loop_scopes.add(scope)
            loops = (*loops, node)
        elif kind is ast.Try:
            index.tries.append((node, loops))
        elif kind is ast.FunctionDef or kind is ast.AsyncFunctionDef:
            index.functions.append(node)
        elif kind is ast.ClassDef:
            index.classes.append(node)
        # A nested def/class/lambda starts a scope of its own, which is the
        # boundary `_walk_own` respects and the one GL007 judges names against.
        child_scope = node if kind in _SCOPE_KINDS else scope
        for child in ast.iter_child_nodes(node):
            queue.append((child, loops, child_scope))
    return index


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


def _walk_own_loops(node):
    """`_walk_own`, pairing each node with the loops enclosing it in this scope.

    Same reason `PythonIndex` carries a loop stack: asking "is this statement
    inside a loop?" by re-walking the subtree of every loop is quadratic in
    nesting, and the answer is already known on the way down.
    """
    stack = [(node, ())]
    while stack:
        cur, loops = stack.pop()
        yield cur, loops
        inner = (*loops, cur) if isinstance(cur, (ast.For, ast.While)) else loops
        for child in ast.iter_child_nodes(cur):
            if isinstance(child, SCOPE_BOUNDARIES):
                continue
            stack.append((child, inner))


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


def _ast_busy_loop_findings(path, index):
    """AST-based replacement for GL001 on Python: the regex version flags
    `while True:` unless "sleep" appears *anywhere* in the file, which both
    misses loops whose sleep is in an unrelated function and flags loops that
    do sleep but happen to share a file with the word "sleep" elsewhere.
    Walking the loop body directly for a real sleep call fixes both.
    """
    rule = RULES_BY_ID["GL001"]
    for node, _ in index.whiles:
        if not (isinstance(node.test, ast.Constant) and node.test.value is True):
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


def _ast_nested_loop_findings(path, index):
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
    for node, enclosing in index.fors:
        if not isinstance(node.iter, ast.Name) or node.lineno in seen:
            continue
        if any(
            type(outer) is ast.For
            and isinstance(outer.iter, ast.Name)
            and outer.iter.id == node.iter.id
            for outer in enclosing
        ):
            seen.add(node.lineno)
            yield _finding(rule, path, node.lineno)


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


def _ast_bubble_sort_findings(path, index):
    """GL023: a `for` loop nested inside another `for` loop whose body
    contains an element swap — the textbook shape of a hand-rolled bubble or
    selection sort.
    """
    rule = RULES_BY_ID["GL023"]
    seen = set()
    for node, enclosing in index.fors:
        if node.lineno in seen or not any(type(outer) is ast.For for outer in enclosing):
            continue
        if any(_is_tuple_swap(stmt) for stmt in ast.walk(node)):
            seen.add(node.lineno)
            yield _finding(rule, path, node.lineno)


def _ast_dict_iterator_findings(path, index):
    """GL030: `for k, v in d.items()` where the key or the value is discarded
    (bound to `_`) — the discarded half didn't need building/unpacking at all.
    """
    rule = RULES_BY_ID["GL030"]
    for node, _ in index.fors:
        if not (isinstance(node.target, ast.Tuple) and len(node.target.elts) == 2):
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
        return isinstance(node.value, (int, float, complex)) and not isinstance(node.value, bool)
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

    def classify(target, value):
        # Unpacking binds each name to its own initialiser, so pair the sides
        # up rather than judging the tuple as a whole: `mwh, grams = 0.0, 0.0`
        # is two counters, and reading only single-name targets left both
        # unclassified — which flagged `mwh += r` as a rebuild.
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
            if len(target.elts) == len(value.elts):
                for t, v in zip(target.elts, value.elts, strict=True):
                    classify(t, v)
            return
        if not isinstance(target, ast.Name):
            return
        if isinstance(value, (ast.List, ast.ListComp)):
            lists.add(target.id)
        elif (
            isinstance(value, ast.Constant)
            and isinstance(value.value, (int, float))
            and not isinstance(value.value, bool)
        ):
            scalars.add(target.id)

    for node in nodes:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            classify(target, node.value)
    return lists, scalars


def _ast_quadratic_rebuild_findings(path, index):
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
    scopes = [index.tree, *index.functions]
    for scope in scopes:
        # A scope with no loop of its own cannot produce a finding here, and
        # most functions have none — so it is never walked at all.
        if scope not in index.loop_scopes:
            continue
        # One walk per scope, not one per scope plus one per loop in it: every
        # statement already knows which loops it sits inside.
        own = list(_walk_own_loops(scope))
        list_names, scalar_names = _names_bound_to_lists(node for node, _ in own)
        for stmt, enclosing in own:
            if not enclosing:
                continue
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
                isinstance(value, (ast.List, ast.ListComp)) or target.id in list_names
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


def _ast_try_in_loop_findings(path, index):
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
    for stmt, enclosing in index.tries:
        if not enclosing or stmt.lineno in seen:
            continue
        swallowed = any(
            all(isinstance(b, (ast.Pass, ast.Continue)) for b in h.body) for h in stmt.handlers
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
    body = text[jobs.end() :]
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


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def finding_sort_key(finding):
    """Sort key putting the findings worth fixing first. Named and exported so
    a front end that assembles its own list — the editor extension merging a
    freshly scanned buffer into a cached project scan — orders it the way the
    CLI would rather than inventing a second ordering.
    """
    return (SEVERITY_ORDER[finding["severity"]], finding["file"], finding["line"])


def applicable(rule, path):
    """Return True if the rule targets the file's language/extension."""
    if path.name == "Dockerfile" and "Dockerfile" in rule["langs"]:
        return True
    return path.suffix in rule["langs"]


def fingerprint(finding, root):
    """Stable id for a finding, for the baseline to name it by.

    Line-insensitive, so it survives every edit above it — the same shape the
    sibling gandalf tool uses, for the same reason: a baseline keyed on line
    numbers is stale by the next commit.

    The path is stored relative to the baseline file, because the two callers
    disagree about paths otherwise: `greenlint .` in CI reports `src/db.py`
    and the editor reports `/home/you/proj/src/db.py`, and a baseline only
    earns its keep if both honour it.

    greenlint's messages are fixed per rule, so this is in practice one id per
    (file, rule): accepting `SELECT *` in `src/db.py` accepts every occurrence
    in that file, and a later one is accepted too. That is the cost of not
    keying on lines, and it is the right way round — a baseline exists to stop
    old findings nagging, not to be a precise inventory.
    """
    try:
        relative = Path(finding["file"]).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        relative = Path(finding["file"]).as_posix()
    key = f"{relative}|{finding['rule']}|{finding['message']}"
    return hashlib.sha1(key.encode("utf-8", "replace"), usedforsecurity=False).hexdigest()


def load_baseline(path):
    """Accepted fingerprints from a baseline file. Missing or unreadable is an
    empty baseline: a linter that stops reporting because a file it was not
    asked about is malformed would be worse than one that reports too much.
    """
    p = Path(path)
    if not p.is_file():
        return set()
    try:
        with p.open("rb") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    return set(data.get("fingerprints") or [])


def apply_baseline(findings, baseline, root):
    """Findings that the baseline does not already accept."""
    if not baseline:
        return findings
    return [f for f in findings if fingerprint(f, root) not in baseline]


def write_baseline(path, findings, root):
    """Snapshot every current finding so later runs stay quiet about them.
    Returns how many distinct ones were recorded."""
    fingerprints = sorted({fingerprint(f, root) for f in findings})
    Path(path).write_text(json.dumps({"version": 1, "fingerprints": fingerprints}, indent=2) + "\n")
    return len(fingerprints)


def scannable(path):
    """True if any rule targets this file's language at all.

    Derived from `RULES` rather than a hardcoded extension list, so a rule for
    a new language brings its files into scope automatically. `scan_file()` on
    a file no rule targets yields nothing, so this only ever skips work — which
    is why the editor extension checks it before reading a file that a project
    scan just walked past. The CLI does not: reading a PNG and matching nothing
    is wasted I/O, but changing what the CLI touches is a bigger decision than
    making the editor's background scan cheap.
    """
    return any(applicable(rule, path) for rule in RULES)


def scan_file(path, disabled=frozenset(), text=None):
    """Yield findings for every enabled rule that matches the file's contents.

    `text` supplies the contents instead of reading them, for callers that
    already hold them — an editor scanning an unsaved buffer, say. `path` is
    still what picks the language, so it must be the name the buffer will be
    saved under. Without this an editor has to write a temp file per keystroke
    to get a scan, which is a lot of disk churn for a tool about not wasting
    energy.
    """
    if text is None:
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
    # Indexed once and shared, for the same reason the tree is parsed once: the
    # docstring pass and all six AST rules want the same handful of node types.
    index = index_python(tree) if tree is not None else None
    if index is not None:
        code = _blank_python_docstrings(code, index)
    # Rules about long-lived loops, applied to test code, only ever produce
    # noise: a test's tight wait is bounded by the test run and is the point.
    if _is_test_file(path):
        disabled = disabled | {"GL001", "GL002", "GL007"}
    ast_rules = {"GL001", "GL007", "GL018", "GL023", "GL030", "GL031"}
    if ast_rules - disabled and index is not None:
        if "GL001" not in disabled:
            yield from _ast_busy_loop_findings(path, index)
        if "GL007" not in disabled:
            yield from _ast_quadratic_rebuild_findings(path, index)
        if "GL018" not in disabled:
            yield from _ast_nested_loop_findings(path, index)
        if "GL023" not in disabled:
            yield from _ast_bubble_sort_findings(path, index)
        if "GL030" not in disabled:
            yield from _ast_dict_iterator_findings(path, index)
        if "GL031" not in disabled:
            yield from _ast_try_in_loop_findings(path, index)
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


def _matches_any(rel, ignore):
    """Match a posix path string against ignore globs.

    Tried both as given and with a leading `/`. `greenlint .` produces
    `tests/x.py`, which `*/tests/*` cannot match — so the obvious way to write
    an ignore glob silently did nothing, including in greenlint's own
    .greenlint.toml. Trying both keeps bare patterns like `tests/*` working too.
    """
    forms = (rel, rel if rel.startswith("/") else "/" + rel)
    return any(fnmatch.fnmatch(s, pat) for pat in ignore for s in forms)


def is_ignored(path, config=None):
    """True if an `ignore` glob covers this path.

    Its own function because a walk is not the only caller: the editor
    extension scans one open buffer at a time, and a file the CLI ignores must
    not sprout squiggles just because it was reached by being opened rather
    than by being walked to.
    """
    ignore = (config or {}).get("ignore") or []
    if not ignore:
        return False
    return _matches_any(Path(path).as_posix(), ignore)


def prunable_bases(ignore):
    """The `<base>` of every ignore glob shaped `<base>/*`, which are the only
    ones a walk can act on before descending.

    `<base>/*` covers everything below `<base>`, because fnmatch's `*` crosses
    `/` — so a directory matching `<base>` can be skipped whole. Nothing else
    can: `*/vendor/*.py` covers only part of the directory, and `*/vendor`
    covers the directory entry itself but nothing inside it. Getting this wrong
    in the permissive direction would silently stop scanning files that are not
    ignored, so the test is on the shape of the pattern rather than on a guess
    about what it might match.
    """
    bases = []
    for pattern in ignore:
        stripped = pattern.rstrip("*")
        if stripped != pattern and stripped.endswith("/") and len(stripped) > 1:
            bases.append(stripped[:-1])
    return bases


# Directories that are never worth walking into: version-control internals and
# installed dependencies, neither of which is code anyone here is writing.
PRUNED_DIR_NAMES = frozenset({".git", "node_modules"})


def walk_files(root, prune_bases=()):
    """Yield every file under `root`, never descending into a pruned directory.

    `Path.rglob("*")` walks the whole tree and leaves the caller to filter, so
    `.git` and `node_modules` were listed in full and then thrown away — the two
    directories most likely to contain more files than the project does. This
    skips them at the directory, so they are never read.

    Symlinked directories are not followed and symlinked files are yielded,
    which is what `rglob` did.
    """
    stack = [Path(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    child = current / entry.name
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in PRUNED_DIR_NAMES:
                            continue
                        if prune_bases and _matches_any(child.as_posix(), prune_bases):
                            continue
                        stack.append(child)
                    elif entry.is_file():
                        yield child
        except OSError:
            continue  # unreadable directory: nothing to scan and nothing to say


def iter_files(paths, config=None):
    """Yield every file under `paths` that the config does not ignore.

    Split out of `scan()` so that other front ends — the editor extension in
    `extensions/vscode/`, which walks the tree itself to cache per file — select
    exactly the same files the CLI does. Two copies of this logic would drift,
    and a file the CLI ignores still being flagged in the editor is the kind of
    disagreement nobody debugs, they just stop trusting the tool.
    """
    config = config or {"disable": set(), "ignore": []}
    prune_bases = prunable_bases(config["ignore"])
    for root in paths:
        p = Path(root)
        files = iter([p]) if p.is_file() else walk_files(p, prune_bases)
        for f in files:
            if is_ignored(f, config):
                continue
            yield f


def scan(paths, config=None):
    """Scan files/directories and return findings sorted by severity."""
    config = config or {"disable": set(), "ignore": []}
    findings = []
    for f in iter_files(paths, config):
        findings.extend(scan_file(f, config["disable"]))
    findings.sort(key=finding_sort_key)
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
    args = p.parse_args(argv)

    if args.list_rules:
        for r in RULES:
            print(
                f"{r['id']} [{r['severity']:6s}] ({', '.join(sorted(r['langs']))}): {r['message']}"
            )
        return 0

    config = load_config(args.config)
    if args.exclude:
        config["ignore"] = [*config["ignore"], *args.exclude]
    findings = scan(args.paths or ["."], config)

    if args.write_baseline:
        path = Path(args.write_baseline)
        count = write_baseline(path, findings, path.parent)
        print(f"greenlint: {count} finding(s) accepted in {path}")
        return 0

    # An explicit --baseline must exist; the default one is used when it happens
    # to be there. A typo in a flag should be an error, not a silent no-op.
    baseline_path = Path(args.baseline) if args.baseline else Path(BASELINE_FILENAME)
    if args.baseline and not baseline_path.is_file():
        raise SystemExit(f"greenlint: no such baseline: {baseline_path}")
    before = len(findings)
    findings = apply_baseline(findings, load_baseline(baseline_path), baseline_path.parent)
    accepted = before - len(findings)
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
        accepted_note = f" ({accepted} accepted by {baseline_path})" if accepted else ""
        print(f"\ngreenlint: {len(findings)} finding(s){accepted_note}")
    return 1 if findings and args.fail_on_findings else 0


if __name__ == "__main__":
    sys.exit(main())
