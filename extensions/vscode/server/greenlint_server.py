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
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import ClassVar

from greenlint_api import greenlint_version, load_greenlint, missing_api
from scan_cache import DEFAULT_CACHE_ENTRIES, FindingCache, ProjectScan, digest, mtime
from server_ops import (
    DEFAULT_MAX_FILE_BYTES,
    PROTOCOL_VERSION,
    op_cancel,
    op_configure,
    op_invalidate,
    op_languages,
    op_ping,
    op_scan_file,
    op_scan_text,
    op_write_baseline,
)

# How often a project scan looks up from the files to answer the editor. Small
# enough that typing stays responsive during a full scan, large enough that the
# queue poll is not itself the workload.
INTERLEAVE_EVERY = 16
# How often a long project scan says it is still going.
PROGRESS_INTERVAL_S = 0.5


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

    # The protocol's operations, in the order the docs list them. One callable
    # per op, all with the same `(server, request)` signature, so adding one is
    # a function in `server_ops` and a row here. `scanProject` is the method
    # above rather than an import: it drives the cache, the walk and the
    # progress events, which is the server itself and not an operation on it.
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
        """Run the callable implementing this request's `op`."""
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
