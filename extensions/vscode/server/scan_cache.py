"""What a scan remembers: the per-file cache and the two running records.

The extension's whole performance story lives here -- a rescan of an untouched
tree must not read a byte, and a file rewritten with identical contents must not
run a rule -- so it is one module, apart from the server that drives it.
"""

import hashlib
import time
from collections import OrderedDict

DEFAULT_CACHE_ENTRIES = 4096


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

    __slots__ = (
        "batch",
        "counts",
        "findings",
        "id",
        "paths",
        "reported",
        "seen",
        "started",
        "stream",
        "summary",
    )

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
