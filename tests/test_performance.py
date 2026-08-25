"""Guards for the things that made a scan slow, and a benchmark to print.

A performance suite that asserts milliseconds is a flaky test wearing a stopwatch:
a shared CI runner is a factor of three on a bad day, and the number that fails
first is the one nobody trusts. So almost everything here counts *work* instead —
files opened, glob matches performed — which is the same on every machine and is
what actually regressed when these were slow.

The one exception is the quadratic guard, which no counter can express: it
compares the cost of 4x the input against 4x the cost. Quadratic work shows up
as a ratio far above 4 whatever the machine, so the bound is on the shape of the
curve rather than on a duration.

    pytest -q tests/test_performance.py     # the guards
    python3 tests/test_performance.py [dir] # the benchmark, for a human

The benchmark asserts nothing: it prints what a scan costs, for when you are
changing something and want to know which way it moved.
"""

import time
from pathlib import Path

import greenlint

# The line GL005 fires on, as a plain literal rather than something built per
# row: a formatted string containing SELECT is what secret and injection
# scanners are looking for, and a fixture should not have to argue with one.
QUERY = "SELECT * FROM t;\n"


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return f


def best_of(fn, runs=3):
    """The fastest of `runs`. Noise only ever adds, so the minimum is the
    closest thing to the cost of the work itself."""
    fastest = None
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - started
        fastest = elapsed if fastest is None else min(fastest, elapsed)
    return fastest


# --- work not done ----------------------------------------------------------


def test_only_files_a_rule_targets_are_opened(tmp_path, monkeypatch):
    """A checkout is mostly images, lock files and bundles. Reading one to match
    it against no rules is the cheapest work to remove: don't do it."""
    opened = []
    original = Path.read_text

    def counting(self, *args, **kwargs):
        opened.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    for name in ("logo.png", "yarn.lock", "data.bin", "notes.md", "bundle.map"):
        write(tmp_path, name, "SELECT * FROM t;\n")
    write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    write(tmp_path, "app.py", "import os\n")

    greenlint.scan([str(tmp_path)])
    assert sorted(opened) == ["app.py", "q.sql"]


def test_the_ignore_list_costs_the_same_at_five_globs_and_at_250(tmp_path, monkeypatch):
    """Matching is per path, not per path per glob.

    The editor hands greenlint its own `files.exclude` and `search.exclude`,
    which is a hundred-odd patterns; running each of them against every file was
    more work than reading some of the files would have been.
    """
    matched = []
    real = greenlint._ignore_matcher

    def counting(patterns):
        match = real(patterns)

        def wrapped(candidate):
            matched.append(candidate)
            return match(candidate)

        return wrapped

    monkeypatch.setattr(greenlint, "_ignore_matcher", counting)
    for index in range(60):
        write(tmp_path, f"pkg{index % 6}/m{index}.py", "x = 1\n")

    # Globs that match nothing here, so both walks visit exactly the same tree.
    few = ["*/vendor/*", "*/dist/*", "*.min.js", "*/build/*", "*/.cache/*"]
    many = [*few, *(f"*/generated{index}/*" for index in range(245))]
    counts = []
    for globs in (few, many):
        matched.clear()
        files = list(greenlint.iter_files([str(tmp_path)], {"disable": set(), "ignore": globs}))
        assert len(files) == 60
        counts.append(len(matched))
    assert counts[0] == counts[1], "matching cost grew with the number of globs"


def test_the_ignore_list_is_compiled_once_for_a_whole_walk(tmp_path):
    """Once for the files and once for the directory prune bases — not per file,
    and not per file per glob."""
    for index in range(40):
        write(tmp_path, f"pkg{index % 4}/m{index}.py", "x = 1\n")
    config = {"disable": set(), "ignore": ["*/vendor/*", "*/dist/*"]}
    greenlint._ignore_matcher.cache_clear()
    list(greenlint.iter_files([str(tmp_path)], config))
    assert greenlint._ignore_matcher.cache_info().misses == 2


# --- shape of the curve -----------------------------------------------------


def test_a_file_the_same_rule_matches_many_times_stays_linear(tmp_path):
    """Line numbers used to come from counting newlines from the top of the file
    per match, which reads the file once per finding. On a generated SQL dump
    that is quadratic, and generated files are the large ones.
    """

    def scan_with(matches):
        # One line repeated: the rule fires per occurrence, and what is being
        # measured is the count of matches, not what they say.
        path = write(tmp_path, f"dump{matches}.sql", QUERY * matches)
        found = None

        def run():
            nonlocal found
            found = list(greenlint.scan_file(path))

        elapsed = best_of(run)
        assert len(found) == matches
        return elapsed

    small = scan_with(2_000)
    large = scan_with(8_000)
    # Four times the input. Linear lands near 4x, the quadratic version was 11x;
    # the bound sits between them with room for a noisy machine either side.
    assert large / small < 6, (
        f"4x the matches cost {large / small:.1f}x the time "
        f"({1000 * small:.0f}ms -> {1000 * large:.0f}ms): line lookup is rescanning the file"
    )


# --- benchmark --------------------------------------------------------------


def _benchmark(target):  # pragma: no cover - a tool, not a test
    import tempfile

    print(f"corpus: {target}")
    config = {"disable": set(), "ignore": []}
    files = list(greenlint.iter_files([target], config))
    findings = None

    def run():
        nonlocal findings
        findings = greenlint.scan([target], config)

    elapsed = best_of(run, runs=2)
    print(
        f"  scan          {1000 * elapsed:8.1f} ms   "
        f"{len(files)} files, {len(findings)} findings, "
        f"{1000 * elapsed / max(len(files), 1):.2f} ms/file"
    )

    scratch = Path(tempfile.mkdtemp())
    dump = scratch / "dump.sql"
    dump.write_text(QUERY * 20_000)
    print(f"  20k matches   {1000 * best_of(lambda: list(greenlint.scan_file(dump))):8.1f} ms")

    assets = scratch / "assets"
    assets.mkdir(exist_ok=True)
    for index in range(200):
        (assets / f"asset{index}.png").write_text("x" * 200_000)
    print(
        f"  200 assets    {1000 * best_of(lambda: greenlint.scan([str(assets)], config)):8.1f} ms"
    )

    for index in range(500):
        path = scratch / "tree" / f"pkg{index % 20}" / f"m{index}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n")
    globs = [f"*/generated{index}/*" for index in range(250)]
    walk = {"disable": set(), "ignore": globs}
    print(
        f"  walk/250 globs{1000 * best_of(lambda: list(greenlint.iter_files([str(scratch / 'tree')], walk))):8.1f} ms"
    )


if __name__ == "__main__":  # pragma: no cover
    import sys

    _benchmark(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent))
