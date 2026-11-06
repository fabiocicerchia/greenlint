"""The vocabulary the rest of the package is written in: what a rule and a
finding are, and where the config and baseline live."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePath
from typing import Any

# A rule as the RULES table declares it, and a finding as the reporters consume
# it. Both are dicts because the table is written as literals and every reader
# does a `.get` on the optional keys.
Rule = dict[str, Any]
Finding = dict[str, Any]
# A parsed `.greenlint.toml`: {"disable": set[str], "ignore": list[str]}.
Config = dict[str, Any]
# A compiled ignore list: one regex `match` for the whole set of globs.
Matcher = Callable[[str], re.Match[str] | None]

CONFIG_FILENAME = ".greenlint.toml"
BASELINE_FILENAME = ".greenlint-baseline.json"

# Files known by their whole name rather than a suffix. A new one is an entry
# here and a tag in RULES, not another `path.name ==` branch at every caller.
NAMED_LANGS = frozenset({"Dockerfile"})


def lang_key(path: PurePath) -> str:
    """The language tag a file is selected by: its exact name if that is a
    known one, else its suffix. Every rule, index and syntax table keys on this.
    """
    return path.name if path.name in NAMED_LANGS else path.suffix
