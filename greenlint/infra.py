"""The rules that read infrastructure files rather than source."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from .base import Finding
from .comments import _is_go_template
from .findings import _finding
from .rules import RULES_BY_ID

# -------------------------------------------------- infrastructure rules ---


def _tf_resource_blocks(text: str, resource_type: str) -> Iterator[tuple[re.Match[str], str, int]]:
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


def _tf_s3_lifecycle_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL013: an `aws_s3_bucket` resource block with no lifecycle rule anywhere
    inside it.
    """
    rule = RULES_BY_ID["GL013"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_s3_bucket"):
        if "lifecycle" not in block.lower():
            yield _finding(rule, path, lineno)


def _tf_asg_static_size_findings(path: Path, text: str) -> Iterator[Finding]:
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


def _tf_log_retention_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL026: an `aws_cloudwatch_log_group` with no `retention_in_days` set —
    logs are kept forever by default.
    """
    rule = RULES_BY_ID["GL026"]
    for _, block, lineno in _tf_resource_blocks(text, "aws_cloudwatch_log_group"):
        if "retention_in_days" not in block:
            yield _finding(rule, path, lineno)


def _dockerfile_layer_bloat_findings(path: Path, text: str) -> Iterator[Finding]:
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
    seen_stages: set[int] = set()
    for pos in installs:
        stage = sum(1 for s in stage_starts if s < pos)
        if stage in seen_stages:
            yield _finding(rule, path, text.count("\n", 0, pos) + 1)
        seen_stages.add(stage)


def _k8s_resources_findings(path: Path, text: str) -> Iterator[Finding]:
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


def _k8s_hpa_static_findings(path: Path, text: str) -> Iterator[Finding]:
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


def _bracketing(starts: list[int], pos: int, low: int, high: int) -> tuple[int, int]:
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


def _fetch_depth_findings(path: Path, text: str) -> Iterator[Finding]:
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


def _compose_resources_findings(path: Path, text: str) -> Iterator[Finding]:
    """GL034: a docker-compose/swarm file (`services:` top-level key) with no
    resource limit anywhere in the file — neither the Swarm-mode
    `deploy.resources` block nor the classic `mem_limit`/`cpus` keys.
    """
    rule = RULES_BY_ID["GL034"]
    m = re.search(r"^services:\s*$", text, re.MULTILINE)
    if m and not re.search(r"mem_limit|nano_cpus|cpus\s*:|memory\s*:", text):
        yield _finding(rule, path, text.count("\n", 0, m.start()) + 1)
