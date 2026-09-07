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

# Annotations are evaluated lazily: several helpers are typed against
# PythonIndex, which is defined further down beside the traversal it holds.
from __future__ import annotations

import argparse
import ast
import bisect
import fnmatch
import functools
import hashlib
import json
import os
import re
import sys
import tomllib
from collections import deque
from collections.abc import Iterator
from pathlib import Path, PurePath
from typing import Any

# A rule as the RULES table declares it, and a finding as the reporters consume
# it. Both are dicts because the table is written as literals and every reader
# does a `.get` on the optional keys.
Rule = dict[str, Any]
Finding = dict[str, Any]
# A parsed `.greenlint.toml`: {"disable": set[str], "ignore": list[str]}.
Config = dict[str, Any]

CONFIG_FILENAME = ".greenlint.toml"
BASELINE_FILENAME = ".greenlint-baseline.json"

# ----------------------------------------------------- carbon arithmetic ---

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
# A swap and a two-name unpack are both exactly two targets.
PAIR = 2

GRID_INTENSITY_G_PER_KWH = 480.0
BUSY_CORE_WATTS = 15.0
KWH_PER_GB_TRANSFERRED = 0.03
G_CO2E_PER_GB = KWH_PER_GB_TRANSFERRED * GRID_INTENSITY_G_PER_KWH  # 14.4, quoted as ~15


def core_seconds_per_gram(grid_g_per_kwh: float = GRID_INTENSITY_G_PER_KWH, watts: float = BUSY_CORE_WATTS) -> float:
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
    # Quoting the vendor: "up to 60% less energy for the same performance".
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
    # --- Added coverage for C#, Kotlin, Swift and Ruby (see docs/rules.md) ---
    "GL039": "a TLS handshake and a new connection per call, CPU on both ends",
    "GL040": f"a pool thread parked, and the pool grown to replace it; {_HOT_PATH}",
    "GL041": f"a whole collection allocated to walk it once; {_HOT_PATH}",
    "GL042": "work that outlives its caller: CPU spent on a result nobody reads",
    "GL043": f"two passes and an intermediate list instead of one pass; {_HOT_PATH}",
    "GL044": f"a real thread parked for the duration of the coroutine; {_HOT_PATH}",
    "GL045": f"two passes and an intermediate array instead of one pass; {_HOT_PATH}",
    "GL046": f"a thread blocked and idle until the block returns; {_HOT_PATH}",
    "GL047": "a dropped connection pool, so a handshake per request",
    "GL048": "quadratic in the string built; passes ~1 gCO2e once the extra work reaches ~500 core-seconds",
    "GL049": f"one round trip and one remote query plan per row; {_HOT_PATH}",
    "GL050": f"an intermediate collection allocated and discarded; {_HOT_PATH}",
}

# ----------------------------------------------------------------- rules ---

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
    index = {}
    for rule in RULES:
        if rule["pattern"] is None or rule["id"] in AST_RULE_IDS:
            continue
        for lang in rule["langs"]:
            index.setdefault(lang, []).append(rule)
    return index


PATTERN_RULES_BY_LANG = _pattern_rules_by_lang()

# Every language tag any rule mentions, for `scannable()`.
SCANNABLE_LANGS = frozenset(lang for rule in RULES for lang in rule["langs"])


# --------------------------------------------------------- configuration ---


def _as_list(value: Any, key: str) -> list[str]:
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
            f'greenlint: {CONFIG_FILENAME}: `{key}` must be a list, not a string — write `{key} = ["{value}"]`'
        )
    return [str(v) for v in value]


def load_config(path: str | None = None) -> Config:
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


# ----------------------------------------------------- comment stripping ---

# Line- and block-comment syntax per extension. Dockerfile/unknown default to `#`.
_SLASH = ("//", ("/*", "*/"))
COMMENT_SYNTAX = {
    # CSS and HTML carry rules but had no entry at all. Both are listed with a
    # None line-comment form because neither language has one: `//` in CSS
    # would eat the rest of any line containing `url(http://…)`, which is a
    # worse bug than the gap it closes.
    ".css": (None, ("/*", "*/")),
    ".html": (None, ("<!--", "-->")),
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


def _blank_spans(text: str, spans: list[tuple[int, int]]) -> str:
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
def _comment_scanners(line_tok: str, block: tuple[str, str] | None) -> tuple:
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


def _step_in_string(text: str, i: int, quote: str, inside: bool) -> tuple:
    """Advance past the next character that can close the string open at `i`.

    Returns the offset to resume from and the quote still open — None once the
    string closed — or `(None, None)` when nothing can close it before EOF.
    """
    match = inside[quote].search(text, i)
    if match is None:
        return None, None
    i = match.start()
    ch = text[i]
    if ch == "\\":
        # A trailing backslash is a line continuation, not an escape of the
        # newline we use to resynchronise.
        if i + 1 < len(text) and text[i + 1] != "\n":
            i += 1
        return i + 1, quote
    # A newline resets the tracking; anything else here is the closing quote.
    return i + 1, None


def _is_apostrophe(text: str, i: int) -> bool:
    """True for the `'` in don't / it's / won't — a letter either side of it."""
    return 0 < i < len(text) - 1 and text[i - 1].isalpha() and text[i + 1].isalpha()


def _step_outside_string(text: str, i: int, outside: bool, line_tok: str, block: tuple[str, str] | None) -> tuple:
    """Advance to the next string opener or comment at or after `i`.

    Returns the offset to resume from, the quote now open (None when the stop
    was a comment) and the comment's span to blank (None when it was a quote).
    `(None, None, None)` means nothing interesting is left in the file.
    """
    n = len(text)
    while True:
        match = outside.search(text, i)
        if match is None:
            return None, None, None
        i = match.start()
        ch = text[i]
        if ch in "\"'":
            if ch == "'" and _is_apostrophe(text, i):
                i += 1
                continue
            return i + 1, ch, None
        if text.startswith(line_tok, i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            return end, None, (i, end)
        end = text.find(block[1], i + len(block[0]))
        end = n if end == -1 else end + len(block[1])
        return end, None, (i, end)


def _blank_comments(text: str, path: str) -> str:
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
    line_tok, block = COMMENT_SYNTAX.get(path.suffix, ("#", None) if path.name == "Dockerfile" else (None, None))
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
            i, quote = _step_in_string(text, i, quote, inside)
        else:
            i, quote, span = _step_outside_string(text, i, outside, line_tok, block)
            if span is not None:
                spans.append(span)
        if i is None:
            break
    return _blank_spans(text, spans)


# Languages whose string literals are worth blanking before a code-structure
# rule looks at them. Everything here uses C-style quoting; a language whose
# quoting rules differ enough to need its own scanner is better served by
# leaving its strings visible (a false negative) than by a scanner that
# desynchronises (false positives everywhere after the first mistake).
_STRING_LANGS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".mjs",
        ".cjs",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".swift",
        ".ts",
        ".tsx",
    }
)

# Opening a string, or the end of the line that resynchronises the scan.
_STRING_OPEN = re.compile(r"[\"'`\n]")


def _no_strings_to_blank(code: str, path: str) -> bool:
    """True when this file cannot gain from blanking its strings.

    Either its language has no C-style quoting, or it holds no quote character
    at all — in a real tree that is a large share of the files. Same reasoning
    as the comment scanner's substring pre-check.
    """
    return path.suffix not in _STRING_LANGS or ('"' not in code and "'" not in code and "`" not in code)


def _string_end(code: str, i: int, quote: str) -> int:
    """Offset of the character that ends the literal whose body starts at `i`.

    A backslash escapes the next character; a newline ends the scan without
    closing the literal, which is what stops one mistake desynchronising the
    rest of the file.
    """
    n = len(code)
    while i < n:
        ch = code[i]
        if ch == "\\" and i + 1 < n and code[i + 1] != "\n":
            i += 2  # an escaped character, including \" and \'
            continue
        if ch in ("\n", quote):
            break
        i += 1
    return i


def _step_to_string_end(code: str, i: int) -> tuple:
    """Advance past the next string literal at or after `i`.

    Returns where to resume and the span to blank — `(None, None)` when nothing
    is left, and `(next_i, None)` for a character that opens no literal.
    """
    match = _STRING_OPEN.search(code, i)
    if match is None:
        return None, None
    i = match.start()
    quote = code[i]
    # A newline only resynchronises the scan, and an apostrophe between two
    # letters is a contraction rather than an opening quote — the same trap
    # `_blank_comments` documents. Getting either wrong opens a string that
    # never closes and blanks the rest of the line.
    if quote == "\n" or (quote == "'" and _is_apostrophe(code, i)):
        return i + 1, None
    end = _string_end(code, i + 1, quote)
    # Past the closing quote, or onto the newline that resynchronises us.
    resume = end + 1 if end < len(code) and code[end] == quote else end
    return resume, (i + 1, end) if end > i + 1 else None


def _blank_strings(code: str, path: str) -> str:
    """Return `code` with string-literal bodies replaced by spaces.

    Offsets and newlines are preserved, exactly as `_blank_comments` preserves
    them, so line numbers still point at the real file.

    This is applied ONLY to rules marked `code_only` — those whose pattern
    describes the shape of the code rather than something embedded in it. The
    distinction is the whole point: `SELECT * FROM t` in a Go file is *always*
    inside a string literal and is a real query, while `sleep(0.01)` inside a
    string is documentation, a test fixture, or a code sample, and reporting it
    is the false positive this exists to remove.

    Quote state resets at every newline, like the comment scanner, so a
    multi-line string keeps its contents visible to the rules. That is a false
    negative, which is the safe direction — a linter that cries wolf gets
    switched off, and this whole pass exists because of that.
    """
    if _no_strings_to_blank(code, path):
        return code
    spans = []
    i, n = 0, len(code)
    while i < n:
        i, span = _step_to_string_end(code, i)
        if i is None:
            break
        if span is not None:
            spans.append(span)
    return _blank_spans(code, spans)


def _blank_python_docstrings(code: str, index: PythonIndex) -> str:
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
        if not (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str)):
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


def _is_go_template(text: str) -> bool:
    """True for a Helm/Go-template YAML file. What such a file *renders to* is
    what matters, and greenlint does not render it — so manifest rules that ask
    "is key X present" cannot answer honestly here.
    """
    return "{{" in text and "}}" in text


# -------------------------------------------------------------- findings ---

# `foo_test.go`, `test_foo.py`, `foo.test.ts`, `foo.spec.ts`.
TEST_FILENAME = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.|_spec\.)", re.IGNORECASE)


def _is_test_file(path: str) -> bool:
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


class _LineIndex:
    """`line_of(offset)` -> 1-based line number, over an index built at most once.

    `text.count("\\n", 0, offset)` per match rescans the file from the top, so a
    file the same rule matches a thousand times was read a thousand times over —
    quadratic, and the files that hit it (generated SQL, bundled JS) are exactly
    the large ones. The index is built on the first call, so the overwhelming
    majority of files, which match nothing, pay nothing for it.
    """

    __slots__ = ("_starts", "_text")

    def __init__(self, text: str) -> None:
        self._text = text
        self._starts = None

    def line_of(self, offset: int) -> int:
        if self._starts is None:
            starts = []
            pos = self._text.find("\n")
            while pos != -1:
                starts.append(pos)
                pos = self._text.find("\n", pos + 1)
            self._starts = starts
        # bisect_left: newlines strictly before the offset, which is what
        # `count` reported for a match starting on the newline itself.
        return bisect.bisect_left(self._starts, offset) + 1


def _finding(rule: Rule, path: str, line: int) -> dict:
    """Build one finding from the rule that fired.

    Every field a consumer sees is assembled here — the JSON output, the
    editor extension and the baseline fingerprint all read this shape, so a
    rule can never emit a finding that is missing its *why* or its
    suggestion.
    """
    return {
        "rule": rule["id"],
        "severity": rule["severity"],
        "file": str(path),
        "line": line,
        "message": rule["message"],
        "suggestion": rule["suggestion"],
        "co2e_estimate": CO2E_HINTS.get(rule["id"], ""),
    }


# ------------------------------------------------------ python AST index ---


def _parse_python(path: str, text: str) -> ast.AST | None:
    """Parse `text` into an AST, or None on a syntax error. Shared by every
    AST-based Python rule so each file is only parsed once per scan.
    """
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError:
        return None


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

    def __init__(self, tree: ast.AST) -> None:
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


# One collector per node kind the index cares about, each returning the loop
# stack and the scope its children are in. A nested def/class/lambda starts a
# scope of its own, which is the boundary `_walk_own` respects and the one GL007
# judges names against; everything else leaves both untouched, which is the
# `collect is None` path in the walk below and by far the commonest one.


def _collect_for(index: PythonIndex, node: ast.AST, loops: tuple[ast.AST, ...], scope: str) -> tuple:
    index.fors.append((node, loops))
    index.loop_scopes.add(scope)
    return (*loops, node), scope


def _collect_while(index: PythonIndex, node: ast.AST, loops: tuple[ast.AST, ...], scope: str) -> tuple:
    index.whiles.append((node, loops))
    index.loop_scopes.add(scope)
    return (*loops, node), scope


def _collect_try(index: PythonIndex, node: ast.AST, loops: tuple[ast.AST, ...], scope: str) -> tuple:
    index.tries.append((node, loops))
    return loops, scope


def _collect_function(index: PythonIndex, node: ast.AST, loops: tuple[ast.AST, ...], scope: str) -> tuple:
    index.functions.append(node)
    return loops, node


def _collect_class(index: PythonIndex, node: ast.AST, loops: tuple[ast.AST, ...], scope: str) -> tuple:
    index.classes.append(node)
    return loops, node


def _collect_lambda(index: PythonIndex, node: ast.AST, loops: tuple[ast.AST, ...], scope: str) -> tuple:
    return loops, node


_COLLECTORS = {
    ast.For: _collect_for,
    ast.While: _collect_while,
    ast.Try: _collect_try,
    ast.FunctionDef: _collect_function,
    ast.AsyncFunctionDef: _collect_function,
    ast.ClassDef: _collect_class,
    ast.Lambda: _collect_lambda,
}


def index_python(tree: ast.AST) -> PythonIndex:
    """Build a `PythonIndex` from one breadth-first pass.

    Breadth-first because that is `ast.walk`'s order, and the rules used to
    read their nodes from `ast.walk` — keeping it means each rule still sees
    its nodes in the order it always did.

    The child walk is spelled out rather than left to `ast.iter_child_nodes`,
    which is two nested generators and a `try/except` per node, and it stays
    inline rather than becoming a helper: this is the one place in greenlint
    that runs tens of millions of times in a real scan — it was 20 of 36 seconds
    on the standard library — and a call plus a list per node costs 13% of a
    stdlib scan (11.96 s → 13.54 s, five runs each, `make bench`).
    """
    index = PythonIndex(tree)
    queue = deque([(tree, (), tree)])
    pop = queue.popleft
    push = queue.append
    while queue:
        node, loops, scope = pop()
        # Exact types, not isinstance: `AsyncFor` and `TryStar` are siblings of
        # `For` and `Try` rather than subclasses, and the rules never matched
        # them. This keeps that true rather than quietly widening them.
        collect = _COLLECTORS.get(type(node))
        if collect is None:
            child_scope = scope
        else:
            loops, child_scope = collect(index, node, loops, scope)
        # Expressions are not descended into: Python has no expression that can
        # contain a statement, so none of the kinds `_COLLECTORS` names can be
        # inside one. That is most of a syntax tree — every name, call, constant
        # and operator — skipped rather than queued and rejected.
        for name in node._fields:
            value = getattr(node, name, None)
            if type(value) is list:
                for item in value:
                    if isinstance(item, ast.AST) and not isinstance(item, ast.expr):
                        push((item, loops, child_scope))
            elif isinstance(value, ast.AST) and not isinstance(value, ast.expr):
                push((value, loops, child_scope))
    return index


# A nested function, lambda or class body is its own scope: its statements and
# its name bindings belong to it, not to the code that encloses it.
SCOPE_BOUNDARIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _walk_own(node: ast.AST) -> Iterator[ast.AST]:
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


def _walk_own_loops(node: ast.AST) -> Iterator[ast.AST]:
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


def _loop_can_exit(loop: ast.AST) -> bool:
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


def _nearest_loop(root: str, target: ast.AST) -> ast.AST | None:
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


# ------------------------------------------------------ python AST rules ---


def _calls_sleep(node: ast.AST) -> bool:
    """True when `node` is a call to something named `sleep` — `time.sleep(x)`,
    `asyncio.sleep(x)` or a bare `sleep(x)` pulled in by `from time import`.
    """
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Attribute) and node.func.attr == "sleep")
        or (isinstance(node.func, ast.Name) and node.func.id == "sleep")
    )


def _ast_busy_loop_findings(path: str, index: PythonIndex) -> list[Finding]:
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
        sleeps = any(_calls_sleep(n) for body_node in node.body for n in ast.walk(body_node))
        if sleeps or _loop_can_exit(node):
            continue
        yield _finding(rule, path, node.lineno)


def _ast_nested_loop_findings(path: str, index: PythonIndex) -> list[Finding]:
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
            type(outer) is ast.For and isinstance(outer.iter, ast.Name) and outer.iter.id == node.iter.id
            for outer in enclosing
        ):
            seen.add(node.lineno)
            yield _finding(rule, path, node.lineno)


def _is_tuple_swap(stmt: ast.stmt) -> bool:
    """True for the idiomatic Python swap `a[i], a[j] = a[j], a[i]` — two
    subscripts assigned from two subscripts. That shape only shows up when
    someone is hand-rolling an in-place swap, i.e. a manual sort.
    """
    return (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Tuple)
        and len(stmt.targets[0].elts) == PAIR
        and all(isinstance(e, ast.Subscript) for e in stmt.targets[0].elts)
        and isinstance(stmt.value, ast.Tuple)
        and len(stmt.value.elts) == PAIR
        and all(isinstance(e, ast.Subscript) for e in stmt.value.elts)
    )


def _ast_bubble_sort_findings(path: str, index: PythonIndex) -> list[Finding]:
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


def _ast_dict_iterator_findings(path: str, index: PythonIndex) -> list[Finding]:
    """GL030: `for k, v in d.items()` where the key or the value is discarded
    (bound to `_`) — the discarded half didn't need building/unpacking at all.
    """
    rule = RULES_BY_ID["GL030"]
    for node, _ in index.fors:
        if not (isinstance(node.target, ast.Tuple) and len(node.target.elts) == PAIR):
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
SCALAR_CALLS = frozenset({"len", "sum", "int", "float", "round", "abs", "ord", "timedelta", "Decimal"})
# Operators that only numbers support, so an expression using one is numeric.
SCALAR_OPS = (ast.Div, ast.FloorDiv, ast.Sub, ast.Mod, ast.Pow)

# Operators no sequence defines, so a name appearing as an operand of one is
# certainly a number. `+` and `*` are shared with str/bytes/tuple/list, and `%`
# is str formatting, so none of those three prove anything and none are here.
NUMERIC_ONLY_OPS = (ast.Sub, ast.Div, ast.FloorDiv, ast.Pow, ast.MatMult)


def _note_numeric(numeric: set[str], node: ast.AST) -> None:
    """Record `node`'s name in `numeric`, when `node` is a plain name."""
    if isinstance(node, ast.Name):
        numeric.add(node.id)


def _scalar_assign_targets(node: ast.AST) -> set[str]:
    """The targets of an assignment whose value is certainly numeric.

    A name *assigned* arithmetic is as numeric as one used in it, and this is
    the commoner shape: `day = start - (start % DAY)` then `day += DAY` in the
    loop. Reading only operands left the target of the seed unclassified,
    because it never appears beside an operator itself.
    """
    if not _is_scalar_expr(node.value):
        return ()
    return tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,)


def _numeric_operands(node: ast.AST) -> set[str]:
    """The sub-expressions this node proves are numeric, or `()` for none."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, NUMERIC_ONLY_OPS):
        return (node.left, node.right)
    if isinstance(node, ast.AugAssign) and isinstance(node.op, NUMERIC_ONLY_OPS):
        return (node.target,)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return (node.operand,)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return _scalar_assign_targets(node)
    return ()


def _names_used_as_numbers(nodes: list[ast.AST]) -> set[str]:
    """Names that arithmetic elsewhere in this scope proves are numeric.

    `_names_bound_to_lists` can only classify a name it watched being
    initialised to a literal, and a counter seeded from something opaque — a
    parameter, a call, another name — tells it nothing. `y = top` then
    `y += row_height(r) + gap` inside a loop therefore read as a sequence
    rebuild, which is how this rule fired on the layout arithmetic of an SVG
    renderer.

    A scope that walks a coordinate almost always does arithmetic on it that
    only numbers support, and one `y - gap` or `-y` settles the question. This
    infers nothing the operators do not already guarantee: `s - 1` on the str
    that GL007 exists to catch is a TypeError, so no genuine rebuild is hidden.
    """
    numeric = set()
    for node in nodes:
        for operand in _numeric_operands(node):
            _note_numeric(numeric, operand)
    return numeric


def _is_scalar_expr(node: ast.AST) -> bool:
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


def _classify_binding(target: ast.AST, value: Any, lists: set[str], scalars: dict[str, Any]) -> None:
    """Record `target` in `lists` or `scalars`, judged from the shape of `value`."""
    # Unpacking binds each name to its own initialiser, so pair the sides
    # up rather than judging the tuple as a whole: `mwh, grams = 0.0, 0.0`
    # is two counters, and reading only single-name targets left both
    # unclassified — which flagged `mwh += r` as a rebuild.
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
        if len(target.elts) == len(value.elts):
            for element, initialiser in zip(target.elts, value.elts, strict=True):
                _classify_binding(element, initialiser, lists, scalars)
        return
    if not isinstance(target, ast.Name):
        return
    if isinstance(value, (ast.List, ast.ListComp)):
        lists.add(target.id)
    elif (
        isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) and not isinstance(value.value, bool)
    ):
        scalars.add(target.id)


def _names_bound_to_lists(nodes: list[ast.AST]) -> tuple:
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
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            _classify_binding(target, node.value, lists, scalars)
    return lists, scalars


def _accumulating_add(stmt: ast.stmt) -> str | None:
    """(target, value) when `stmt` accumulates onto a plain name with `+`/`+=`,
    else (None, None).

    Only `x += <expr>` and `x = x + <expr>`: `x = y + z` rebinds rather than
    accumulates, and a non-name target (`d[k] += …`) is not a name to track.
    """
    if isinstance(stmt, ast.AugAssign) and isinstance(stmt.op, ast.Add):
        target, value = stmt.target, stmt.value
    elif (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.value, ast.BinOp)
        and isinstance(stmt.value.op, ast.Add)
    ):
        target, value = stmt.targets[0], stmt.value
        left = stmt.value.left
        if not (isinstance(left, ast.Name) and left.id == getattr(target, "id", None)):
            return None, None
    else:
        return None, None
    return (target, value) if isinstance(target, ast.Name) else (None, None)


def _is_sequence_rebuild(stmt: ast.stmt, list_names: set[str], scalar_names: set[str]) -> bool:
    """True when `stmt` copies the whole sequence built so far — the O(n^2) shape."""
    target, value = _accumulating_add(stmt)
    if target is None:
        return False
    # A numeric counter (`total += 1`, `seen += len(chunk)`, `kwh +=
    # watts * hours / 1000`) accumulates in O(1) — not a rebuild.
    if _is_scalar_expr(value) or target.id in scalar_names:
        return False
    # `xs += ...` is `list.extend` when xs is a list: in place, O(k), no copy.
    # Either the list literal on the right proves it (`+=` a list is a
    # TypeError for str/bytes/tuple), or the name was seen being initialised to
    # one. Only the rebinding form (`xs = xs + [a]`) copies everything
    # accumulated so far.
    return not (
        isinstance(stmt, ast.AugAssign) and (isinstance(value, (ast.List, ast.ListComp)) or target.id in list_names)
    )


def _ast_quadratic_rebuild_findings(path: str, index: PythonIndex) -> list[Finding]:
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
        scalar_names |= _names_used_as_numbers(node for node, _ in own)
        for stmt, enclosing in own:
            if not enclosing:
                continue
            if not isinstance(stmt, (ast.AugAssign, ast.Assign)) or stmt.lineno in seen:
                continue
            if _is_sequence_rebuild(stmt, list_names, scalar_names):
                seen.add(stmt.lineno)
                yield _finding(rule, path, stmt.lineno)


# Conversions whose failure is routinely used as a type test, where a
# non-throwing check exists (`.isdigit()`, a regex, a guard).
PROBE_CALLS = frozenset({"int", "float", "complex", "Decimal"})


def _has_cheap_alternative(body: str) -> bool:
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


def _ast_try_in_loop_findings(path: str, index: PythonIndex) -> list[Finding]:
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
        swallowed = any(all(isinstance(b, (ast.Pass, ast.Continue)) for b in h.body) for h in stmt.handlers)
        if swallowed and _has_cheap_alternative(stmt.body):
            seen.add(stmt.lineno)
            yield _finding(rule, path, stmt.lineno)


# -------------------------------------------------- infrastructure rules ---


def _tf_resource_blocks(text: str, resource_type: str) -> list[tuple[int, str]]:
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


def _tf_s3_lifecycle_findings(path: str, text: str) -> list[Finding]:
    """GL013: an `aws_s3_bucket` resource block with no lifecycle rule anywhere
    inside it.
    """
    rule = RULES_BY_ID["GL013"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_s3_bucket"):
        if "lifecycle" not in block.lower():
            yield _finding(rule, path, lineno)


def _tf_asg_static_size_findings(path: str, text: str) -> list[Finding]:
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


def _tf_log_retention_findings(path: str, text: str) -> list[Finding]:
    """GL026: an `aws_cloudwatch_log_group` with no `retention_in_days` set —
    logs are kept forever by default.
    """
    rule = RULES_BY_ID["GL026"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_cloudwatch_log_group"):
        if "retention_in_days" not in block:
            yield _finding(rule, path, lineno)


def _dockerfile_layer_bloat_findings(path: str, text: str) -> list[Finding]:
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


def _k8s_resources_findings(path: str, text: str) -> list[Finding]:
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


def _k8s_hpa_static_findings(path: str, text: str) -> list[Finding]:
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
    # super-linter belongs here too: with VALIDATE_ALL_CODEBASE off it lints
    # the diff against the default branch, which it cannot compute from a
    # shallow clone.
    r"|gandalf|merge-base|super-linter"
    # Docs builds that stamp a "last updated" date per page read each file's
    # own commit history — mkdocs-material's git-revision-date-localized, and
    # the git-committers/git-authors plugins alongside it. A shallow clone
    # gives them nothing to read, so they fall back to the build date and
    # every page claims to have changed today.
    r"|git-revision-date|git-committers|git-authors",
    re.IGNORECASE,
)


def _job_starts(text: str, body_at: int) -> list[int]:
    """Offsets where each entry under `jobs:` begins, empty when unsegmentable."""
    body = text[body_at:]
    # The first key under `jobs:` sets the indent at which a sibling job starts.
    first = re.search(r"^([ \t]+)[\w-]+:[ \t]*$", body, re.MULTILINE)
    if not first:
        return []
    return [
        body_at + m.start() for m in re.finditer(rf"^{re.escape(first.group(1))}[\w-]+:[ \t]*$", body, re.MULTILINE)
    ]


def _bracketing(starts: list[int], pos: int, low: int, high: int) -> tuple:
    """The two `starts` either side of `pos`, falling back to `low` and `high`."""
    before = [s for s in starts if s <= pos]
    after = [s for s in starts if s > pos]
    return (before[-1] if before else low), (after[0] if after else high)


def _job_span(text: str, pos: int) -> tuple[int, int]:
    """(start, end) of the `jobs:` entry containing `pos`, or the whole file.

    Crude on purpose — indentation, not a YAML parse, because greenlint has no
    YAML dependency and this only needs to find a block boundary. Any workflow
    it cannot segment falls back to the whole file, which is what the rule did
    everywhere before.
    """
    jobs = re.search(r"^jobs:[ \t]*$", text, re.MULTILINE)
    if not jobs or pos < jobs.end():
        return 0, len(text)
    starts = _job_starts(text, jobs.end())
    if not starts:
        return 0, len(text)
    return _bracketing(starts, pos, jobs.end(), len(text))


def _fetch_depth_findings(path: str, text: str) -> list[Finding]:
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


def _compose_resources_findings(path: str, text: str) -> list[Finding]:
    """GL034: a docker-compose/swarm file (`services:` top-level key) with no
    resource limit anywhere in the file — neither the Swarm-mode
    `deploy.resources` block nor the classic `mem_limit`/`cpus` keys.
    """
    rule = RULES_BY_ID["GL034"]
    m = re.search(r"^services:\s*$", text, re.MULTILINE)
    if m and not re.search(r"mem_limit|nano_cpus|cpus\s*:|memory\s*:", text):
        yield _finding(rule, path, text.count("\n", 0, m.start()) + 1)


# ------------------------------------------------ ordering and baselines ---

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def finding_sort_key(finding: Finding) -> tuple:
    """Sort key putting the findings worth fixing first. Named and exported so
    a front end that assembles its own list — the editor extension merging a
    freshly scanned buffer into a cached project scan — orders it the way the
    CLI would rather than inventing a second ordering.
    """
    return (SEVERITY_ORDER[finding["severity"]], finding["file"], finding["line"])


def applicable(rule: Rule, path: str) -> bool:
    """Return True if the rule targets the file's language/extension."""
    if path.name == "Dockerfile" and "Dockerfile" in rule["langs"]:
        return True
    return path.suffix in rule["langs"]


def fingerprint(finding: Finding, root: str) -> str:
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


def load_baseline(path: str) -> set[str]:
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


def apply_baseline(findings: list[Finding], baseline: set[str], root: str) -> list[Finding]:
    """Findings that the baseline does not already accept."""
    if not baseline:
        return findings
    return [f for f in findings if fingerprint(f, root) not in baseline]


def write_baseline(path: str, findings: list[Finding], root: str) -> None:
    """Snapshot every current finding so later runs stay quiet about them.
    Returns how many distinct ones were recorded."""
    fingerprints = sorted({fingerprint(f, root) for f in findings})
    Path(path).write_text(json.dumps({"version": 1, "fingerprints": fingerprints}, indent=2) + "\n")
    return len(fingerprints)


# -------------------------------------------------------------- scanning ---


def scannable(path: str) -> bool:
    """True if any rule targets this file's language at all.

    Derived from `RULES` rather than a hardcoded extension list, so a rule for
    a new language brings its files into scope automatically. Every rule — the
    pattern ones, the AST ones and the per-format ones — is selected by suffix
    or by the name `Dockerfile`, so a file this returns False for cannot produce
    a finding whatever it contains. `scan_file` leans on that to return before
    reading it, and the editor extension before asking about it at all.

    A set lookup rather than a pass over `RULES`: this is asked once per file in
    a walk, and the answer only ever depended on the set of tags.
    """
    return path.suffix in SCANNABLE_LANGS or (path.name == "Dockerfile" and "Dockerfile" in SCANNABLE_LANGS)


# The AST rules, in the order their findings come out, wired to the ids
# `AST_RULE_IDS` names. Each takes the shared per-file index, never its own walk.
AST_FINDERS = (
    ("GL001", _ast_busy_loop_findings),
    ("GL007", _ast_quadratic_rebuild_findings),
    ("GL018", _ast_nested_loop_findings),
    ("GL023", _ast_bubble_sort_findings),
    ("GL030", _ast_dict_iterator_findings),
    ("GL031", _ast_try_in_loop_findings),
)

# The rules that need a whole resource block rather than one match, keyed the
# way `PATTERN_RULES_BY_LANG` is: the suffix, or `Dockerfile` by name. Tags that
# mean the same format share one tuple, the way the pattern index aliases them.
BLOCK_FINDERS = {
    ".tf": (
        ("GL013", _tf_s3_lifecycle_findings),
        ("GL024", _tf_asg_static_size_findings),
        ("GL026", _tf_log_retention_findings),
    ),
    ".yml": (
        ("GL014", _k8s_resources_findings),
        ("GL033", _k8s_hpa_static_findings),
        ("GL034", _compose_resources_findings),
    ),
    "Dockerfile": (("GL029", _dockerfile_layer_bloat_findings),),
}
BLOCK_FINDERS[".tofu"] = BLOCK_FINDERS[".tf"]
BLOCK_FINDERS[".yaml"] = BLOCK_FINDERS[".yml"]
BLOCK_FINDERS[".dockerfile"] = BLOCK_FINDERS["Dockerfile"]


def _lang_key(path: str) -> str:
    """The tag the rule indexes are keyed by: the suffix, or `Dockerfile` by name."""
    return "Dockerfile" if path.name == "Dockerfile" else path.suffix


def _context_findings(
    path: str, text: str, code: str, index: PythonIndex, disabled: frozenset[str]
) -> Iterator[Finding]:
    """Findings from the checks that read whole-file or whole-block context
    instead of matching one regex — the AST rules, and the per-format ones that
    look for the *absence* of a key.
    """
    if index is not None and not disabled >= AST_RULE_IDS:
        for rule_id, finder in AST_FINDERS:
            if rule_id not in disabled:
                yield from finder(path, index)
    # GL004 takes `text`, not `code`: it reads comments deliberately, to tell a
    # real `fetch-depth: 0` from one being discussed in a comment above it.
    if path.suffix in (".yml", ".yaml") and "GL004" not in disabled:
        yield from _fetch_depth_findings(path, text)
    for rule_id, finder in BLOCK_FINDERS.get(_lang_key(path), ()):
        if rule_id not in disabled:
            yield from finder(path, code)


def _pattern_findings(path: str, code: str, disabled: frozenset[str]) -> list[Finding]:
    """Findings from the single-regex rules tagged for this file's language,
    looked up rather than filtered — see `_pattern_rules_by_lang`.
    """
    line_of = _LineIndex(code).line_of
    # Built once, and only if some enabled rule for this language actually wants
    # it — blanking strings costs a pass over the file, and most languages have
    # no code_only rule at all.
    code_no_strings = None
    for rule in PATTERN_RULES_BY_LANG.get(_lang_key(path), ()):
        if rule["id"] in disabled:
            continue
        view = code
        if rule.get("code_only"):
            if code_no_strings is None:
                code_no_strings = _blank_strings(code, path)
            view = code_no_strings
        for m in rule["pattern"].finditer(view):
            yield _finding(rule, path, line_of(m.start()))


def scan_file(path: str, disabled: frozenset[str] = frozenset(), text: str | None = None) -> Iterator[Finding]:
    """Yield findings for every enabled rule that matches the file's contents.

    `text` supplies the contents instead of reading them, for callers that
    already hold them — an editor scanning an unsaved buffer, say. `path` is
    still what picks the language, so it must be the name the buffer will be
    saved under. Without this an editor has to write a temp file per keystroke
    to get a scan, which is a lot of disk churn for a tool about not wasting
    energy.
    """
    # No rule targets this language, so there is nothing to find in it — and no
    # reason to read it. A checkout is full of images, lock files and minified
    # bundles that were being read in full and then matched against nothing.
    if not scannable(path):
        return
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
    yield from _context_findings(path, text, code, index, disabled)
    yield from _pattern_findings(path, code, disabled)


# -------------------------------------------------------- file discovery ---


@functools.lru_cache(maxsize=32)
def _ignore_matcher(patterns: tuple[str, ...]) -> Any:
    """One compiled regex for a whole ignore list.

    `fnmatch` per pattern per path meant a walk ran one regex match per glob per
    file — and once the editor merges in `files.exclude` and `search.exclude`
    that is a hundred of them, on every file, before anything is read. An
    alternation answers the same question in one. Cached on the patterns, of
    which there is one set per config.

    `normcase` is applied to the patterns here and to the path below, which is
    exactly what `fnmatch.fnmatch` does — and the whole of why it is slower than
    `fnmatchcase`. Dropping it would silently make ignore globs case-sensitive
    on Windows.
    """
    if not patterns:
        return None
    return re.compile("|".join(fnmatch.translate(os.path.normcase(p)) for p in patterns)).match


def _matches_any(rel: str, ignore: list[str]) -> bool:
    """Match a posix path string against ignore globs.

    Tried both as given and with a leading `/`. `greenlint .` produces
    `tests/x.py`, which `*/tests/*` cannot match — so the obvious way to write
    an ignore glob silently did nothing, including in greenlint's own
    .greenlint.toml. Trying both keeps bare patterns like `tests/*` working too.
    """
    match = _ignore_matcher(tuple(ignore))
    if match is None:
        return False
    forms = (rel,) if rel.startswith("/") else (rel, "/" + rel)
    return any(match(os.path.normcase(form)) for form in forms)


def is_ignored(path: str, config: Config | None = None) -> bool:
    """True if this path is under a pruned directory, or an `ignore` glob
    covers it.

    Its own function because a walk is not the only caller: the editor
    extension scans one open buffer at a time, and a file the CLI ignores must
    not sprout squiggles just because it was reached by being opened rather
    than by being walked to. The pruned-directory check is here for the same
    reason — the walk skips `.venv` wholesale, so a `.venv` file the editor
    asks about directly has to be skipped too, or the two disagree.
    """
    p = path if isinstance(path, PurePath) else Path(path)
    if not PRUNED_DIR_NAMES.isdisjoint(p.parts):
        return True
    ignore = (config or {}).get("ignore") or []
    if not ignore:
        return False
    return _matches_any(p.as_posix(), ignore)


def prunable_bases(ignore: list[str]) -> tuple[str, ...]:
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


# Directories that are never worth walking into: version-control internals,
# installed dependencies and tool caches, none of which is code anyone here is
# writing. A virtualenv is the expensive one — a few thousand third-party .py
# files, each read and run past every rule, which is enough to make an editor
# scan look like a hang.
#
# `site-packages` is listed as well as the venv names because a venv can be
# called anything (`env3`, `.direnv`, a conda prefix); the directory the
# packages actually land in cannot. Build outputs (`dist`, `build`, `target`)
# are deliberately absent: those names belong to real source directories often
# enough that skipping them by default would hide findings. Use `ignore` in
# .greenlint.toml for those.
PRUNED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "site-packages",
        ".tox",
        ".nox",
        ".direnv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)


def walk_files(root: str, prune_bases: tuple[str, ...] = ()) -> Iterator[str]:
    """Yield every file under `root`, never descending into a pruned directory.

    `Path.rglob("*")` walks the whole tree and leaves the caller to filter, so
    `.git` and `node_modules` were listed in full and then thrown away — the two
    directories most likely to contain more files than the project does. This
    skips them at the directory, so they are never read.

    Symlinked directories are not followed and symlinked files are yielded,
    which is what `rglob` did.
    """
    # Paths are carried as strings and `scandir` hands back the joined form for
    # free, so a `Path` is only built for the files actually yielded — not for
    # every directory entry passed over on the way there.
    stack = [os.fspath(root) or "."]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in PRUNED_DIR_NAMES:
                            continue
                        if prune_bases and _matches_any(Path(entry.path).as_posix(), prune_bases):
                            continue
                        stack.append(entry.path)
                    elif entry.is_file():
                        yield Path(entry.path)
        except OSError:
            continue  # unreadable directory: nothing to scan and nothing to say


def iter_files(paths: list[str], config: Config | None = None) -> Iterator[str]:
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


def scan(paths: list[str], config: Config | None = None) -> list[Finding]:
    """Scan files/directories and return findings sorted by severity."""
    config = config or {"disable": set(), "ignore": []}
    findings = []
    for f in iter_files(paths, config):
        findings.extend(scan_file(f, config["disable"]))
    findings.sort(key=finding_sort_key)
    return findings


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


def _print_text(findings: list[Finding], accepted: int, baseline_path: str | None) -> None:
    """`--format text`: the human report, and the count a reader looks for."""
    for f in findings:
        print(f"{f['file']}:{f['line']}: [{f['rule']}/{f['severity']}] {f['message']}")  # noqa: T201 — the tool's output
        print(f"    ↳ {f['suggestion']}")  # noqa: T201 — the tool's output
        if f["co2e_estimate"]:
            print(f"    ~ {f['co2e_estimate']}")  # noqa: T201 — the tool's output
    accepted_note = f" ({accepted} accepted by {baseline_path})" if accepted else ""
    print(f"\ngreenlint: {len(findings)} finding(s){accepted_note}")  # noqa: T201 — the tool's output


def _resolve_baseline(explicit: str | None) -> str | None:
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
