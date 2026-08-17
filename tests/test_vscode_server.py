"""Tests for the VS Code extension's scan server.

The extension's whole performance story is the cache, so what is asserted here
is not "does it find things" — greenlint's own suite covers that — but *how few
times it had to look*: a rescan of an untouched tree must not read a byte, and
a file rewritten with identical contents must not run a rule.
"""

import importlib.util
import io
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import greenlint

SERVER_PATH = Path(__file__).resolve().parent.parent / "editors/vscode/server/greenlint_server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("greenlint_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server_module = load_server_module()


@pytest.fixture
def server():
    return server_module.Server(greenlint, io.StringIO())


def ask(server, **request):
    """Run one request through the real dispatch path and return the response."""
    request.setdefault("id", 1)
    before = server.out.tell()
    server.dispatch(request)
    server.out.seek(before)
    return json.loads(server.out.read())


def write(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_ping_reports_the_loaded_rule_set(server):
    response = ask(server, op="ping")
    assert response["ok"] is True
    assert response["rules"] == len(greenlint.RULES)
    assert response["protocol"] == server_module.PROTOCOL_VERSION


def test_rules_op_carries_the_energy_rationale(server):
    rules = ask(server, op="rules")["rules"]
    assert len(rules) == len(greenlint.RULES)
    assert all(rule["suggestion"] for rule in rules)
    assert next(r for r in rules if r["id"] == "GL003")["co2e_estimate"]


def test_scan_text_finds_issues_in_an_unsaved_buffer(server, tmp_path):
    response = ask(server, op="scanText", path=str(tmp_path / "q.sql"), text="SELECT * FROM t;\n")
    assert [f["rule"] for f in response["findings"]] == ["GL005"]


def test_scan_text_reuses_findings_for_unchanged_content(server, tmp_path):
    """Every cursor move and selection change fires a document event. Rescanning
    identical bytes is the cost this cache exists to remove."""
    args = {"op": "scanText", "path": str(tmp_path / "q.sql"), "text": "SELECT * FROM t;\n"}
    ask(server, **args)
    ask(server, **args)
    assert server.cache.stats()["hashHits"] == 1
    assert server.cache.stats()["misses"] == 1


def test_scan_file_reuses_findings_while_the_stat_is_unchanged(server, tmp_path):
    path = write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    assert ask(server, op="scanFile", path=str(path))["source"] == "scan"
    assert ask(server, op="scanFile", path=str(path))["source"] == "stat"


def test_rewriting_a_file_with_the_same_bytes_costs_a_read_not_a_scan(server, tmp_path):
    """A branch switch and back, or a formatter that changed nothing, moves
    every mtime in the tree without changing a single rule's answer."""
    path = write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    ask(server, op="scanFile", path=str(path))
    path.write_text("SELECT * FROM t;\n")  # same content, new mtime
    assert ask(server, op="scanFile", path=str(path))["source"] == "hash"


def test_editing_a_file_rescans_it(server, tmp_path):
    path = write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    ask(server, op="scanFile", path=str(path))
    path.write_text("SELECT id FROM t;\n")
    response = ask(server, op="scanFile", path=str(path))
    assert response["source"] == "scan"
    assert response["findings"] == []


def test_files_no_rule_targets_are_never_opened(server, tmp_path):
    path = write(tmp_path, "logo.png", "not really a png\n")
    assert ask(server, op="scanFile", path=str(path))["source"] == "skip"


def test_oversized_files_are_skipped(server, tmp_path):
    path = write(tmp_path, "big.sql", "SELECT * FROM t;\n" * 100)
    response = ask(server, op="scanFile", path=str(path), maxFileBytes=10)
    assert response["source"] == "skip"
    assert response["findings"] == []


def test_project_scan_matches_the_cli(server, tmp_path):
    write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    write(tmp_path, "ci.yml", "on:\n  schedule:\n    - cron: '* * * * *'\n")
    findings = ask(server, op="scanProject", root=str(tmp_path), paths=[str(tmp_path)])["findings"]
    assert findings == greenlint.scan([str(tmp_path)], greenlint.load_config(str(tmp_path)))


def test_second_project_scan_reads_nothing(server, tmp_path):
    write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    write(tmp_path, "a.py", "while True:\n    check()\n")
    args = {"op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]}
    first = ask(server, **args)
    second = ask(server, **args)
    assert first["stats"]["scanned"] == 2
    assert second["stats"]["scanned"] == 0
    assert second["stats"]["reusedFromStat"] == first["stats"]["files"]
    assert second["findings"] == first["findings"]


def test_project_scan_honours_ignore_globs(server, tmp_path):
    write(tmp_path, "vendor/q.sql", "SELECT * FROM t;\n")
    write(tmp_path, ".greenlint.toml", 'ignore = ["*/vendor/*"]\n')
    assert (
        ask(server, op="scanProject", root=str(tmp_path), paths=[str(tmp_path)])["findings"] == []
    )


def test_editing_the_config_invalidates_the_cache(server, tmp_path):
    """A cached finding is only valid for the config that produced it."""
    write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    args = {"op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]}
    assert ask(server, **args)["findings"]
    write(tmp_path, ".greenlint.toml", 'disable = ["GL005"]\n')
    assert ask(server, **args)["findings"] == []


def test_invalidate_drops_a_single_path(server, tmp_path):
    path = write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    ask(server, op="scanFile", path=str(path))
    ask(server, op="invalidate", paths=[str(path)])
    assert ask(server, op="scanFile", path=str(path))["source"] == "scan"


def test_cache_is_bounded(tmp_path):
    small = server_module.Server(greenlint, io.StringIO(), cache_entries=8)
    for index in range(50):
        ask(small, op="scanText", path=str(tmp_path / f"q{index}.sql"), text=f"SELECT {index};\n")
    assert small.cache.stats()["entries"] == 8


def test_a_broken_config_is_an_error_not_a_dead_server(server, tmp_path):
    """greenlint exits on invalid TOML, which is right for a CLI and fatal for
    a server that has to survive every keystroke of someone editing that TOML."""
    write(tmp_path, ".greenlint.toml", "disable = [\n")
    response = ask(server, op="scanFile", path=str(tmp_path / "q.sql"), root=str(tmp_path))
    assert response["ok"] is False
    assert "invalid TOML" in response["error"]
    assert ask(server, op="ping")["ok"] is True


def test_unknown_op_is_reported(server):
    assert ask(server, op="nope")["ok"] is False


def test_an_ignored_file_is_not_scanned_just_because_it_was_opened(server, tmp_path):
    """A project walk filters ignored files out; a buffer scan is reached by
    opening the file, so it has to check for itself or the editor disagrees
    with CI about the same file."""
    path = write(tmp_path, "vendor/q.sql", "SELECT * FROM t;\n")
    write(tmp_path, ".greenlint.toml", 'ignore = ["*/vendor/*"]\n')
    root = str(tmp_path)
    assert ask(server, op="scanFile", path=str(path), root=root)["findings"] == []
    text_scan = ask(server, op="scanText", path=str(path), root=root, text="SELECT * FROM t;\n")
    assert text_scan["findings"] == []


def test_missing_api_names_what_an_older_greenlint_lacks():
    # A 0.1.0-shaped module: imports fine, missing the editor API.
    old = types.SimpleNamespace(
        CONFIG_FILENAME=".greenlint.toml",
        CO2E_HINTS={},
        RULES=[],
        load_config=lambda path=None: {},
        scan_file=lambda path, disabled=frozenset(): [],
    )
    assert server_module.missing_api(greenlint) == []
    missing = server_module.missing_api(old)
    assert "iter_files" in missing
    # Present but older: the buffer scan needs the keyword, not just the name.
    assert "scan_file(text=)" in missing


def test_an_old_greenlint_refuses_to_start_and_says_why(tmp_path):
    """It used to import happily and fail on the first project scan with
    "module 'greenlint' has no attribute 'iter_files'", which reads as a bug in
    the extension rather than a version to upgrade. Refusing at startup also
    lets the extension move on to the next candidate interpreter."""
    stub = write(
        tmp_path,
        "greenlint.py",
        "CONFIG_FILENAME = '.greenlint.toml'\nCO2E_HINTS = {}\nRULES = []\n"
        "def load_config(path=None): return {}\n"
        "def scan_file(path, disabled=frozenset()): return []\n",
    )
    result = subprocess.run(
        [sys.executable, str(SERVER_PATH), "--greenlint", str(stub)],
        input="",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout.strip())
    assert payload["fatal"] is True
    assert "too old" in payload["error"]
    assert "iter_files" in payload["error"]
    assert "pipx install --force" in payload["error"]
