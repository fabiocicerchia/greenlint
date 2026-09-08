"""Reading `.greenlint.toml`."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .base import CONFIG_FILENAME, Config

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
            data: dict[str, Any] = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"greenlint: {cfg_path}: invalid TOML — {exc}") from exc
    return {
        "disable": set(_as_list(data.get("disable"), "disable")),
        "ignore": _as_list(data.get("ignore"), "ignore"),
    }
