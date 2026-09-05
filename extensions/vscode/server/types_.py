"""The shapes the language server passes between its modules."""

from typing import Any

# One newline-delimited JSON-RPC request or response.
Request = dict[str, Any]
Response = dict[str, Any]
# A finding, as greenlint itself produces it.
Finding = dict[str, Any]
# A merged `.greenlint.toml` plus the editor's own settings.
Config = dict[str, Any]
# (mtime_ns, size) -- the cheap check that skips opening an unchanged file.
StatStamp = tuple[int, int]
