"""Finding and loading the greenlint module this server scans with.

Kept apart from the server because the question it answers -- which greenlint,
and is it new enough -- is settled once at startup and has nothing to do with
scanning or with the wire protocol.
"""

import importlib.util
import inspect
import sys
from importlib import metadata
from pathlib import Path


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
