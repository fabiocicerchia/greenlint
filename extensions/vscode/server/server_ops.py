"""The protocol's operations, one function per op.

Each takes the server it runs against and the decoded request, and returns the
payload to answer with. Kept apart from the server so that adding an op is a
function here and a row in `Server.OPS`, not another method on a class that
already owns the cache, the config and the pump.
"""

import sys
from pathlib import Path

from greenlint_api import greenlint_version
from types_ import Request, Response

PROTOCOL_VERSION = 1
DEFAULT_MAX_FILE_BYTES = 1_000_000


def op_ping(server: str, request: Request) -> dict:
    """Protocol and build identity, and the ordering the client sorts by."""
    return {
        "protocol": PROTOCOL_VERSION,
        "version": greenlint_version(server.gl),
        "rules": len(server.gl.RULES),
        "python": sys.version.split()[0],
        "module": getattr(server.gl, "__file__", None),
        # The client merges findings from several scans and has to sort
        # the merged list itself. The *order* is greenlint's to decide,
        # so it is published rather than reinvented over there — and a
        # severity added here needs no change in the extension.
        "severityOrder": dict(server.gl.SEVERITY_ORDER),
    }


def op_languages(server: str, request: Request) -> dict:
    """The suffixes some rule targets, so the client can skip the rest."""
    # Just the extensions, not the rule table: the client uses this to
    # avoid sending a buffer no rule would look at, and nothing else.
    return {"extensions": sorted({lang for rule in server.gl.RULES for lang in rule["langs"]})}


def op_scan_text(server: str, request: Request) -> dict:
    """Scan a buffer the editor holds, saved or not."""
    config = server.config_for(request.get("root"))
    path = Path(request["path"])
    findings = server.scan_text(path, request.get("text", ""), config)
    return {"findings": server.accepted(findings, config)}


def op_scan_file(server: str, request: Request) -> dict:
    """Scan one file on disk, answering from the cache where it can."""
    config = server.config_for(request.get("root"))
    max_bytes = request.get("maxFileBytes", DEFAULT_MAX_FILE_BYTES)
    found, how = server.scan_path(Path(request["path"]), config, max_bytes)
    return {"findings": server.accepted(found, config), "source": how}


def op_configure(server: str, request: Request) -> dict:
    """Take the client's ignore globs; a change invalidates every cache."""
    ignore = [str(pattern) for pattern in request.get("ignore") or []]
    if ignore != server.extra_ignore:
        server.extra_ignore = ignore
        server.ignore_generation += 1
        server.configs.clear()
        server.cache.clear()
    return {"ignore": server.extra_ignore}


def op_write_baseline(server: str, request: Request) -> dict:
    """Accept every finding in the tree into `.greenlint-baseline.json`."""
    root = request.get("root")
    config = server.config_for(root)
    # Scanned rather than taken from the client: the baseline has to
    # describe the tree, not whatever the panel happens to be showing,
    # and the cache makes this nearly free straight after a scan.
    findings = []
    for path in server.gl.iter_files([root], config):
        found, _ = server.scan_path(path, config, DEFAULT_MAX_FILE_BYTES)
        findings.extend(found)
    target = Path(root) / server.gl.BASELINE_FILENAME
    count = server.gl.write_baseline(target, findings, target.parent)
    server.configs.clear()
    return {"path": str(target), "accepted": count}


def op_invalidate(server: str, request: Request) -> dict:
    """Drop the named paths from the cache, or the whole of it."""
    paths = request.get("paths")
    if paths:
        for path in paths:
            server.cache.drop(str(path))
    else:
        server.cache.clear()
        server.configs.clear()
    return {"cache": server.cache.stats()}


def op_cancel(server: str, request: Request) -> Response:
    """Mark a scan cancelled, whether it is running or still queued."""
    target = request.get("cancel")
    if target is None:
        return {"cancelling": False}
    server.cancelled.add(target)
    # A scan can be cancelled while it is still queued — `pump` defers
    # one project scan behind another — so this cannot be limited to the
    # running one. What it can do is forget the ids that name no scan at
    # all, which is what a cancel arriving just after its scan finished
    # leaves behind.
    pending = {d.get("id") for d in server.deferred if d.get("id") is not None}
    if server.active_scan is not None:
        pending.add(server.active_scan)
    server.cancelled &= pending
    return {"cancelling": target in server.cancelled}
