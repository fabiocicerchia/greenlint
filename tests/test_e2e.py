"""End to end: the real `python -m greenlint` process, as a user or CI runs it.

The rest of the suite calls `main()` in-process; these go through the entry
point, argv, stdout and the exit code, which is what a CI gate actually sees.
Each run starts in an empty directory so no stray config or baseline leaks in.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "basic"


def greenlint(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(  # nosec B603 - fixed argv: this interpreter and the repo's own package
        [sys.executable, "-m", "greenlint", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_scanning_the_example_reports_what_its_readme_promises(tmp_path: Path) -> None:
    run = greenlint(tmp_path, str(EXAMPLE))
    assert run.returncode == 0
    assert "[GL001/" in run.stdout
    assert "[GL005/" in run.stdout
    assert "greenlint: " in run.stdout.splitlines()[-1]


def test_fail_on_findings_gates_a_dirty_tree_but_not_a_clean_one(tmp_path: Path) -> None:
    assert greenlint(tmp_path, str(EXAMPLE), "--fail-on-findings").returncode == 1
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "ok.py").write_text("x = 1\n")
    run = greenlint(tmp_path, str(clean), "--fail-on-findings")
    assert run.returncode == 0
    assert "greenlint: 0 finding(s)" in run.stdout


def test_json_output_is_machine_readable(tmp_path: Path) -> None:
    run = greenlint(tmp_path, str(EXAMPLE), "--format", "json")
    assert run.returncode == 0
    findings = json.loads(run.stdout)
    assert {"GL001", "GL005"} <= {f["rule"] for f in findings}
    assert all(f["file"].endswith("sample.py") for f in findings)


def test_a_written_baseline_silences_the_gate_on_the_next_run(tmp_path: Path) -> None:
    (tmp_path / "q.sql").write_text("SELECT * FROM t;\n")
    assert greenlint(tmp_path, ".", "--fail-on-findings").returncode == 1
    assert greenlint(tmp_path, ".", "--write-baseline").returncode == 0
    run = greenlint(tmp_path, ".", "--fail-on-findings")
    assert run.returncode == 0
    assert "accepted by" in run.stdout


def test_getting_started_config_example_does_what_it_says(tmp_path: Path) -> None:
    """The `.greenlint.toml` in docs/getting-started.md, copied verbatim, must
    disable the rules and ignore the paths it lists — that is what a reader pastes."""
    doc = (ROOT / "docs" / "getting-started.md").read_text()
    (tmp_path / ".greenlint.toml").write_text(doc.split("```toml\n", 1)[1].split("```", 1)[0])
    (tmp_path / "poll.py").write_text("import time\ntime.sleep(0.05)\nfor i in xs: out = out + [i]\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "q.sql").write_text("SELECT * FROM t;\n")
    (tmp_path / "q.sql").write_text("SELECT * FROM t;\n")
    findings = json.loads(greenlint(tmp_path, ".", "--format", "json").stdout)
    assert {(f["rule"], f["file"]) for f in findings} == {("GL005", "q.sql")}
