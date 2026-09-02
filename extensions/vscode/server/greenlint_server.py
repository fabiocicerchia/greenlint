"""Long-lived scan server for the greenlint VS Code extension.

Speaks newline-delimited JSON over stdin/stdout. One request per line in, one
response per line out; `id` correlates them.

Why a server at all, rather than shelling out to `greenlint --format json`:
a CLI run pays for interpreter startup, importing the module and compiling ~40
regexes before it reads a single byte — around 100 ms, every time. At one run
per save that is tolerable; at one run per keystroke it is the dominant cost
and it is pure waste. Here that happens once per session.

Three layers keep the scanning itself off the disk and off the CPU:

  stat  — a project rescan compares (mtime_ns, size) per file and skips
          unchanged ones without opening them.
  hash  — a file whose stat changed but whose bytes did not (a touch, a branch
          switch and back, a formatter that rewrote it identically) reuses its
          cached findings without running a single rule.
  scan  — only what is genuinely new gets read and matched.

Everything is bounded: the cache is an LRU with a fixed entry count, files over
a size cap are skipped, and files no rule targets are never opened at all.

Ops:
  ping                                    -> {version, rules, python,
                                             severityOrder}
  languages                               -> file extensions any rule targets
  scanText   {path, text, root}           -> findings for an unsaved buffer
  scanFile   {path, root}                 -> findings for a file on disk
  scanProject{root, paths, stream}        -> findings for the whole tree, in
                                             progress-event batches when
                                             streaming, plus an end summary
  configure  {ignore:[glob,...]}          -> extra ignore globs, on top of
                                             .greenlint.toml
  writeBaseline {root}                    -> record current findings as accepted
  invalidate {paths}|{}                   -> drop cache entries (or all)
  cancel     {cancel: id}                 -> stop an in-flight project scan
"""

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import queue
import sys
import threading
import time
from collections import OrderedDict
from importlib import metadata
from pathlib import Path
from typing import ClassVar

PROTOCOL_VERSION = 1
DEFAULT_CACHE_ENTRIES = 4096
DEFAULT_MAX_FILE_BYTES = 1_000_000
# How often a project scan looks up from the files to answer the editor. Small
# enough that typing stays responsive during a full scan, large enough that the
# queue poll is not itself the workload.
INTERLEAVE_EVERY = 16
# How often a long project scan says it is still going.
PROGRESS_INTERVAL_S = 0.5


def load_greenlint(module_path=None):
    """Import greenlint, preferring an explicit path over the installed copy.

    The extension points this at the greenlint.py in the open workspace when
    there is one, so contributors editing rules see their own rules fire.
    """
    if module_path:
        path = Path(module_path)
        if path.is_dir():
            path = path / "greenlint.py"
        spec = importlib.util.spec_from_file_location("greenlint", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load greenlint from {path}")
        module = importlib.util.module_from_spec(spec)
        # Registered before exec so a module that imports itself finds it.
        sys.modules["greenlint"] = module
        spec.loader.exec_module(module)
        return module
    import greenlint

    return greenlint


# The module surface this server calls. Checked at startup rather than
# discovered when a scan fails: an older greenlint imports perfectly and then
# raises `has no attribute 'iter_files'` on the first project scan, which
# reads like a bug in the extension rather than a version to upgrade. Checking
# capabilities rather than a version number means this stays correct without
# anyone remembering to bump a floor.
REQUIRED_API = (
    "BASELINE_FILENAME",
    "CONFIG_FILENAME",
    "CO2E_HINTS",
    "RULES",
    "finding_sort_key",
    "is_ignored",
    "iter_files",
    "SEVERITY_ORDER",
    "apply_baseline",
    "load_baseline",
    "load_config",
    "scan_file",
    "scannable",
    "write_baseline",
)


def missing_api(gl):
    """Names this server needs that the loaded greenlint does not have."""
    missing = [name for name in REQUIRED_API if not hasattr(gl, name)]
    # Present but older: the buffer scan depends on the keyword, not just on
    # the function existing.
    if "scan_file" not in missing and "text" not in inspect.signature(gl.scan_file).parameters:
        missing.append("scan_file(text=)")
    return missing


def greenlint_version(gl):
    """Best-effort version string.

    greenlint carries no `__version__` — the number lives in pyproject.toml — so
    this falls back to the installed distribution's metadata, and to "unknown"
    when there is no installed distribution to ask. Which module actually got
    loaded is a separate question, answered by `module` in the ping response.
    """
    version = getattr(gl, "__version__", None)
    if version:
        return str(version)
    try:
        return metadata.version("greenlint")
    except metadata.PackageNotFoundError:
        return "unknown"


def digest(text):
    """Content fingerprint. blake2b at 16 bytes: shorter and faster than sha256,
    and this only ever answers "same bytes as last time?" — not a security claim.
    """
    return hashlib.blake2b(text.encode("utf-8", "replace"), digest_size=16).hexdigest()


def mtime(path):
    """A path's modification stamp, or None when there is nothing to stat."""
    if path is None:
        return None
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


class FindingCache:
    """Bounded LRU of per-file scan results.

    Each entry holds both stamps a lookup can present: the stat tuple (cheap,
    but wrong after a no-op write) and the content hash (exact, but costs a
    read). A hit on either returns the findings; a hit on the hash alone also
    repairs the stat stamp, so the next lookup is free again.
    """

    def __init__(self, limit=DEFAULT_CACHE_ENTRIES):
        self.limit = limit
        self.entries = OrderedDict()
        self.stat_hits = 0
        self.hash_hits = 0
        self.misses = 0

    def _touch(self, key):
        self.entries.move_to_end(key)

    def by_stat(self, key, stat_stamp):
        entry = self.entries.get(key)
        if entry is not None and entry["stat"] == stat_stamp:
            self._touch(key)
            self.stat_hits += 1
            return entry["findings"]
        return None

    def by_hash(self, key, content_hash, stat_stamp=None):
        entry = self.entries.get(key)
        if entry is not None and entry["hash"] == content_hash:
            if stat_stamp is not None:
                entry["stat"] = stat_stamp
            self._touch(key)
            self.hash_hits += 1
            return entry["findings"]
        return None

    def put(self, key, content_hash, findings, stat_stamp=None):
        self.misses += 1
        self.entries[key] = {"hash": content_hash, "stat": stat_stamp, "findings": findings}
        self._touch(key)
        while len(self.entries) > self.limit:
            self.entries.popitem(last=False)

    def drop(self, key):
        self.entries.pop(key, None)

    def clear(self):
        self.entries.clear()

    def stats(self):
        return {
            "entries": len(self.entries),
            "statHits": self.stat_hits,
            "hashHits": self.hash_hits,
            "misses": self.misses,
        }


class RunningSummary:
    """The end-of-scan totals, accumulated as the walk goes.

    Counted on the way past rather than from a list at the end, so a streaming
    scan need not keep every finding alive purely to count it — the whole point
    of streaming is that the client already has them.

    Deliberately counts and nothing else. The CO2e hints are prose about
    different physical quantities — grams per GB, grams per instance-day,
    "negligible per call" — so adding them up would produce a number with no
    unit and a false air of precision, which is the one thing this tool is
    careful not to do.
    """

    __slots__ = ("by_rule", "by_severity", "files", "total")

    def __init__(self):
        self.total = 0
        self.by_severity = {"high": 0, "medium": 0, "low": 0}
        self.by_rule = {}
        self.files = set()

    def add(self, findings):
        for finding in findings:
            self.total += 1
            severity = finding["severity"]
            self.by_severity[severity] = self.by_severity.get(severity, 0) + 1
            self.by_rule[finding["rule"]] = self.by_rule.get(finding["rule"], 0) + 1
            self.files.add(finding["file"])

    def result(self):
        return {
            "total": self.total,
            "bySeverity": self.by_severity,
            "byRule": dict(sorted(self.by_rule.items(), key=lambda kv: (-kv[1], kv[0]))),
            "files": len(self.files),
        }


class ProjectScan:
    """One walk in progress: what has been seen, found and reused so far.

    A record rather than locals so the walk, the progress event and the final
    response can each be their own function without passing eight arguments
    between them.
    """

    __slots__ = ("batch", "counts", "findings", "id", "paths", "reported", "seen",
                 "started", "stream", "summary")

    def __init__(self, request):
        root = request.get("root")
        self.id = request.get("id")
        self.paths = request.get("paths") or ([root] if root else ["."])
        self.stream = bool(request.get("stream"))
        self.started = time.perf_counter()
        self.reported = self.started
        self.seen = 0
        self.counts = {"stat": 0, "hash": 0, "scan": 0, "skip": 0}
        self.batch = []
        # Kept only when the client is not streaming. A streamed scan has
        # already handed every finding over, so holding a second copy of a large
        # tree's findings here — and sorting it — is work for a list nobody
        # reads. The summary is accumulated instead.
        self.findings = []
        self.summary = RunningSummary()

    def add(self, found):
        if not found:
            return
        self.summary.add(found)
        if not self.stream:
            self.findings.extend(found)
        self.batch.extend(found)

    def result(self, cache_stats):
        return {
            # Streaming already delivered these one batch at a time; sending
            # them again would double the cost of the thing being optimised.
            "findings": self.findings,
            "streamed": self.stream,
            "summary": self.summary.result(),
            "stats": {
                "files": self.seen,
                "reusedFromStat": self.counts["stat"],
                "reusedFromHash": self.counts["hash"],
                "scanned": self.counts["scan"],
                "skipped": self.counts["skip"],
                "ms": round((time.perf_counter() - self.started) * 1000),
                "cache": cache_stats,
            },
        }


class Server:
    def __init__(self, gl, out, cache_entries=DEFAULT_CACHE_ENTRIES):
        self.gl = gl
        self.out = out
        self.out_lock = threading.Lock()
        self.inbox = queue.Queue()
        self.cache = FindingCache(cache_entries)
        self.configs = {}
        self.config_fingerprint = None
        # Scans asked to stop, and the one currently walking. The set is pruned
        # to what can still be cancelled every time it is added to, so a cancel
        # that arrives after its scan has finished is dropped rather than kept
        # for the life of the process.
        self.cancelled = set()
        self.active_scan = None
        self.deferred = []
        # Ignore globs the client adds on top of `.greenlint.toml` — the
        # editor's own exclude list, which greenlint has no way to know about.
        self.extra_ignore = []
        self.ignore_generation = 0

    # --- transport -------------------------------------------------------

    def send(self, payload):
        line = json.dumps(payload, default=str)
        with self.out_lock:
            self.out.write(line + "\n")
            self.out.flush()

    def read_stdin(self):
        """Feed stdin lines to the inbox from a thread.

        A thread rather than `select()` because select cannot watch a pipe on
        Windows, and blocking readline releases the GIL anyway.
        """
        for line in sys.stdin:
            line = line.strip()
            if line:
                self.inbox.put(line)
        self.inbox.put(None)

    # --- config ----------------------------------------------------------

    def config_for(self, root):
        """Config for a workspace root, re-read when `.greenlint.toml` changes.

        Stat-gated rather than cached outright: one stat per request is free
        next to a scan, and "my config edit did nothing" is a bug that costs an
        afternoon. A changed config invalidates every cached finding, since
        `disable` changes what a scan would have produced — and so does a
        changed client exclude list, which is why the generation counter is
        part of the cache key.
        """
        cfg_path = Path(root) / self.gl.CONFIG_FILENAME if root else None
        base_path = Path(root) / self.gl.BASELINE_FILENAME if root else None
        stamp = mtime(cfg_path)
        key = (stamp, mtime(base_path), self.ignore_generation)
        cached = self.configs.get(root)
        if cached is not None and cached[0] == key:
            return cached[1]
        config = self.merged_config(cfg_path, stamp, base_path)
        self.drop_cache_if_rules_moved(config)
        self.configs[root] = (key, config)
        return config

    def merged_config(self, cfg_path, stamp, base_path):
        """`.greenlint.toml` plus the client's excludes, plus the baseline.

        The client's excludes are merged in rather than applied separately, so
        every path that consults `ignore` — the walk's directory pruning, a
        single buffer scan — honours them without knowing they came from
        somewhere else.
        """
        if cfg_path is not None and stamp is not None:
            config = self.gl.load_config(str(cfg_path))
        else:
            config = {"disable": set(), "ignore": []}
        return {
            "disable": config["disable"],
            "ignore": [*config["ignore"], *self.extra_ignore],
            # Not part of the fingerprint below: findings are cached unfiltered
            # and the baseline is applied on the way out, so accepting a
            # finding costs a repaint rather than a rescan.
            "baseline": self.gl.load_baseline(base_path) if base_path else set(),
            "baseline_root": base_path.parent if base_path else None,
        }

    def drop_cache_if_rules_moved(self, config):
        """Empty the finding cache when what a scan would report has changed."""
        fingerprint = digest(
            json.dumps(
                {"disable": sorted(config["disable"]), "ignore": list(config["ignore"])},
                sort_keys=True,
            )
        )
        if fingerprint != self.config_fingerprint:
            self.cache.clear()
            self.config_fingerprint = fingerprint

    # --- scanning --------------------------------------------------------

    def accepted(self, findings, config):
        """Findings the baseline has not already accepted."""
        return self.gl.apply_baseline(findings, config["baseline"], config["baseline_root"])

    def scan_text(self, path, text, config):
        if self.gl.is_ignored(path, config):
            return []
        key = str(path)
        content_hash = digest(text)
        cached = self.cache.by_hash(key, content_hash)
        if cached is not None:
            return cached
        findings = sorted(
            self.gl.scan_file(path, config["disable"], text=text), key=self.gl.finding_sort_key
        )
        self.cache.put(key, content_hash, findings)
        return findings

    def scan_path(self, path, config, max_bytes):
        """Scan one file on disk, going no further down than a hit allows.

        Returns (findings, how) where `how` is stat/hash/scan/skip — the
        extension reports the mix so the caching is observable rather than
        asserted.
        """
        key = str(path)
        # Checked before the stat: an ignored file is not scanned at all, and a
        # project walk has already filtered these out, so this only fires for a
        # single file the editor asked about directly.
        if self.gl.is_ignored(path, config):
            self.cache.drop(key)
            return [], "skip"
        try:
            info = path.stat()
        except OSError:
            self.cache.drop(key)
            return [], "skip"
        stamp = [info.st_mtime_ns, info.st_size]
        cached = self.cache.by_stat(key, stamp)
        if cached is not None:
            return cached, "stat"
        if info.st_size > max_bytes or not self.gl.scannable(path):
            self.cache.put(key, None, [], stat_stamp=stamp)
            return [], "skip"
        try:
            text = path.read_text(errors="replace")
        except OSError:
            self.cache.drop(key)
            return [], "skip"
        content_hash = digest(text)
        cached = self.cache.by_hash(key, content_hash, stat_stamp=stamp)
        if cached is not None:
            return cached, "hash"
        findings = sorted(
            self.gl.scan_file(path, config["disable"], text=text), key=self.gl.finding_sort_key
        )
        self.cache.put(key, content_hash, findings, stat_stamp=stamp)
        return findings, "scan"

    def report_progress(self, scan):
        """Say how far the walk has got, and hand over the batch when streaming.

        Not just for the progress bar: silence is the difference between a
        client waiting on a scan and a client waiting on nothing, which look
        identical from outside until one of them times out.
        """
        self.send(
            {
                "id": scan.id,
                "event": "progress",
                "files": scan.seen,
                "found": scan.summary.total,
                "batch": scan.batch if scan.stream else [],
            }
        )
        scan.batch.clear()

    def walk(self, scan, config, max_bytes):
        """Scan every file under the request's paths. True if it was cancelled."""
        for path in self.gl.iter_files(scan.paths, config):
            scan.seen += 1
            if scan.seen % INTERLEAVE_EVERY == 0:
                # A full scan must not hold the editor hostage: buffer scans
                # and cancellations are answered between batches of files.
                self.pump()
                if scan.id in self.cancelled:
                    return True
                now = time.perf_counter()
                if now - scan.reported >= PROGRESS_INTERVAL_S:
                    scan.reported = now
                    self.report_progress(scan)
            found, how = self.scan_path(path, config, max_bytes)
            scan.counts[how] += 1
            scan.add(self.accepted(found, config))
        return False

    def scan_project(self, request):
        """Walk the tree, reporting findings as they are made.

        `stream: true` turns the progress events into the delivery mechanism
        rather than a status line: each carries the findings made since the last
        one, so a panel fills as the walk goes instead of staying empty until
        the end. The final response then carries the totals and not the findings
        again — a large scan should cross the pipe once, not twice.
        """
        config = self.config_for(request.get("root"))
        scan = ProjectScan(request)
        self.active_scan = scan.id
        try:
            # Cancelled while it was still queued behind another scan.
            cancelled = scan.id in self.cancelled or self.walk(
                scan, config, request.get("maxFileBytes", DEFAULT_MAX_FILE_BYTES)
            )
        finally:
            self.active_scan = None
            self.cancelled.discard(scan.id)
        if cancelled:
            return {"cancelled": True, "findings": []}
        if scan.stream and scan.batch:
            self.report_progress(scan)  # whatever the last interval did not cover
        scan.findings.sort(key=self.gl.finding_sort_key)
        return scan.result(self.cache.stats())

    # --- dispatch --------------------------------------------------------

    def op_ping(self, request):
        """Protocol and build identity, and the ordering the client sorts by."""
        return {
            "protocol": PROTOCOL_VERSION,
            "version": greenlint_version(self.gl),
            "rules": len(self.gl.RULES),
            "python": sys.version.split()[0],
            "module": getattr(self.gl, "__file__", None),
            # The client merges findings from several scans and has to sort
            # the merged list itself. The *order* is greenlint's to decide,
            # so it is published rather than reinvented over there — and a
            # severity added here needs no change in the extension.
            "severityOrder": dict(self.gl.SEVERITY_ORDER),
        }

    def op_languages(self, request):
        """The suffixes some rule targets, so the client can skip the rest."""
        # Just the extensions, not the rule table: the client uses this to
        # avoid sending a buffer no rule would look at, and nothing else.
        return {"extensions": sorted({lang for rule in self.gl.RULES for lang in rule["langs"]})}

    def op_scan_text(self, request):
        """Scan a buffer the editor holds, saved or not."""
        config = self.config_for(request.get("root"))
        path = Path(request["path"])
        findings = self.scan_text(path, request.get("text", ""), config)
        return {"findings": self.accepted(findings, config)}

    def op_scan_file(self, request):
        """Scan one file on disk, answering from the cache where it can."""
        config = self.config_for(request.get("root"))
        max_bytes = request.get("maxFileBytes", DEFAULT_MAX_FILE_BYTES)
        found, how = self.scan_path(Path(request["path"]), config, max_bytes)
        return {"findings": self.accepted(found, config), "source": how}

    def op_configure(self, request):
        """Take the client's ignore globs; a change invalidates every cache."""
        ignore = [str(pattern) for pattern in request.get("ignore") or []]
        if ignore != self.extra_ignore:
            self.extra_ignore = ignore
            self.ignore_generation += 1
            self.configs.clear()
            self.cache.clear()
        return {"ignore": self.extra_ignore}

    def op_write_baseline(self, request):
        """Accept every finding in the tree into `.greenlint-baseline.json`."""
        root = request.get("root")
        config = self.config_for(root)
        # Scanned rather than taken from the client: the baseline has to
        # describe the tree, not whatever the panel happens to be showing,
        # and the cache makes this nearly free straight after a scan.
        findings = []
        for path in self.gl.iter_files([root], config):
            found, _ = self.scan_path(path, config, DEFAULT_MAX_FILE_BYTES)
            findings.extend(found)
        target = Path(root) / self.gl.BASELINE_FILENAME
        count = self.gl.write_baseline(target, findings, target.parent)
        self.configs.clear()
        return {"path": str(target), "accepted": count}

    def op_invalidate(self, request):
        """Drop the named paths from the cache, or the whole of it."""
        paths = request.get("paths")
        if paths:
            for path in paths:
                self.cache.drop(str(path))
        else:
            self.cache.clear()
            self.configs.clear()
        return {"cache": self.cache.stats()}

    def op_cancel(self, request):
        """Mark a scan cancelled, whether it is running or still queued."""
        target = request.get("cancel")
        if target is None:
            return {"cancelling": False}
        self.cancelled.add(target)
        # A scan can be cancelled while it is still queued — `pump` defers
        # one project scan behind another — so this cannot be limited to the
        # running one. What it can do is forget the ids that name no scan at
        # all, which is what a cancel arriving just after its scan finished
        # leaves behind.
        pending = {d.get("id") for d in self.deferred if d.get("id") is not None}
        if self.active_scan is not None:
            pending.add(self.active_scan)
        self.cancelled &= pending
        return {"cancelling": target in self.cancelled}

    # The protocol's operations, in the order the docs list them. One method per
    # op with the same signature, so adding one is a method and a row here.
    OPS: ClassVar[dict] = {
        "ping": op_ping,
        "languages": op_languages,
        "scanText": op_scan_text,
        "scanFile": op_scan_file,
        "scanProject": scan_project,
        "configure": op_configure,
        "writeBaseline": op_write_baseline,
        "invalidate": op_invalidate,
        "cancel": op_cancel,
    }

    def handle(self, request):
        """Run the method implementing this request's `op`."""
        op = request.get("op")
        try:
            handler = self.OPS[op]
        except (KeyError, TypeError):  # missing, misspelled, or not a string
            raise ValueError(f"unknown op: {op!r}") from None
        return handler(self, request)

    def parse(self, line):
        try:
            return json.loads(line)
        except ValueError as exc:
            self.send({"id": None, "ok": False, "error": f"malformed request: {exc}"})
            return None

    def dispatch(self, request):
        try:
            response = self.handle(request)
        # A bad config raises SystemExit by design in the CLI, where exiting is
        # the right answer. Here it is one failed request, not the end of the
        # session, so it comes back as an error the extension can surface.
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - reported, not swallowed
            self.send({"id": request.get("id"), "ok": False, "error": f"{exc}"})
            return
        response["id"] = request.get("id")
        response["ok"] = True
        self.send(response)

    def pump(self):
        """Answer whatever is waiting, without blocking. Called between batches
        of a project scan so interactive requests jump the queue; another
        project scan is deferred rather than nested.
        """
        while True:
            try:
                line = self.inbox.get_nowait()
            except queue.Empty:
                return
            if line is None:
                self.inbox.put(None)
                return
            request = self.parse(line)
            if request is None:
                continue
            if request.get("op") == "scanProject":
                self.deferred.append(request)
                continue
            self.dispatch(request)

    def serve(self):
        threading.Thread(target=self.read_stdin, daemon=True).start()
        self.send({"id": 0, "ok": True, "event": "ready", "protocol": PROTOCOL_VERSION})
        while True:
            if self.deferred:
                self.dispatch(self.deferred.pop(0))
                continue
            line = self.inbox.get()
            if line is None:
                break
            request = self.parse(line)
            if request is not None:
                self.dispatch(request)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="greenlint_server")
    parser.add_argument("--greenlint", help="path to greenlint.py or its directory")
    args = parser.parse_args(argv)

    # Nothing but protocol on stdout. Anything that prints — a warning from an
    # import, a stray debug line in a rule — would otherwise land mid-stream
    # and desynchronise the parser on the other end.
    out = sys.stdout
    sys.stdout = sys.stderr

    try:
        gl = load_greenlint(args.greenlint or os.environ.get("GREENLINT_MODULE"))
        missing = missing_api(gl)
        if missing:
            raise ImportError(
                f"greenlint {greenlint_version(gl)} at {getattr(gl, '__file__', '?')} is too old "
                f"for this extension: it has no {', '.join(missing)}. Upgrade it with "
                "`pip install -U git+https://github.com/fabiocicerchia/greenlint` "
                "(or `pipx install --force ...` if that is how it was installed), or point "
                "`greenlint.greenlintPath` at a checkout."
            )
    except Exception as exc:  # noqa: BLE001 - the extension turns this into a prompt
        out.write(json.dumps({"id": 0, "ok": False, "fatal": True, "error": f"{exc}"}) + "\n")
        out.flush()
        return 1

    Server(gl, out).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
