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
  ping                                    -> {version, rules, python}
  rules                                   -> the full rule table
  scanText   {path, text, root}           -> findings for an unsaved buffer
  scanFile   {path, root}                 -> findings for a file on disk
  scanProject{root, paths}                -> findings for the whole tree
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

PROTOCOL_VERSION = 1
DEFAULT_CACHE_ENTRIES = 4096
DEFAULT_MAX_FILE_BYTES = 1_000_000
# How often a project scan looks up from the files to answer the editor. Small
# enough that typing stays responsive during a full scan, large enough that the
# queue poll is not itself the workload.
INTERLEAVE_EVERY = 16


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
    "CONFIG_FILENAME",
    "CO2E_HINTS",
    "RULES",
    "finding_sort_key",
    "is_ignored",
    "iter_files",
    "load_config",
    "scan_file",
    "scannable",
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


class Server:
    def __init__(self, gl, out, cache_entries=DEFAULT_CACHE_ENTRIES):
        self.gl = gl
        self.out = out
        self.out_lock = threading.Lock()
        self.inbox = queue.Queue()
        self.cache = FindingCache(cache_entries)
        self.configs = {}
        self.config_fingerprint = None
        self.cancelled = set()
        self.deferred = []

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
        `disable` changes what a scan would have produced.
        """
        cfg_path = Path(root) / self.gl.CONFIG_FILENAME if root else None
        try:
            stamp = cfg_path.stat().st_mtime_ns if cfg_path else None
        except OSError:
            stamp = None
        cached = self.configs.get(root)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        if cfg_path is not None and stamp is not None:
            config = self.gl.load_config(str(cfg_path))
        else:
            config = {"disable": set(), "ignore": []}
        fingerprint = digest(
            json.dumps(
                {"disable": sorted(config["disable"]), "ignore": list(config["ignore"])},
                sort_keys=True,
            )
        )
        if fingerprint != self.config_fingerprint:
            self.cache.clear()
            self.config_fingerprint = fingerprint
        self.configs[root] = (stamp, config)
        return config

    # --- scanning --------------------------------------------------------

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

    def scan_project(self, request):
        root = request.get("root")
        paths = request.get("paths") or ([root] if root else ["."])
        max_bytes = request.get("maxFileBytes", DEFAULT_MAX_FILE_BYTES)
        config = self.config_for(root)
        started = time.perf_counter()
        findings = []
        counts = {"stat": 0, "hash": 0, "scan": 0, "skip": 0}
        seen = 0
        for path in self.gl.iter_files(paths, config):
            seen += 1
            if seen % INTERLEAVE_EVERY == 0:
                # A full scan must not hold the editor hostage: buffer scans
                # and cancellations are answered between batches of files.
                self.pump()
                if request.get("id") in self.cancelled:
                    self.cancelled.discard(request["id"])
                    return {"cancelled": True, "findings": []}
            found, how = self.scan_path(path, config, max_bytes)
            counts[how] += 1
            if found:
                findings.extend(found)
        findings.sort(key=self.gl.finding_sort_key)
        return {
            "findings": findings,
            "stats": {
                "files": seen,
                "reusedFromStat": counts["stat"],
                "reusedFromHash": counts["hash"],
                "scanned": counts["scan"],
                "skipped": counts["skip"],
                "ms": round((time.perf_counter() - started) * 1000),
                "cache": self.cache.stats(),
            },
        }

    # --- dispatch --------------------------------------------------------

    def handle(self, request):
        op = request.get("op")
        if op == "ping":
            return {
                "protocol": PROTOCOL_VERSION,
                "version": greenlint_version(self.gl),
                "rules": len(self.gl.RULES),
                "python": sys.version.split()[0],
                "module": getattr(self.gl, "__file__", None),
            }
        if op == "rules":
            return {
                "rules": [
                    {
                        "id": rule["id"],
                        "severity": rule["severity"],
                        "langs": sorted(rule["langs"]),
                        "message": rule["message"],
                        "suggestion": rule["suggestion"],
                        "co2e_estimate": self.gl.CO2E_HINTS.get(rule["id"], ""),
                    }
                    for rule in self.gl.RULES
                ]
            }
        if op == "scanText":
            config = self.config_for(request.get("root"))
            path = Path(request["path"])
            return {"findings": self.scan_text(path, request.get("text", ""), config)}
        if op == "scanFile":
            config = self.config_for(request.get("root"))
            max_bytes = request.get("maxFileBytes", DEFAULT_MAX_FILE_BYTES)
            found, how = self.scan_path(Path(request["path"]), config, max_bytes)
            return {"findings": found, "source": how}
        if op == "scanProject":
            return self.scan_project(request)
        if op == "invalidate":
            paths = request.get("paths")
            if paths:
                for path in paths:
                    self.cache.drop(str(path))
            else:
                self.cache.clear()
                self.configs.clear()
            return {"cache": self.cache.stats()}
        if op == "cancel":
            self.cancelled.add(request.get("cancel"))
            return {}
        raise ValueError(f"unknown op: {op!r}")

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
    parser.add_argument("--cache-entries", type=int, default=DEFAULT_CACHE_ENTRIES)
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

    Server(gl, out, cache_entries=args.cache_entries).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
