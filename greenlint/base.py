"""The vocabulary the rest of the package is written in: what a rule and a
finding are, and where the config and baseline live."""

from __future__ import annotations

import re
from collections.abc import Callable
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
