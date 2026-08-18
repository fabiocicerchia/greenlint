"""Tests for the VS Code extension's scan server.

The extension's whole performance story is the cache, so what is asserted here
is not "does it find things" — greenlint's own suite covers that — but *how few
times it had to look*: a rescan of an untouched tree must not read a byte, and
a file rewritten with identical contents must not run a rule.
"""

import importlib.util
import io
import json
import os
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


def test_languages_op_reports_what_the_rules_target(server):
    """The client skips files no rule would look at; the list has to come from
    the rule table rather than a copy of it."""
    extensions = ask(server, op="languages")["extensions"]
    assert set(extensions) == {lang for rule in greenlint.RULES for lang in rule["langs"]}
    assert ".py" in extensions and "Dockerfile" in extensions


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


def responses(server):
    """Every line the server has written, progress events included."""
    return [json.loads(line) for line in server.out.getvalue().splitlines()]


def test_a_long_project_scan_reports_progress(server, tmp_path, monkeypatch):
    """Silence and a hang look identical from the client, and the client's only
    recourse is a timeout — which is how a slow-but-fine scan of a large tree
    came back as "scanProject timed out"."""
    monkeypatch.setattr(server_module, "PROGRESS_INTERVAL_S", 0)
    for index in range(64):
        write(tmp_path, f"q{index}.sql", "SELECT * FROM t;\n")
    server.dispatch({"id": 1, "op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]})
    progress = [line for line in responses(server) if line.get("event") == "progress"]
    assert progress, "a long scan said nothing until it was done"
    assert progress[0]["files"] == server_module.INTERLEAVE_EVERY
    assert progress[-1]["found"] > 0
    assert responses(server)[-1]["ok"] is True


def test_a_project_scan_answers_a_buffer_scan_before_it_finishes(server, tmp_path):
    """Typing must not wait for a full walk to end. The buffer scan is queued
    before the project scan starts, so if it is answered first the interleaving
    is what did it."""
    for index in range(64):
        write(tmp_path, f"q{index}.sql", "SELECT * FROM t;\n")
    server.inbox.put(
        json.dumps(
            {"id": 2, "op": "scanText", "path": str(tmp_path / "buf.sql"), "text": "SELECT 1;"}
        )
    )
    server.dispatch({"id": 1, "op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]})
    answered = [line["id"] for line in responses(server) if "ok" in line]
    assert answered.index(2) < answered.index(1)


def test_another_project_scan_arriving_mid_walk_is_deferred_not_nested(server, tmp_path):
    write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    for index in range(64):
        write(tmp_path, f"f{index}.py", "x = 1\n")
    args = {"op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]}
    server.inbox.put(json.dumps({"id": 2, **args}))
    server.dispatch({"id": 1, **args})
    assert [line["id"] for line in responses(server) if "ok" in line] == [1]
    assert len(server.deferred) == 1


def test_streaming_delivers_findings_in_batches_as_they_are_made(server, tmp_path, monkeypatch):
    """The panel should fill while the walk runs, not after it. Each progress
    event carries what was found since the last one."""
    monkeypatch.setattr(server_module, "PROGRESS_INTERVAL_S", 0)
    for index in range(64):
        write(tmp_path, f"q{index}.sql", "SELECT * FROM t;\n")
    server.dispatch(
        {
            "id": 1,
            "op": "scanProject",
            "root": str(tmp_path),
            "paths": [str(tmp_path)],
            "stream": True,
        }
    )
    lines = responses(server)
    streamed = [f for line in lines if line.get("event") == "progress" for f in line["batch"]]
    assert len(streamed) == 64
    # Delivered once, not once per batch and again at the end.
    final = lines[-1]
    assert final["streamed"] is True
    assert final["findings"] == []


def test_streaming_and_batching_agree_with_one_shot_and_with_the_cli(server, tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "PROGRESS_INTERVAL_S", 0)
    for index in range(40):
        write(tmp_path, f"q{index}.sql", "SELECT * FROM t;\n")
    write(tmp_path, "ci.yml", "on:\n  schedule:\n    - cron: '* * * * *'\n")
    args = {"op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]}
    server.dispatch({"id": 1, "stream": True, **args})
    streamed = [
        f for line in responses(server) if line.get("event") == "progress" for f in line["batch"]
    ]
    expected = greenlint.scan([str(tmp_path)], greenlint.load_config(str(tmp_path)))
    assert sorted(streamed, key=greenlint.finding_sort_key) == expected


def test_the_summary_is_the_whole_scan_not_a_batch(server, tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "PROGRESS_INTERVAL_S", 0)
    for index in range(20):
        write(tmp_path, f"q{index}.sql", "SELECT * FROM t;\n")
    write(tmp_path, "ci.yml", "on:\n  schedule:\n    - cron: '* * * * *'\n")
    server.dispatch(
        {
            "id": 1,
            "op": "scanProject",
            "root": str(tmp_path),
            "paths": [str(tmp_path)],
            "stream": True,
        }
    )
    summary = responses(server)[-1]["summary"]
    assert summary["total"] == 21
    assert summary["bySeverity"] == {"high": 1, "medium": 20, "low": 0}
    assert summary["files"] == 21
    assert list(summary["byRule"]) == ["GL005", "GL003"]  # busiest rule first


def test_a_non_streaming_scan_still_returns_everything(server, tmp_path):
    """The one-shot shape stays valid: streaming is a request the client opts
    into, not a change to what a project scan means."""
    write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    response = ask(server, op="scanProject", root=str(tmp_path), paths=[str(tmp_path)])
    assert response["streamed"] is False
    assert [f["rule"] for f in response["findings"]] == ["GL005"]
    assert response["summary"]["total"] == 1


def test_configure_adds_ignore_globs_on_top_of_the_config(server, tmp_path):
    """The editor's own exclude list, which greenlint has no way to read."""
    write(tmp_path, "src/q.sql", "SELECT * FROM t;\n")
    write(tmp_path, "dist/q.sql", "SELECT * FROM t;\n")
    args = {"op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]}
    assert len(ask(server, **args)["findings"]) == 2
    assert ask(server, op="configure", ignore=["*/dist/*"])["ignore"] == ["*/dist/*"]
    findings = ask(server, **args)["findings"]
    assert [f["file"] for f in findings] == [str(tmp_path / "src" / "q.sql")]


def test_configure_invalidates_what_was_cached_under_the_old_excludes(server, tmp_path):
    """A cached finding is only valid for the excludes that produced it — the
    same reason editing .greenlint.toml drops the cache."""
    write(tmp_path, "dist/q.sql", "SELECT * FROM t;\n")
    args = {"op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]}
    assert ask(server, **args)["findings"]
    ask(server, op="configure", ignore=["*/dist/*"])
    assert ask(server, **args)["findings"] == []
    # And back again, without a restart.
    ask(server, op="configure", ignore=[])
    assert ask(server, **args)["findings"]


def test_configure_applies_to_a_single_buffer_too(server, tmp_path):
    """An excluded file that happens to be open should not sprout squiggles;
    the editor said it was not interesting."""
    path = write(tmp_path, "dist/q.sql", "SELECT * FROM t;\n")
    ask(server, op="configure", ignore=["*/dist/*"])
    root = str(tmp_path)
    assert ask(server, op="scanFile", path=str(path), root=root)["findings"] == []
    text = ask(server, op="scanText", path=str(path), root=root, text="SELECT * FROM t;\n")
    assert text["findings"] == []


def test_configure_lets_the_walk_skip_the_directory_entirely(server, tmp_path, monkeypatch):
    """The point of the exercise: an excluded directory is never opened, not
    opened and then filtered."""
    write(tmp_path, "src/q.sql", "SELECT * FROM t;\n")
    for index in range(20):
        write(tmp_path, f"dist/f{index}.sql", "SELECT * FROM t;\n")
    ask(server, op="configure", ignore=["*/dist/*"])
    opened = []
    real_scandir = os.scandir

    def watched(path):
        opened.append(str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", watched)
    stats = ask(server, op="scanProject", root=str(tmp_path), paths=[str(tmp_path)])["stats"]
    assert stats["files"] == 1
    assert not any("dist" in path for path in opened)


def test_write_baseline_quietens_the_findings_it_recorded(server, tmp_path):
    write(tmp_path, "src/q.sql", "SELECT * FROM t;\n")
    args = {"op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]}
    assert len(ask(server, **args)["findings"]) == 1
    written = ask(server, op="writeBaseline", root=str(tmp_path))
    assert written["accepted"] == 1
    assert ask(server, **args)["findings"] == []
    # And a file the baseline never saw is still reported.
    write(tmp_path, "src/new.sql", "SELECT * FROM u;\n")
    assert len(ask(server, **args)["findings"]) == 1


def test_a_baselined_finding_is_quiet_in_an_open_buffer_too(server, tmp_path):
    """Otherwise the panel and the squiggles disagree about the same line."""
    path = write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    root = str(tmp_path)
    ask(server, op="writeBaseline", root=root)
    assert ask(server, op="scanFile", path=str(path), root=root)["findings"] == []
    text = ask(server, op="scanText", path=str(path), root=root, text="SELECT * FROM t;\n")
    assert text["findings"] == []


def test_the_cache_survives_a_baseline_change(server, tmp_path):
    """Findings are cached unfiltered and the baseline is applied on the way
    out, so accepting one costs a repaint rather than a rescan of the tree."""
    write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    args = {"op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]}
    ask(server, **args)
    ask(server, op="writeBaseline", root=str(tmp_path))
    stats = ask(server, **args)["stats"]
    # Nothing re-read: the baseline file itself is new in the tree, but no rule
    # targets .json so it is skipped rather than scanned.
    assert stats["scanned"] == 0
    assert stats["reusedFromStat"] >= 1


def test_cancelling_a_project_scan_stops_the_walk(server, tmp_path):
    for index in range(200):
        write(tmp_path, f"f{index}.sql", "SELECT * FROM t;\n")
    # Queued ahead of the scan, so the pump between batches picks it up.
    server.inbox.put(json.dumps({"id": 2, "op": "cancel", "cancel": 1}))
    server.dispatch({"id": 1, "op": "scanProject", "root": str(tmp_path), "paths": [str(tmp_path)]})
    scan = next(line for line in responses(server) if line.get("id") == 1 and "ok" in line)
    assert scan["cancelled"] is True
    assert scan["findings"] == []
