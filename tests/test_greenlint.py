import os
import re
from pathlib import Path

import pytest

import greenlint
from greenlint import _blank_strings, load_config, main, scan, scan_file


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return f


def rule_ids(findings):
    return {f["rule"] for f in findings}


def test_detects_every_minute_cron(tmp_path):
    write(tmp_path, "ci.yml", "on:\n  schedule:\n    - cron: '* * * * *'\n")
    assert "GL003" in rule_ids(scan([str(tmp_path)]))


def test_detects_select_star_and_fat_base(tmp_path):
    write(tmp_path, "q.sql", "SELECT * FROM users;\n")
    write(tmp_path, "Dockerfile", "FROM ubuntu:24.04\n")
    ids = rule_ids(scan([str(tmp_path)]))
    assert {"GL005", "GL006"} <= ids


def test_slim_base_not_flagged(tmp_path):
    write(tmp_path, "Dockerfile", "FROM debian:bookworm-slim\n")
    assert "GL006" not in rule_ids(scan([str(tmp_path)]))


def test_findings_sorted_high_first(tmp_path):
    write(tmp_path, "ci.yml", "cron: '* * * * *'\nfetch-depth: 0\n")
    sevs = [f["severity"] for f in scan([str(tmp_path)])]
    assert sevs == sorted(sevs, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s])


def test_config_disables_rule(tmp_path):
    write(tmp_path, "q.sql", "SELECT * FROM users;\n")
    cfg = write(tmp_path, ".greenlint.toml", 'disable = ["GL005"]\n')
    assert "GL005" not in rule_ids(scan([str(tmp_path)], load_config(str(cfg))))


def test_config_ignores_path(tmp_path):
    write(tmp_path, "vendor/q.sql", "SELECT * FROM users;\n")
    cfg = write(tmp_path, ".greenlint.toml", 'ignore = ["*/vendor/*"]\n')
    assert scan([str(tmp_path)], load_config(str(cfg))) == []


def test_missing_config_is_a_noop(tmp_path):
    assert load_config(str(tmp_path / "nope.toml")) == {"disable": set(), "ignore": []}


def test_ast_busy_loop_ignores_unrelated_sleep_elsewhere_in_file(tmp_path):
    # regex GL001 looked for "sleep" anywhere in the file, so this busy loop
    # was a false negative; the AST version only trusts a sleep call reachable
    # from inside the loop body.
    write(
        tmp_path,
        "a.py",
        "def poll():\n    while True:\n        check()\n\ndef other():\n    time.sleep(1)\n",
    )
    assert "GL001" in rule_ids(scan([str(tmp_path)]))


def test_ast_busy_loop_not_flagged_when_loop_actually_sleeps(tmp_path):
    write(tmp_path, "a.py", "def poll():\n    while True:\n        time.sleep(1)\n")
    assert "GL001" not in rule_ids(scan([str(tmp_path)]))


def test_paginator_loop_not_flagged(tmp_path):
    # `while True:` draining a paginated API exits on what came back. Each pass
    # does a network round trip, so it is not spinning on a core.
    write(
        tmp_path,
        "a.py",
        "def f(client):\n    token = None\n    while True:\n        page = client.get(token)\n"
        "        token = page.get('next')\n        if not token:\n            break\n",
    )
    assert "GL001" not in rule_ids(scan([str(tmp_path)]))


def test_read_until_eof_loop_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(conn):\n    while True:\n        ch = conn.recv(1)\n"
        "        if not ch:\n            break\n",
    )
    assert "GL001" not in rule_ids(scan([str(tmp_path)]))


def test_loop_returning_a_value_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(it):\n    while True:\n        n = next(it)\n        if n > end:\n            return n\n",
    )
    assert "GL001" not in rule_ids(scan([str(tmp_path)]))


def test_break_in_a_nested_loop_does_not_exonerate(tmp_path):
    # The break belongs to the inner `for`, so the outer `while True:` still
    # has no way out.
    write(
        tmp_path,
        "a.py",
        "def f(xs):\n    while True:\n        for x in xs:\n            if x:\n                break\n",
    )
    assert "GL001" in rule_ids(scan([str(tmp_path)]))


def test_ast_busy_loop_respects_disable(tmp_path):
    cfg = write(tmp_path, ".greenlint.toml", 'disable = ["GL001"]\n')
    write(tmp_path, "a.py", "while True:\n    check()\n")
    assert "GL001" not in rule_ids(scan([str(tmp_path)], load_config(str(cfg))))


def test_findings_carry_a_co2e_estimate(tmp_path):
    write(tmp_path, "q.sql", "SELECT * FROM users;\n")
    findings = scan([str(tmp_path)])
    assert findings[0]["co2e_estimate"]


def test_cli_github_format_emits_workflow_commands(tmp_path, capsys):
    write(tmp_path, "q.sql", "SELECT * FROM users;\n")
    main([str(tmp_path), "--format", "github"])
    out = capsys.readouterr().out
    assert out.startswith("::")
    assert "file=" in out and "line=" in out and "title=greenlint" in out


def test_detects_apt_and_pip_without_cleanup_flags(tmp_path):
    write(
        tmp_path,
        "Dockerfile",
        "FROM debian:bookworm-slim\n"
        "RUN apt-get update && apt-get install -y curl\n"
        "RUN pip install -r requirements.txt\n",
    )
    ids = rule_ids(scan([str(tmp_path)]))
    assert {"GL009", "GL010"} <= ids


def test_apt_and_pip_cleanup_flags_not_flagged(tmp_path):
    write(
        tmp_path,
        "Dockerfile",
        "FROM debian:bookworm-slim\n"
        "RUN apt-get install -y --no-install-recommends curl\n"
        "RUN pip install --no-cache-dir -r requirements.txt\n",
    )
    ids = rule_ids(scan([str(tmp_path)]))
    assert "GL009" not in ids and "GL010" not in ids


def test_detects_img_missing_lazy_loading(tmp_path):
    write(tmp_path, "page.html", '<img src="hero.png">\n')
    assert "GL011" in rule_ids(scan([str(tmp_path)]))


def test_img_with_loading_attr_not_flagged(tmp_path):
    write(tmp_path, "page.html", '<img loading="lazy" src="hero.png">\n')
    assert "GL011" not in rule_ids(scan([str(tmp_path)]))


def test_detects_query_in_loop(tmp_path):
    write(
        tmp_path,
        "a.py",
        "for user_id in user_ids:\n"
        '    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))\n',
    )
    assert "GL012" in rule_ids(scan([str(tmp_path)]))


def test_batched_query_not_flagged_as_n_plus_1(tmp_path):
    write(
        tmp_path,
        "a.py",
        'cursor.execute(f"SELECT * FROM users WHERE id IN {user_ids}")\n',
    )
    assert "GL012" not in rule_ids(scan([str(tmp_path)]))


def test_detects_s3_bucket_without_lifecycle(tmp_path):
    write(
        tmp_path,
        "bucket.tf",
        'resource "aws_s3_bucket" "logs" {\n  bucket = "my-logs"\n}\n',
    )
    assert "GL013" in rule_ids(scan([str(tmp_path)]))


def test_s3_bucket_with_lifecycle_not_flagged(tmp_path):
    write(
        tmp_path,
        "bucket.tf",
        'resource "aws_s3_bucket" "logs" {\n'
        '  bucket = "my-logs"\n'
        "  lifecycle_rule {\n    enabled = true\n  }\n"
        "}\n",
    )
    assert "GL013" not in rule_ids(scan([str(tmp_path)]))


def test_detects_k8s_deployment_without_resources(tmp_path):
    write(
        tmp_path,
        "deploy.yaml",
        "apiVersion: apps/v1\nkind: Deployment\nspec:\n"
        "  template:\n    spec:\n      containers:\n"
        "      - name: web\n        image: nginx\n",
    )
    assert "GL014" in rule_ids(scan([str(tmp_path)]))


def test_k8s_deployment_with_resources_not_flagged(tmp_path):
    write(
        tmp_path,
        "deploy.yaml",
        "apiVersion: apps/v1\nkind: Deployment\nspec:\n"
        "  template:\n    spec:\n      containers:\n"
        "      - name: web\n        image: nginx\n"
        "        resources:\n          limits:\n            cpu: 500m\n",
    )
    assert "GL014" not in rule_ids(scan([str(tmp_path)]))


def test_detects_eol_docker_base_image(tmp_path):
    write(tmp_path, "Dockerfile", "FROM node:12\n")
    assert "GL015" in rule_ids(scan([str(tmp_path)]))


def test_current_docker_base_image_not_flagged(tmp_path):
    write(tmp_path, "Dockerfile", "FROM node:22\n")
    assert "GL015" not in rule_ids(scan([str(tmp_path)]))


def test_detects_non_graviton_instance_family(tmp_path):
    write(
        tmp_path,
        "main.tf",
        'resource "aws_instance" "web" {\n  instance_type = "m5.large"\n}\n',
    )
    assert "GL016" in rule_ids(scan([str(tmp_path)]))


def test_graviton_instance_family_not_flagged(tmp_path):
    write(
        tmp_path,
        "main.tf",
        'resource "aws_instance" "web" {\n  instance_type = "m6g.large"\n}\n',
    )
    assert "GL016" not in rule_ids(scan([str(tmp_path)]))


def test_detects_gif_in_html_and_css(tmp_path):
    write(tmp_path, "page.html", '<img src="hero.gif">\n')
    write(tmp_path, "style.css", '.bg { background: url("loading.gif"); }\n')
    ids = rule_ids(scan([str(tmp_path)]))
    assert "GL017" in ids


def test_png_in_html_and_css_not_flagged(tmp_path):
    write(tmp_path, "page.html", '<img src="hero.png">\n')
    write(tmp_path, "style.css", '.bg { background: url("loading.png"); }\n')
    assert "GL017" not in rule_ids(scan([str(tmp_path)]))


def test_detects_nested_loop_over_same_collection(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(items):\n    for i in items:\n        for j in items:\n            pass\n",
    )
    assert "GL018" in rule_ids(scan([str(tmp_path)]))


def test_nested_loop_over_different_collections_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(items, others):\n    for i in items:\n        for j in others:\n            pass\n",
    )
    assert "GL018" not in rule_ids(scan([str(tmp_path)]))


def test_detects_http_request_in_loop(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(ids):\n    for i in ids:\n        requests.get(f'/x/{i}')\n",
    )
    assert "GL019" in rule_ids(scan([str(tmp_path)]))


def test_batched_http_request_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(ids):\n    session.get('/batch', params={'ids': ids})\n",
    )
    assert "GL019" not in rule_ids(scan([str(tmp_path)]))


def test_detects_eager_logging_fstring(tmp_path):
    write(tmp_path, "a.py", 'import logging\ndef f(x):\n    logging.debug(f"x={x}")\n')
    assert "GL020" in rule_ids(scan([str(tmp_path)]))


def test_lazy_logging_not_flagged(tmp_path):
    write(tmp_path, "a.py", 'import logging\ndef f(x):\n    logging.debug("x=%s", x)\n')
    assert "GL020" not in rule_ids(scan([str(tmp_path)]))


def test_detects_pandas_iterrows(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(df):\n    for i, row in df.iterrows():\n        print(row)\n",
    )
    assert "GL021" in rule_ids(scan([str(tmp_path)]))


def test_vectorised_pandas_not_flagged(tmp_path):
    write(tmp_path, "a.py", 'def f(df):\n    df["c"] = df["a"] + df["b"]\n')
    assert "GL021" not in rule_ids(scan([str(tmp_path)]))


def test_detects_file_open_in_loop(tmp_path):
    write(tmp_path, "a.py", "def f(paths):\n    for p in paths:\n        f = open(p)\n")
    assert "GL022" in rule_ids(scan([str(tmp_path)]))


def test_file_opened_outside_loop_not_flagged(tmp_path):
    write(tmp_path, "a.py", "def f(paths):\n    data = [open(p).read() for p in paths]\n")
    assert "GL022" not in rule_ids(scan([str(tmp_path)]))


def test_detects_manual_bubble_sort(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(a):\n    n = len(a)\n    for i in range(n):\n"
        "        for j in range(n - 1):\n            if a[j] > a[j + 1]:\n"
        "                a[j], a[j + 1] = a[j + 1], a[j]\n",
    )
    assert "GL023" in rule_ids(scan([str(tmp_path)]))


def test_builtin_sorted_not_flagged(tmp_path):
    write(tmp_path, "a.py", "def f(a):\n    return sorted(a)\n")
    assert "GL023" not in rule_ids(scan([str(tmp_path)]))


def test_detects_fixed_size_autoscaling_group(tmp_path):
    write(
        tmp_path,
        "asg.tf",
        'resource "aws_autoscaling_group" "bad" {\n  min_size = 3\n  max_size = 3\n}\n',
    )
    assert "GL024" in rule_ids(scan([str(tmp_path)]))


def test_elastic_autoscaling_group_not_flagged(tmp_path):
    write(
        tmp_path,
        "asg.tf",
        'resource "aws_autoscaling_group" "good" {\n  min_size = 1\n  max_size = 5\n}\n',
    )
    assert "GL024" not in rule_ids(scan([str(tmp_path)]))


def test_detects_gp2_volume(tmp_path):
    write(
        tmp_path,
        "vol.tf",
        'resource "aws_ebs_volume" "v" {\n  volume_type = "gp2"\n}\n',
    )
    assert "GL025" in rule_ids(scan([str(tmp_path)]))


def test_gp3_volume_not_flagged(tmp_path):
    write(
        tmp_path,
        "vol.tf",
        'resource "aws_ebs_volume" "v" {\n  volume_type = "gp3"\n}\n',
    )
    assert "GL025" not in rule_ids(scan([str(tmp_path)]))


def test_detects_log_group_without_retention(tmp_path):
    write(
        tmp_path,
        "log.tf",
        'resource "aws_cloudwatch_log_group" "l" {\n  name = "app"\n}\n',
    )
    assert "GL026" in rule_ids(scan([str(tmp_path)]))


def test_log_group_with_retention_not_flagged(tmp_path):
    write(
        tmp_path,
        "log.tf",
        'resource "aws_cloudwatch_log_group" "l" {\n  name = "app"\n  retention_in_days = 30\n}\n',
    )
    assert "GL026" not in rule_ids(scan([str(tmp_path)]))


def test_detects_express_static_without_cache(tmp_path):
    write(tmp_path, "server.js", "app.use(express.static('public'));\n")
    assert "GL027" in rule_ids(scan([str(tmp_path)]))


def test_express_static_with_maxage_not_flagged(tmp_path):
    write(tmp_path, "server.js", "app.use(express.static('public', { maxAge: '1y' }));\n")
    assert "GL027" not in rule_ids(scan([str(tmp_path)]))


def test_detects_wildcard_import(tmp_path):
    write(tmp_path, "a.py", "from os import *\n")
    assert "GL028" in rule_ids(scan([str(tmp_path)]))


def test_named_import_not_flagged(tmp_path):
    write(tmp_path, "a.py", "from math import sqrt\n")
    assert "GL028" not in rule_ids(scan([str(tmp_path)]))


def test_detects_multiple_dockerfile_install_layers(tmp_path):
    write(
        tmp_path,
        "Dockerfile",
        "FROM debian:bookworm-slim\nRUN apt-get install -y curl\nRUN pip3 install -r requirements.txt\n",
    )
    assert "GL029" in rule_ids(scan([str(tmp_path)]))


def test_single_dockerfile_install_layer_not_flagged(tmp_path):
    write(
        tmp_path,
        "Dockerfile",
        "FROM debian:bookworm-slim\nRUN apt-get install -y curl && pip3 install -r requirements.txt\n",
    )
    assert "GL029" not in rule_ids(scan([str(tmp_path)]))


def test_detects_dict_items_discarding_key_or_value(tmp_path):
    write(tmp_path, "a.py", "def f(d):\n    for _, v in d.items():\n        print(v)\n")
    assert "GL030" in rule_ids(scan([str(tmp_path)]))


def test_dict_items_using_both_key_and_value_not_flagged(tmp_path):
    write(tmp_path, "a.py", "def f(d):\n    for k, v in d.items():\n        print(k, v)\n")
    assert "GL030" not in rule_ids(scan([str(tmp_path)]))


def test_detects_lookup_guarded_by_except_in_loop(tmp_path):
    # `d[k]` + `except KeyError: continue` where `d.get(k)` never raises.
    write(
        tmp_path,
        "a.py",
        "def f(keys, d):\n    for k in keys:\n        try:\n            v = d[k]\n"
        "        except KeyError:\n            continue\n",
    )
    assert "GL031" in rule_ids(scan([str(tmp_path)]))


def test_detects_int_conversion_used_as_a_type_test(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(items):\n    for s in items:\n        try:\n            n = int(s)\n"
        "        except ValueError:\n            continue\n",
    )
    assert "GL031" in rule_ids(scan([str(tmp_path)]))


def test_swallowed_io_error_in_loop_not_flagged(tmp_path):
    # Opening a file can fail on perfectly good input; catching it is how that
    # is written, not a pattern with a free alternative.
    write(
        tmp_path,
        "a.py",
        "def f(paths):\n    for p in paths:\n        try:\n            data = json.load(open(p))\n"
        "        except OSError:\n            continue\n",
    )
    assert "GL031" not in rule_ids(scan([str(tmp_path)]))


def test_retry_loop_handler_not_flagged(tmp_path):
    # The handler does real work (backoff + give-up check), so the exception is
    # not standing in for an if-check and cannot be hoisted out of the loop.
    write(
        tmp_path,
        "a.py",
        "def f():\n    while True:\n        try:\n            run()\n            break\n"
        "        except OSError:\n            if time.time() > deadline:\n                raise\n"
        "            time.sleep(2)\n",
    )
    assert "GL031" not in rule_ids(scan([str(tmp_path)]))


def test_per_item_error_collector_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(checks):\n    for c in checks:\n        try:\n            evaluate(c)\n"
        "        except Failure as e:\n            results.append(str(e))\n",
    )
    assert "GL031" not in rule_ids(scan([str(tmp_path)]))


def test_handler_that_breaks_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(fd):\n    while True:\n        try:\n            chunk = os.read(fd, 4096)\n"
        "        except OSError:\n            break\n",
    )
    assert "GL031" not in rule_ids(scan([str(tmp_path)]))


def test_try_except_around_loop_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(keys, d):\n    try:\n        for k in keys:\n            v = d[k]\n"
        "    except KeyError:\n        pass\n",
    )
    assert "GL031" not in rule_ids(scan([str(tmp_path)]))


def test_detects_malloc_in_loop(tmp_path):
    write(
        tmp_path,
        "a.c",
        "void f(int n) {\n    for (int i = 0; i < n; i++) {\n        int *buf = malloc(100);\n    }\n}\n",
    )
    assert "GL032" in rule_ids(scan([str(tmp_path)]))


def test_malloc_outside_loop_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.c",
        "void f(int n) {\n    int *buf = malloc(100 * n);\n    for (int i = 0; i < n; i++) {\n    }\n}\n",
    )
    assert "GL032" not in rule_ids(scan([str(tmp_path)]))


def test_detects_fixed_range_hpa(tmp_path):
    write(
        tmp_path,
        "hpa.yaml",
        "apiVersion: autoscaling/v2\nkind: HorizontalPodAutoscaler\nspec:\n  minReplicas: 3\n  maxReplicas: 3\n",
    )
    assert "GL033" in rule_ids(scan([str(tmp_path)]))


def test_elastic_hpa_not_flagged(tmp_path):
    write(
        tmp_path,
        "hpa.yaml",
        "apiVersion: autoscaling/v2\nkind: HorizontalPodAutoscaler\nspec:\n  minReplicas: 1\n  maxReplicas: 5\n",
    )
    assert "GL033" not in rule_ids(scan([str(tmp_path)]))


def test_config_array_may_span_lines(tmp_path):
    cfg = tmp_path / ".greenlint.toml"
    cfg.write_text('ignore = [\n  "*/vendor/*",\n  "*/examples/*",\n]\n')
    assert load_config(str(cfg))["ignore"] == ["*/vendor/*", "*/examples/*"]


def test_multiline_ignore_actually_excludes_files(tmp_path):
    cfg = tmp_path / ".greenlint.toml"
    cfg.write_text('ignore = [\n  "*/examples/*",\n]\n')
    (tmp_path / "examples").mkdir()
    write(tmp_path / "examples", "a.py", "while True:\n    pass\n")
    assert scan([str(tmp_path)], load_config(str(cfg))) == []


def test_detects_two_install_layers_in_one_stage(tmp_path):
    write(
        tmp_path,
        "Dockerfile",
        "FROM alpine\nRUN apk add curl\nRUN pip install foo\nRUN pip install bar\n",
    )
    assert "GL029" in rule_ids(scan([str(tmp_path)]))


def test_install_layers_in_separate_build_stages_not_flagged(tmp_path):
    # The build stage is discarded, so its layers never ship — chaining across
    # the FROM boundary saves nothing.
    write(
        tmp_path,
        "Dockerfile",
        "FROM python:3.12 AS build\nRUN pip install build\n"
        "FROM python:3.12-slim\nRUN pip install /tmp/x.whl\n",
    )
    assert "GL029" not in rule_ids(scan([str(tmp_path)]))


def test_detects_quadratic_list_rebuild(tmp_path):
    write(tmp_path, "a.py", "out = []\nfor i in range(10):\n    out = out + [i]\n")
    assert "GL007" in rule_ids(scan([str(tmp_path)]))


def test_detects_string_concat_in_loop(tmp_path):
    write(tmp_path, "a.py", "s = ''\nfor w in words:\n    s += w\n")
    assert "GL007" in rule_ids(scan([str(tmp_path)]))


def test_append_in_loop_is_not_flagged(tmp_path):
    # append is amortised O(1) and idiomatic — the whole reason this rule was
    # rewritten. Guard it so the regex version cannot come back.
    write(tmp_path, "a.py", "out = []\nfor i in range(10):\n    out.append(i)\n")
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_counter_increment_in_loop_is_not_flagged(tmp_path):
    write(tmp_path, "a.py", "total = 0\nfor i in range(10):\n    total += 1\n")
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_numeric_accumulation_is_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "kwh = 0\nseen = 0\nfor r in rows:\n"
        "    kwh += r.hours * r.watts / 1000\n"
        "    seen += len(r.data)\n",
    )
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_tuple_unpacked_counters_are_not_flagged(tmp_path):
    # `mwh, grams = 0.0, 0.0` binds two counters. Reading only single-name
    # targets left both unclassified, so `mwh += v` looked like a rebuild.
    write(
        tmp_path,
        "a.py",
        "mwh, grams = 0.0, 0.0\nfor r in rows:\n    mwh += r\n    grams += r\n",
    )
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_tuple_unpacked_list_still_detects_rebuild(tmp_path):
    # The other half of the pairing: `out` is a list here, `n` a counter, and
    # `out = out + [i]` is still the rebuilding form.
    write(
        tmp_path,
        "a.py",
        "out, n = [], 0\nfor i in range(10):\n    out = out + [i]\n",
    )
    assert "GL007" in rule_ids(scan([str(tmp_path)]))


def test_list_extend_via_augmented_assign_is_not_flagged(tmp_path):
    # `xs += [...]` is list.extend — in place, O(k). Only `xs = xs + [...]`
    # copies the whole list each pass.
    write(tmp_path, "a.py", "xs = []\nfor g in groups:\n    xs += [g.a, g.b]\n")
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_list_extend_with_comprehension_is_not_flagged(tmp_path):
    write(tmp_path, "a.py", "xs = []\nfor g in groups:\n    xs += [x for x in g]\n")
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_extend_of_a_name_known_to_be_a_list_is_not_flagged(tmp_path):
    # `lines = []` proves `lines += f(x)` is list.extend, not a rebuild.
    write(
        tmp_path,
        "a.py",
        "def f(groups):\n    lines = []\n    for g in groups:\n        lines += render(g)\n    return lines\n",
    )
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_bytes_accumulation_of_a_call_result_is_still_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(conn):\n    data = b''\n    while True:\n        data += conn.recv(10)\n",
    )
    assert "GL007" in rule_ids(scan([str(tmp_path)]))


def test_byte_accumulation_is_still_flagged(tmp_path):
    write(tmp_path, "a.py", "data = b''\nwhile True:\n    data += chunk\n")
    assert "GL007" in rule_ids(scan([str(tmp_path)]))


def test_rebinding_from_other_names_is_not_flagged(tmp_path):
    write(tmp_path, "a.py", "for i in range(10):\n    z = x + y\n")
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_cursor_seeded_from_arithmetic_is_not_flagged(tmp_path):
    # `day` never appears beside an operator itself — it is the *target* of
    # the arithmetic that seeds it. Reading only operands left it unclassified
    # and `day += DAY` read as a rebuild.
    write(
        tmp_path,
        "a.py",
        "def days(start, end):\n"
        "    out = []\n"
        "    day = start - (start % DAY)\n"
        "    while day <= end:\n"
        "        out.append(day)\n"
        "        day += DAY\n"
        "    return out\n",
    )
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_assignment_of_a_list_expression_still_detects_rebuild(tmp_path):
    # The assignment rule must not clear a name assigned a *sequence*
    # expression: `out = out + [i]` is the canonical rebuild.
    write(
        tmp_path,
        "a.py",
        "def f(n):\n"
        "    out = other + [0]\n"
        "    for i in range(n):\n"
        "        out = out + [i]\n"
        "    return out\n",
    )
    assert "GL007" in rule_ids(scan([str(tmp_path)]))


def test_coordinate_seeded_from_a_parameter_is_not_flagged(tmp_path):
    # `y = top` says nothing about y's type, so the initialiser check cannot
    # clear it — but `y - gap` later in the scope can: no sequence defines `-`.
    write(
        tmp_path,
        "a.py",
        "def render(rows, top, gap):\n"
        "    y = top\n"
        "    for row in rows:\n"
        "        y += height(row) + gap\n"
        "    return y - gap\n",
    )
    assert "GL007" not in rule_ids(scan([str(tmp_path)]))


def test_string_accumulator_is_still_flagged_when_the_scope_does_arithmetic(tmp_path):
    # The numeric evidence has to be about *this* name. `n - 1` clears `n`
    # and must leave the genuine rebuild of `s` alone.
    write(
        tmp_path,
        "a.py",
        "def f(words, n):\n    s = ''\n    for w in words:\n        s += w\n    return s, n - 1\n",
    )
    assert "GL007" in rule_ids(scan([str(tmp_path)]))


def test_numeric_evidence_does_not_leak_across_scopes(tmp_path):
    # Same reason the initialiser sets are per-scope: `total - 1` in one
    # function must not clear `total` in the next.
    write(
        tmp_path,
        "a.py",
        "def a(total):\n"
        "    return total - 1\n"
        "\n"
        "def b(chunks):\n"
        "    total = b''\n"
        "    for c in chunks:\n"
        "        total += c\n"
        "    return total\n",
    )
    assert "GL007" in rule_ids(scan([str(tmp_path)]))


def test_helm_template_not_flagged_for_missing_resources(tmp_path):
    write(
        tmp_path,
        "workload.yaml",
        "apiVersion: apps/v1\nkind: Deployment\nspec:\n  template:\n"
        '    {{- include "app.podSpec" . | nindent 4 }}\n',
    )
    assert "GL014" not in rule_ids(scan([str(tmp_path)]))


def test_sleep_of_exactly_100ms_is_not_flagged(tmp_path):
    # The rule is "sub-100ms". 0.1s is 100ms.
    write(tmp_path, "a.py", "time.sleep(0.1)\n")
    assert "GL002" not in rule_ids(scan([str(tmp_path)]))


def test_sleep_below_100ms_is_still_flagged(tmp_path):
    write(tmp_path, "a.py", "time.sleep(0.05)\n")
    assert "GL002" in rule_ids(scan([str(tmp_path)]))


def test_short_sleep_in_a_test_file_is_not_flagged(tmp_path):
    write(tmp_path, "proxy_test.go", "func f() { time.Sleep(10 * time.Millisecond) }\n")
    assert "GL002" not in rule_ids(scan([str(tmp_path)]))


def test_short_sleep_in_production_code_is_still_flagged(tmp_path):
    write(tmp_path, "proxy.go", "func f() { time.Sleep(10 * time.Millisecond) }\n")
    assert "GL002" in rule_ids(scan([str(tmp_path)]))


def test_pattern_in_a_comment_is_not_a_finding(tmp_path):
    # Prose warning against a pattern is not the pattern. This was six false
    # positives out of six across the portfolio's docs and examples.
    write(tmp_path, "a.py", "# never write SELECT * FROM users\nq = 1\n")
    write(tmp_path, "b.sql", "-- bad: SELECT * FROM users;\nSELECT id FROM users;\n")
    write(tmp_path, "c.go", "// avoid time.Sleep(10 * time.Millisecond)\n")
    write(tmp_path, "d.yml", "# not a cron: * * * * * schedule\nx: 1\n")
    assert rule_ids(scan([str(tmp_path)])) == set()


def test_pattern_in_a_docstring_is_not_a_finding(tmp_path):
    write(tmp_path, "a.py", '"""Never write SELECT * FROM orders."""\n')
    assert "GL005" not in rule_ids(scan([str(tmp_path)]))


def test_pattern_in_a_real_string_is_still_a_finding(tmp_path):
    # A query lives in a string literal — blanking comments must not touch it.
    write(tmp_path, "a.py", 'q = "SELECT * FROM users"\n')
    assert "GL005" in rule_ids(scan([str(tmp_path)]))


def test_hash_inside_a_string_is_not_a_comment(tmp_path):
    write(tmp_path, "a.py", 'q = "# SELECT * FROM users"\n')
    assert "GL005" in rule_ids(scan([str(tmp_path)]))


def test_block_comment_is_blanked(tmp_path):
    write(tmp_path, "a.go", "/*\n  SELECT * FROM users\n*/\nfunc f() {}\n")
    assert "GL005" not in rule_ids(scan([str(tmp_path)]))


def test_commented_out_dockerfile_directive_not_flagged(tmp_path):
    write(tmp_path, "Dockerfile", "# FROM ubuntu:22.04\nFROM alpine:3.24\n")
    assert "GL006" not in rule_ids(scan([str(tmp_path)]))


def test_detects_full_history_clone(tmp_path):
    write(
        tmp_path,
        "ci.yml",
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n          fetch-depth: 0\n",
    )
    assert "GL004" in rule_ids(scan([str(tmp_path)]))


def test_full_history_clone_not_flagged_when_a_scanner_needs_it(tmp_path):
    write(
        tmp_path,
        "security.yml",
        "jobs:\n  secrets:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n"
        "          fetch-depth: 0\n      - uses: gitleaks/gitleaks-action@v3\n",
    )
    assert "GL004" not in rule_ids(scan([str(tmp_path)]))


def test_full_history_clone_in_a_comment_not_flagged(tmp_path):
    write(
        tmp_path,
        "action.yml",
        "runs:\n  steps:\n"
        "    # cheaper than asking every caller for fetch-depth: 0\n"
        "    - run: git fetch --depth=1\n",
    )
    assert "GL004" not in rule_ids(scan([str(tmp_path)]))


def test_full_history_clone_not_flagged_for_docs_date_plugins(tmp_path):
    """A "last updated" date per page is read from that file's own commit
    history. Shallow-cloning does not make the docs build cheaper — it makes
    every page claim it changed today.
    """
    write(
        tmp_path,
        "docs.yml",
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n"
        "          fetch-depth: 0\n"
        "      - run: pip install mkdocs-git-revision-date-localized-plugin\n"
        "      - run: mkdocs build --strict\n",
    )
    assert "GL004" not in rule_ids(scan([str(tmp_path)]))


def test_full_history_clone_not_flagged_for_super_linter(tmp_path):
    """With VALIDATE_ALL_CODEBASE off, super-linter lints the diff against the
    default branch — which it cannot work out from a shallow clone.
    """
    write(
        tmp_path,
        "linter.yml",
        "jobs:\n  lint:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n"
        "          fetch-depth: 0\n"
        "      - uses: docker://ghcr.io/super-linter/super-linter@sha256:abc\n",
    )
    assert "GL004" not in rule_ids(scan([str(tmp_path)]))


def test_full_history_clone_still_flagged_for_a_plain_build(tmp_path):
    """The exemption is per job and per tool: a build job that clones all of
    history for nothing is exactly what GL004 is for.
    """
    write(
        tmp_path,
        "ci.yml",
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n"
        "          fetch-depth: 0\n      - run: make build\n",
    )
    assert "GL004" in rule_ids(scan([str(tmp_path)]))


def test_full_history_clone_not_flagged_for_release_tooling(tmp_path):
    write(
        tmp_path,
        "release.yml",
        "jobs:\n  release:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n"
        "          fetch-depth: 0\n      - uses: googleapis/release-please-action@v4\n",
    )
    assert "GL004" not in rule_ids(scan([str(tmp_path)]))


def test_detects_compose_service_without_limits(tmp_path):
    write(tmp_path, "docker-compose.yml", "services:\n  web:\n    image: nginx\n")
    assert "GL034" in rule_ids(scan([str(tmp_path)]))


def test_compose_service_with_mem_limit_not_flagged(tmp_path):
    write(
        tmp_path,
        "docker-compose.yml",
        "services:\n  web:\n    image: nginx\n    mem_limit: 512m\n",
    )
    assert "GL034" not in rule_ids(scan([str(tmp_path)]))


def test_opentofu_files_use_the_same_terraform_rules(tmp_path):
    write(
        tmp_path,
        "main.tofu",
        'resource "aws_instance" "web" {\n  instance_type = "m5.large"\n}\n',
    )
    assert "GL016" in rule_ids(scan([str(tmp_path)]))


def test_detects_k8s_cronjob_schedule_every_minute(tmp_path):
    write(
        tmp_path,
        "cron.yaml",
        "apiVersion: batch/v1\nkind: CronJob\nspec:\n  schedule: '* * * * *'\n",
    )
    assert "GL003" in rule_ids(scan([str(tmp_path)]))


def test_detects_sub_100ms_polling_across_languages(tmp_path):
    write(tmp_path, "poll.sh", "sleep 0.05\n")
    write(tmp_path, "poll.go", "time.Sleep(50 * time.Millisecond)\n")
    write(tmp_path, "poll.rs", "thread::sleep(Duration::from_millis(50));\n")
    write(tmp_path, "Poll.java", "Thread.sleep(50);\n")
    write(tmp_path, "poll.c", "usleep(50000);\n")
    ids = rule_ids(scan([str(tmp_path)]))
    assert ids == {"GL002"}


def test_normal_sleep_intervals_across_languages_not_flagged(tmp_path):
    write(tmp_path, "poll.sh", "sleep 5\n")
    write(tmp_path, "poll.go", "time.Sleep(5 * time.Second)\n")
    write(tmp_path, "poll.rs", "thread::sleep(Duration::from_secs(5));\n")
    assert rule_ids(scan([str(tmp_path)])) == set()


def test_select_star_detected_in_c_and_rust(tmp_path):
    write(tmp_path, "q.c", 'char *q = "SELECT * FROM users";\n')
    write(tmp_path, "q.rs", 'let q = "SELECT * FROM users";\n')
    assert rule_ids(scan([str(tmp_path)])) == {"GL005"}


def test_detects_linq_count_zero_check(tmp_path):
    write(tmp_path, "a.cs", "if (items.Count() == 0) { return; }\n")
    assert "GL035" in rule_ids(scan([str(tmp_path)]))


def test_linq_any_not_flagged(tmp_path):
    write(tmp_path, "a.cs", "if (!items.Any()) { return; }\n")
    assert "GL035" not in rule_ids(scan([str(tmp_path)]))


def test_detects_ruby_hash_keys_include(tmp_path):
    write(tmp_path, "a.rb", "if h.keys.include?(k)\n  puts k\nend\n")
    assert "GL036" in rule_ids(scan([str(tmp_path)]))


def test_ruby_hash_key_predicate_not_flagged(tmp_path):
    write(tmp_path, "a.rb", "if h.key?(k)\n  puts k\nend\n")
    assert "GL036" not in rule_ids(scan([str(tmp_path)]))


def test_detects_ruby_select_map_chain(tmp_path):
    write(tmp_path, "a.rb", "result = list.select(&:active?).map(&:name)\n")
    assert "GL037" in rule_ids(scan([str(tmp_path)]))


def test_ruby_filter_map_not_flagged(tmp_path):
    write(tmp_path, "a.rb", "result = list.filter_map { |x| x.name if x.active? }\n")
    assert "GL037" not in rule_ids(scan([str(tmp_path)]))


def test_detects_inline_jsx_prop_allocation(tmp_path):
    write(tmp_path, "Comp.jsx", "const A = () => <Foo onClick={() => doThing()} />;\n")
    assert "GL038" in rule_ids(scan([str(tmp_path)]))


def test_hoisted_jsx_prop_not_flagged(tmp_path):
    write(tmp_path, "Comp.jsx", "const B = () => <Foo onClick={handleClick} />;\n")
    assert "GL038" not in rule_ids(scan([str(tmp_path)]))


def test_detects_kotlin_short_delay(tmp_path):
    write(tmp_path, "Poll.kt", "suspend fun bad() { while (true) { delay(50) } }\n")
    assert "GL002" in rule_ids(scan([str(tmp_path)]))


def test_kotlin_long_delay_not_flagged(tmp_path):
    write(tmp_path, "Poll.kt", "suspend fun good() { while (true) { delay(5000) } }\n")
    assert "GL002" not in rule_ids(scan([str(tmp_path)]))


def test_detects_swift_short_timer_interval(tmp_path):
    write(
        tmp_path,
        "Poll.swift",
        "Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { _ in tick() }\n",
    )
    assert "GL002" in rule_ids(scan([str(tmp_path)]))


def test_swift_long_timer_interval_not_flagged(tmp_path):
    write(
        tmp_path,
        "Poll.swift",
        "Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { _ in tick() }\n",
    )
    assert "GL002" not in rule_ids(scan([str(tmp_path)]))


# --- PR #27 review follow-ups: each of these reproduced a real defect. ---


def test_apostrophe_does_not_unblank_the_rest_of_the_file(tmp_path):
    # `echo don't` opened a quote that never closed, so every comment after it
    # stayed visible to the rules and prose was reported as code.
    write(tmp_path, "x.sh", "echo don't\n# never use sleep 0.01 in a loop\n")
    assert "GL002" not in rule_ids(scan([str(tmp_path)]))


def test_apostrophe_does_not_hide_a_real_finding(tmp_path):
    write(tmp_path, "x.sh", "echo don't\nsleep 0.01\n")
    assert "GL002" in rule_ids(scan([str(tmp_path)]))


def test_busy_loop_found_despite_return_in_nested_function(tmp_path):
    # The `return` belongs to the callback, not to the loop, so it is not an
    # exit condition — the loop still pegs a core.
    write(
        tmp_path,
        "a.py",
        "def serve():\n    while True:\n        def _cb():\n            return 1\n        _cb()\n",
    )
    assert "GL001" in rule_ids(scan([str(tmp_path)]))


def test_quadratic_rebuild_name_bindings_are_per_scope(tmp_path):
    # `total = 0` in a() must not exempt the genuine string rebuild in b().
    write(
        tmp_path,
        "a.py",
        "def a():\n"
        "    total = 0\n"
        "    for x in range(10):\n"
        "        total += x\n"
        "\n"
        "def b():\n"
        "    total = ''\n"
        "    for x in range(10):\n"
        "        total += str(x)\n",
    )
    findings = [f for f in scan([str(tmp_path)]) if f["rule"] == "GL007"]
    assert [f["line"] for f in findings] == [9]


def test_fetch_depth_exemption_is_per_job(tmp_path):
    write(
        tmp_path,
        "w.yml",
        "name: demo\n"
        "jobs:\n"
        "  secrets:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          fetch-depth: 0\n"
        "      - uses: gitleaks/gitleaks-action@v2\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          fetch-depth: 0\n"
        "      - run: make build\n",
    )
    findings = [f for f in scan([str(tmp_path)]) if f["rule"] == "GL004"]
    assert [f["line"] for f in findings] == [13]


def test_python_file_is_parsed_once(tmp_path, monkeypatch):
    import greenlint

    f = write(tmp_path, "a.py", "x = 1\n")
    calls = []
    original = greenlint._parse_python
    monkeypatch.setattr(
        greenlint,
        "_parse_python",
        lambda p, t: (calls.append(p), original(p, t))[1],
    )
    list(greenlint.scan_file(f))
    assert len(calls) == 1


def test_multiline_ignore_array_is_parsed(tmp_path):
    write(tmp_path, "tests/q.sql", "SELECT * FROM users;\n")
    cfg = write(tmp_path, ".greenlint.toml", 'ignore = [\n  "*/examples/*",\n  "*/tests/*",\n]\n')
    assert scan([str(tmp_path)], load_config(str(cfg))) == []


def test_relative_ignore_glob_applies(tmp_path, monkeypatch):
    # `greenlint .` yields `tests/q.sql`, which `*/tests/*` cannot match unless
    # the path is anchored — the globs silently did nothing.
    write(tmp_path, "tests/q.sql", "SELECT * FROM users;\n")
    cfg = write(tmp_path, ".greenlint.toml", 'ignore = ["*/tests/*"]\n')
    monkeypatch.chdir(tmp_path)
    assert scan(["."], load_config(str(cfg))) == []


def test_string_instead_of_list_is_rejected(tmp_path):
    import pytest

    cfg = write(tmp_path, ".greenlint.toml", 'disable = "GL005"\n')
    with pytest.raises(SystemExit, match="must be a list"):
        load_config(str(cfg))


def test_malformed_config_aborts(tmp_path):
    import pytest

    cfg = write(tmp_path, ".greenlint.toml", "disable = [\n")
    with pytest.raises(SystemExit, match="invalid TOML"):
        load_config(str(cfg))


def test_core_seconds_per_gram_anchor():
    """Every hint is sanity-checked against this: at 480 gCO2e/kWh a gram is
    7.5 kJ, which is ~500 seconds of a 15 W core.

    It is the arithmetic that condemned the old per-call figures. "~0.001 gCO2e
    per call" claimed half a core-second for a string format, overstating it by
    roughly a millionfold."""
    assert greenlint.core_seconds_per_gram() == 500.0
    # Dirtier grid -> fewer core-seconds buy a gram.
    assert greenlint.core_seconds_per_gram(960.0) == 250.0
    assert greenlint.core_seconds_per_gram(watts=30.0) == 250.0


def test_no_hint_quotes_a_fictional_per_call_gram_figure():
    """A function call costs nanojoules, so a per-call gram figure cannot be
    real. Hot-path rules must describe scaling instead — this is what regressed
    before, in prose nobody checked."""
    per_call = [
        rule_id
        for rule_id, hint in greenlint.CO2E_HINTS.items()
        if "gCO2e per call" in hint or "gCO2e per iteration" in hint
    ]
    assert per_call == [], f"per-call gram figures reintroduced: {per_call}"


def test_cron_hint_multiplies_out_to_something_sane():
    """GL003 used to read "~1-5 gCO2e per unnecessary run x 1440 runs/day",
    which resolves to 1.4-7.2 kg/day for one cron entry — roughly 1000x high,
    and published as a headline number."""
    hint = greenlint.CO2E_HINTS["GL003"]
    assert "kg" not in hint
    # The hint now quotes the anchor and one worked example instead of a made-up
    # per-run band: runtime/500 is the whole calculation, and a job that overruns
    # its minute scales through the same formula instead of breaking it.
    assert "500 core-seconds" in hint
    assert "~6 gCO2e/day" in hint


def test_scan_file_accepts_text_instead_of_reading_the_file(tmp_path):
    """The editor extension scans unsaved buffers. Without a text override it
    would have to write a temp file per keystroke to get a finding."""
    path = tmp_path / "q.sql"  # never created on disk
    findings = list(greenlint.scan_file(path, text="SELECT * FROM users;\n"))
    assert rule_ids(findings) == {"GL005"}
    assert findings[0]["file"] == str(path)


def test_scan_file_text_override_still_picks_language_from_the_path(tmp_path):
    """`SELECT *` in a .md file is prose, not a query: the buffer's contents
    decide what matches, its name decides which rules are even tried."""
    assert list(greenlint.scan_file(tmp_path / "notes.md", text="SELECT * FROM users;\n")) == []


def test_iter_files_selects_what_scan_scans(tmp_path):
    """Two walkers would drift, and a file the CLI ignores still being flagged
    in the editor is the kind of disagreement nobody debugs."""
    write(tmp_path, "vendor/q.sql", "SELECT * FROM users;\n")
    write(tmp_path, "src/q.sql", "SELECT * FROM users;\n")
    cfg = load_config(str(write(tmp_path, ".greenlint.toml", 'ignore = ["*/vendor/*"]\n')))
    walked = {str(f) for f in greenlint.iter_files([str(tmp_path)], cfg)}
    assert str(tmp_path / "src" / "q.sql") in walked
    assert str(tmp_path / "vendor" / "q.sql") not in walked
    assert {f["file"] for f in scan([str(tmp_path)], cfg)} == {str(tmp_path / "src" / "q.sql")}


def test_finding_sort_key_orders_high_severity_first(tmp_path):
    write(tmp_path, "ci.yml", "cron: '* * * * *'\nfetch-depth: 0\n")
    findings = scan([str(tmp_path)])
    assert findings == sorted(findings, key=greenlint.finding_sort_key)
    assert findings[0]["severity"] == "high"


def test_scannable_matches_whether_scan_file_can_find_anything(tmp_path):
    """The editor's prefilter must never skip a file the CLI would report on."""
    assert greenlint.scannable(tmp_path / "a.py")
    assert greenlint.scannable(tmp_path / "Dockerfile")
    assert not greenlint.scannable(tmp_path / "logo.png")
    assert not greenlint.scannable(tmp_path / "Dockerfile.prod")  # applicable() is exact-name


def test_is_ignored_matches_the_walkers_own_filtering(tmp_path):
    cfg = {"disable": set(), "ignore": ["*/vendor/*"]}
    assert greenlint.is_ignored(tmp_path / "vendor" / "q.sql", cfg)
    assert not greenlint.is_ignored(tmp_path / "src" / "q.sql", cfg)
    assert not greenlint.is_ignored(tmp_path / "vendor" / "q.sql", {"ignore": []})


# --- the shared AST index -------------------------------------------------
# These lock in what the rules read off it. The rules used to walk the tree
# themselves, six times over; nothing about their answers may depend on that
# having become one walk.


def test_index_python_collects_loops_functions_and_classes():
    tree = greenlint._parse_python(Path("a.py"), SAMPLE)
    index = greenlint.index_python(tree)
    assert [node.lineno for node, _ in index.fors] == [4, 5, 9]
    assert [node.lineno for node, _ in index.whiles] == [2]
    assert [node.lineno for node, _ in index.tries] == [10]
    assert [node.name for node in index.functions] == ["loops", "clean", "method"]
    assert [node.name for node in index.classes] == ["K"]


def test_index_python_records_the_loops_enclosing_each_node():
    tree = greenlint._parse_python(Path("a.py"), SAMPLE)
    index = greenlint.index_python(tree)
    enclosing = {node.lineno: [loop.lineno for loop in loops] for node, loops in index.fors}
    assert enclosing == {4: [], 5: [4], 9: []}
    # The `try` on line 10 is inside the loop on line 9: that is exactly the
    # question GL031 used to answer by walking every loop's subtree.
    assert [[loop.lineno for loop in loops] for _, loops in index.tries] == [[9]]


def test_index_python_marks_only_scopes_that_own_a_loop():
    """GL007 skips a scope with no loop in it rather than walking it to find
    out, and most functions have no loop."""
    tree = greenlint._parse_python(Path("a.py"), SAMPLE)
    index = greenlint.index_python(tree)
    owners = {getattr(scope, "name", "<module>") for scope in index.loop_scopes}
    assert owners == {"loops", "method"}
    assert not any(getattr(scope, "name", "") == "clean" for scope in index.loop_scopes)


SAMPLE = """\
def loops(xs):
    while True:
        pass
    for x in xs:
        for y in xs:
            pass
class K:
    def method(self, xs):
        for x in xs:
            try:
                pass
            except ValueError:
                continue
def clean(a, b):
    return a + b
"""


# --- comment blanking -----------------------------------------------------
# Rewritten to jump between interesting characters instead of visiting every
# one. Verified against the previous implementation over ~158,000 generated
# (text, language) pairs; these are the shapes worth keeping in the suite.


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("f.py", "x = 1  # SELECT * FROM t\n", "x = 1                   \n"),
        # A docstring is prose; an ordinary string literal is a real query.
        (
            "f.py",
            "'''SELECT * FROM t'''\nq = 'SELECT * FROM t'\n",
            "'''SELECT * FROM t'''\nq = 'SELECT * FROM t'\n",
        ),
        # An apostrophe must not open a string that swallows the rest of the file.
        ("f.sh", "echo don't # SELECT * FROM t\n", "echo don't                  \n"),
        ("f.sql", "SELECT * FROM t; -- SELECT * FROM u\n", "SELECT * FROM t;                   \n"),
        (
            "f.js",
            "/* SELECT * FROM t */ q('SELECT * FROM u') // SELECT * FROM v\n",
            "                      q('SELECT * FROM u')                   \n",
        ),
        ("f.js", "/* unterminated SELECT * FROM t\n", "                               \n"),
        # A quote is reset at the newline, so the next line's comment is seen.
        (
            "f.sh",
            "a = 'unterminated\nb # SELECT * FROM t\n",
            "a = 'unterminated\nb                  \n",
        ),
        ("f.py", "no comment token here at all\n", "no comment token here at all\n"),
        # No comment syntax known for this extension: left alone entirely.
        ("f.md", "# SELECT * FROM t\n", "# SELECT * FROM t\n"),
    ],
)
def test_blank_comments_shapes(name, text, expected):
    assert greenlint._blank_comments(text, Path(name)) == expected


def test_blank_comments_preserves_length_and_newlines():
    text = "a = 1  # one\nb = 2  /* two */ c\n# three\n"
    for name in ("f.py", "f.js", "f.sql", "f.sh"):
        blanked = greenlint._blank_comments(text, Path(name))
        assert len(blanked) == len(text)
        assert [i for i, c in enumerate(blanked) if c == "\n"] == [
            i for i, c in enumerate(text) if c == "\n"
        ]


def test_blank_spans_returns_the_original_when_there_is_nothing_to_blank():
    text = "unchanged\n"
    assert greenlint._blank_spans(text, []) is text


# --- excludes and the pruning walk ---------------------------------------


def test_cli_exclude_flag_skips_matching_paths(tmp_path, capsys):
    write(tmp_path, "src/q.sql", "SELECT * FROM t;\n")
    write(tmp_path, "vendor/q.sql", "SELECT * FROM t;\n")
    main([str(tmp_path), "--config", str(tmp_path / "none.toml"), "--exclude", "*/vendor/*"])
    out = capsys.readouterr().out
    assert "1 finding(s)" in out
    assert "vendor" not in out


def test_cli_exclude_is_repeatable_and_adds_to_the_config(tmp_path, capsys):
    for name in ("src/q.sql", "vendor/q.sql", "dist/q.sql", "build/q.sql"):
        write(tmp_path, name, "SELECT * FROM t;\n")
    cfg = write(tmp_path, ".greenlint.toml", 'ignore = ["*/build/*"]\n')
    main(
        [
            str(tmp_path),
            "--config",
            str(cfg),
            "--exclude",
            "*/vendor/*",
            "--exclude",
            "*/dist/*",
        ]
    )
    out = capsys.readouterr().out
    assert "1 finding(s)" in out  # only src/ survives config + both flags


def test_prunable_bases_only_takes_patterns_that_cover_a_whole_directory():
    """Pruning on a pattern that does not cover everything below it would stop
    scanning files that are not ignored — silently."""
    assert greenlint.prunable_bases(["*/vendor/*"]) == ["*/vendor"]
    assert greenlint.prunable_bases(["*/vendor/**"]) == ["*/vendor"]
    # Covers only some of the directory.
    assert greenlint.prunable_bases(["*/vendor/*.py"]) == []
    # Covers the directory entry itself, but nothing inside it.
    assert greenlint.prunable_bases(["*/vendor"]) == []
    assert greenlint.prunable_bases(["*"]) == []


def test_walk_files_never_descends_into_pruned_directories(tmp_path, monkeypatch):
    write(tmp_path, "src/app.py", "x = 1\n")
    write(tmp_path, "node_modules/pkg/index.js", "x\n")
    write(tmp_path, ".git/objects/ab/cdef", "x\n")
    write(tmp_path, "vendor/lib/thing.js", "x\n")

    opened = []
    real_scandir = os.scandir

    def watched(path):
        opened.append(str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", watched)
    config = {"disable": set(), "ignore": ["*/vendor/*"]}
    files = [f.name for f in greenlint.iter_files([str(tmp_path)], config)]
    assert files == ["app.py"]
    # Not merely filtered afterwards — never opened.
    assert not any("node_modules" in p or ".git" in p or "vendor" in p for p in opened)


def test_walk_files_prunes_virtualenvs_and_caches(tmp_path, monkeypatch):
    """A virtualenv is thousands of third-party files; walking one is what made
    an editor scan look like a hang."""
    write(tmp_path, "app.py", "x = 1\n")
    write(tmp_path, ".venv/lib/python3.11/site-packages/dep/mod.py", "while True: pass\n")
    write(tmp_path, "env3/lib/site-packages/other/mod.py", "while True: pass\n")
    write(tmp_path, ".mypy_cache/3.11/mod.data.json", "{}\n")

    opened = []
    real_scandir = os.scandir

    def watched(path):
        opened.append(str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", watched)
    files = [f.name for f in greenlint.iter_files([str(tmp_path)])]
    assert files == ["app.py"]
    assert not any("site-packages" in p or "mypy_cache" in p for p in opened)
    # And the same file asked about directly — the editor's path — is skipped,
    # so a buffer opened out of .venv does not sprout squiggles the CLI never
    # reports.
    assert greenlint.is_ignored(tmp_path / ".venv" / "lib" / "mod.py")
    assert not greenlint.is_ignored(tmp_path / "app.py")


def test_walk_files_matches_what_rglob_selected(tmp_path):
    """The pruning walk replaced `Path.rglob`; it must still pick the same
    files, symlinks and all."""
    write(tmp_path, "a.py", "x = 1\n")
    write(tmp_path, "sub/b.py", "x = 1\n")
    (tmp_path / "link.py").symlink_to(tmp_path / "a.py")
    (tmp_path / "linkdir").symlink_to(tmp_path / "sub")
    (tmp_path / "broken.py").symlink_to(tmp_path / "nope.py")
    walked = {f.relative_to(tmp_path).as_posix() for f in greenlint.walk_files(tmp_path)}
    rglobbed = {
        f.relative_to(tmp_path).as_posix()
        for f in tmp_path.rglob("*")
        if f.is_file() and ".git" not in f.parts and "node_modules" not in f.parts
    }
    assert walked == rglobbed
    # Symlinked file yielded; symlinked directory not followed; broken one skipped.
    assert walked == {"a.py", "sub/b.py", "link.py"}


def test_walk_files_survives_an_unreadable_directory(tmp_path):
    write(tmp_path, "ok/a.py", "x = 1\n")
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "b.py").write_text("x = 1\n")
    locked.chmod(0o000)
    try:
        names = {f.name for f in greenlint.walk_files(tmp_path)}
        assert "a.py" in names
    finally:
        locked.chmod(0o755)


# --- baseline -------------------------------------------------------------


def test_baseline_accepts_current_findings_and_still_reports_new_ones(tmp_path, capsys):
    write(tmp_path, "src/q.sql", "SELECT * FROM t;\n")
    baseline = tmp_path / greenlint.BASELINE_FILENAME
    findings = scan([str(tmp_path)])
    assert greenlint.write_baseline(baseline, findings, tmp_path) == 1
    accepted = greenlint.load_baseline(baseline)
    assert greenlint.apply_baseline(findings, accepted, tmp_path) == []
    # A finding in a file the baseline never saw is still reported.
    write(tmp_path, "src/other.sql", "SELECT * FROM u;\n")
    fresh = scan([str(tmp_path)])
    assert len(greenlint.apply_baseline(fresh, accepted, tmp_path)) == 1


def test_fingerprint_is_the_same_for_absolute_and_relative_paths(tmp_path, monkeypatch):
    """The editor reports absolute paths and `greenlint .` reports relative
    ones. A baseline only earns its keep if both honour the same file."""
    write(tmp_path, "src/q.sql", "SELECT * FROM t;\n")
    absolute = scan([str(tmp_path)])[0]
    monkeypatch.chdir(tmp_path)
    relative = scan(["."])[0]
    assert relative["file"] != absolute["file"]
    assert greenlint.fingerprint(relative, ".") == greenlint.fingerprint(absolute, tmp_path)


def test_fingerprint_survives_edits_above_the_finding(tmp_path):
    """Line-insensitive on purpose: a baseline keyed on line numbers is stale
    by the next commit."""
    path = write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    before = greenlint.fingerprint(scan([str(tmp_path)])[0], tmp_path)
    path.write_text("-- a new comment line\n-- and another\nSELECT * FROM t;\n")
    after = scan([str(tmp_path)])[0]
    assert after["line"] == 3
    assert greenlint.fingerprint(after, tmp_path) == before


def test_a_missing_or_broken_baseline_reports_everything(tmp_path):
    """Failing open: a linter that goes quiet because a file it was not asked
    about is malformed is worse than one that reports too much."""
    assert greenlint.load_baseline(tmp_path / "nope.json") == set()
    broken = write(tmp_path, "b.json", "{not json")
    assert greenlint.load_baseline(broken) == set()


def test_cli_writes_and_then_honours_a_baseline(tmp_path, capsys, monkeypatch):
    write(tmp_path, "q.sql", "SELECT * FROM t;\n")
    monkeypatch.chdir(tmp_path)
    main([".", "--config", "nope.toml", "--write-baseline"])
    assert "1 finding(s) accepted" in capsys.readouterr().out
    assert (tmp_path / greenlint.BASELINE_FILENAME).is_file()
    main([".", "--config", "nope.toml"])
    out = capsys.readouterr().out
    assert "0 finding(s)" in out
    assert "1 accepted" in out


def test_cli_rejects_a_baseline_path_that_is_not_there(tmp_path, monkeypatch):
    """An explicit flag that silently does nothing is worse than an error; the
    default file is optional, a named one is not."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="no such baseline"):
        main([".", "--baseline", "missing.json"])


def _docs_anchor(rule):
    """The GitHub heading anchor a front end derives for a rule.

    Mirrors `ruleDocsUrl` in the VS Code extension: GitHub lowercases the
    heading, drops punctuation it does not keep, and turns spaces into hyphens
    — so the em dash leaves the doubled hyphen you see in the result.
    """
    slug = f"{rule['id']} — {rule['message']}".lower()
    slug = re.sub(r"[^a-z0-9 _-]", "", slug)
    return slug.replace(" ", "-")


def test_every_rule_has_a_matching_heading_in_the_docs():
    """The rules reference is addressable per rule, and the address is derived
    from the rule's own message.

    Editors link a finding straight to its section, so a heading that no longer
    matches its rule is a link that silently goes nowhere. That is a
    documentation drift no reader would notice and no other test would catch.
    """
    doc = (Path(__file__).resolve().parent.parent / "docs" / "rules.md").read_text()
    missing = [r["id"] for r in greenlint.RULES if f"## {r['id']} — {r['message']}" not in doc]
    assert not missing, f"docs/rules.md heading does not match the rule message: {missing}"


def test_rule_anchors_are_unique():
    anchors = [_docs_anchor(r) for r in greenlint.RULES]
    assert len(set(anchors)) == len(anchors)


# --- Coverage added for C#, Kotlin, Swift and Ruby (issue #34) ---------------
#
# Every rule gets both halves: a true positive, and a near-miss that must NOT
# fire. A rule with only the first is how a linter earns the reputation of
# being noise, and these languages had one rule each — a clean run said
# "barely checked", not "clean".


def scan_one(tmp_path, name, content):
    write(tmp_path, name, content)
    return rule_ids(scan([str(tmp_path)]))


class TestCSharpRules:
    def test_new_httpclient_per_call(self, tmp_path):
        assert "GL039" in scan_one(tmp_path, "a.cs", "var c = new HttpClient();\n")

    def test_a_reused_client_is_not_flagged(self, tmp_path):
        # The fix the rule asks for must not itself trip the rule.
        assert "GL039" not in scan_one(
            tmp_path,
            "b.cs",
            "private static readonly HttpClient Client = _factory.CreateClient();\n",
        )

    def test_blocking_on_a_task(self, tmp_path):
        ids = scan_one(tmp_path, "c.cs", "var r = FetchAsync().Result;\ntask.Wait();\n")
        assert "GL040" in ids

    def test_await_is_not_flagged(self, tmp_path):
        assert "GL040" not in scan_one(tmp_path, "d.cs", "var r = await FetchAsync();\n")

    def test_tolist_just_to_iterate(self, tmp_path):
        assert "GL041" in scan_one(
            tmp_path, "e.cs", "foreach (var x in items.Where(i => i.Ok).ToList()) { }\n"
        )

    def test_tolist_kept_as_a_variable_is_not_flagged(self, tmp_path):
        # Materialising to reuse it is legitimate; only the throwaway is not.
        assert "GL041" not in scan_one(
            tmp_path,
            "f.cs",
            "var list = items.Where(i => i.Ok).ToList();\nforeach (var x in list) { }\n",
        )


class TestKotlinRules:
    def test_globalscope(self, tmp_path):
        assert "GL042" in scan_one(tmp_path, "a.kt", "GlobalScope.launch { work() }\n")

    def test_a_scoped_launch_is_not_flagged(self, tmp_path):
        assert "GL042" not in scan_one(tmp_path, "b.kt", "viewModelScope.launch { work() }\n")

    def test_filter_map_chain(self, tmp_path):
        assert "GL043" in scan_one(
            tmp_path, "c.kt", "val out = xs.filter { it.ok }.map { it.name }\n"
        )

    def test_mapnotnull_is_not_flagged(self, tmp_path):
        assert "GL043" not in scan_one(
            tmp_path, "d.kt", "val out = xs.mapNotNull { if (it.ok) it.name else null }\n"
        )

    def test_runblocking(self, tmp_path):
        assert "GL044" in scan_one(tmp_path, "e.kt", "runBlocking { fetch() }\n")

    def test_a_suspend_call_is_not_flagged(self, tmp_path):
        assert "GL044" not in scan_one(tmp_path, "f.kt", "suspend fun go() { fetch() }\n")


class TestSwiftRules:
    def test_filter_map_chain(self, tmp_path):
        assert "GL045" in scan_one(
            tmp_path, "a.swift", "let out = xs.filter { $0.ok }.map { $0.name }\n"
        )

    def test_compactmap_is_not_flagged(self, tmp_path):
        assert "GL045" not in scan_one(
            tmp_path, "b.swift", "let out = xs.compactMap { $0.ok ? $0.name : nil }\n"
        )

    def test_dispatch_sync(self, tmp_path):
        assert "GL046" in scan_one(tmp_path, "c.swift", "DispatchQueue.main.sync { render() }\n")

    def test_dispatch_async_is_not_flagged(self, tmp_path):
        assert "GL046" not in scan_one(
            tmp_path, "d.swift", "DispatchQueue.main.async { render() }\n"
        )

    def test_a_new_session_per_request(self, tmp_path):
        assert "GL047" in scan_one(
            tmp_path, "e.swift", "let s = URLSession(configuration: .default)\n"
        )

    def test_shared_session_is_not_flagged(self, tmp_path):
        assert "GL047" not in scan_one(tmp_path, "f.swift", "let s = URLSession.shared\n")


class TestRubyRules:
    def test_string_built_with_plus_equals_in_a_loop(self, tmp_path):
        assert "GL048" in scan_one(tmp_path, "a.rb", "items.each do |i|\n  out += i.to_s\nend\n")

    def test_shovel_operator_is_not_flagged(self, tmp_path):
        # << appends in place; it is the fix, not the smell.
        assert "GL048" not in scan_one(
            tmp_path, "b.rb", "items.each do |i|\n  out << i.to_s\nend\n"
        )

    def test_query_inside_a_loop(self, tmp_path):
        assert "GL049" in scan_one(
            tmp_path,
            "c.rb",
            "orders.each do |o|\n  o.customer = Customer.find_by(id: o.cid)\nend\n",
        )

    def test_a_preloaded_association_is_not_flagged(self, tmp_path):
        assert "GL049" not in scan_one(
            tmp_path, "d.rb", "Order.includes(:customer).each do |o|\n  puts o.customer.name\nend\n"
        )

    def test_map_flatten(self, tmp_path):
        assert "GL050" in scan_one(tmp_path, "e.rb", "rows.map { |r| r.tags }.flatten\n")

    def test_flat_map_is_not_flagged(self, tmp_path):
        assert "GL050" not in scan_one(tmp_path, "f.rb", "rows.flat_map { |r| r.tags }\n")


def test_every_rule_states_its_energy_rationale():
    # A rule with no rationale is a style opinion wearing a carbon badge.
    for rule in greenlint.RULES:
        assert rule["id"] in greenlint.CO2E_HINTS, f"{rule['id']} has no CO2e hint"
        assert rule["suggestion"], f"{rule['id']} has no suggestion"


def test_comment_syntax_covers_every_language_with_a_rule():
    # An extension with rules but no comment syntax cannot be suppressed
    # inline, which is the escape hatch every false positive needs.
    exts = {ext for rule in greenlint.RULES for ext in rule["langs"] if ext.startswith(".")}
    known = set(greenlint.COMMENT_SYNTAX)
    assert exts <= known, f"no comment syntax for {sorted(exts - known)}"


# --- the fast paths still answer what the slow ones did ----------------------


def test_line_numbers_are_right_when_a_rule_fires_many_times(tmp_path):
    """Line numbers come from an index built once per file rather than by
    counting newlines per match, which was quadratic. The answer must not move.
    """
    # One line repeated: the rule fires per occurrence, and a fixture that
    # builds a query string inline is what an injection scanner goes looking
    # for — even when the building is a repeat of one literal.
    query = "SELECT * FROM t;\n"
    f = write(tmp_path, "dump.sql", query * 500)
    lines = [x["line"] for x in greenlint.scan_file(f) if x["rule"] == "GL005"]
    assert lines == list(range(1, 501))


def test_line_numbers_survive_a_match_at_the_start_of_a_line(tmp_path):
    f = write(tmp_path, "q.sql", "-- header\nSELECT * FROM t;\n\nSELECT * FROM u;\n")
    assert [x["line"] for x in greenlint.scan_file(f) if x["rule"] == "GL005"] == [2, 4]


def test_the_language_index_selects_the_same_rules_as_applicable():
    """`scan_file` looks its rules up by language instead of asking every rule
    whether it applies. The two answers have to be the same set."""
    suffixes = {ext for rule in greenlint.RULES for ext in rule["langs"]}
    for suffix in suffixes:
        path = Path("Dockerfile" if suffix == "Dockerfile" else f"x{suffix}")
        expected = {
            r["id"]
            for r in greenlint.RULES
            if greenlint.applicable(r, path)
            and r["pattern"] is not None
            and r["id"] not in greenlint.AST_RULE_IDS
        }
        indexed = {r["id"] for r in greenlint.PATTERN_RULES_BY_LANG.get(suffix, ())}
        assert indexed == expected, suffix


def test_scannable_agrees_with_the_rule_table():
    for suffix in {ext for rule in greenlint.RULES for ext in rule["langs"]}:
        path = Path("Dockerfile" if suffix == "Dockerfile" else f"x{suffix}")
        assert greenlint.scannable(path) is True
    assert greenlint.scannable(Path("photo.png")) is False


def test_ignore_globs_match_the_same_paths_as_fnmatch():
    """The ignore list is compiled to one regex instead of run glob by glob;
    `normcase` has to stay, or the globs go case-sensitive on Windows."""
    import fnmatch

    patterns = ["*/tests/*", "tests/*", "*.min.js", "*/vendor/*.py", "dist/*"]
    paths = [
        "tests/x.py",
        "/p/tests/x.py",
        "x.min.js",
        "vendor/a.py",
        "/p/vendor/a.py",
        "dist/a",
        "src/a.py",
    ]
    for path in paths:
        forms = (path, path if path.startswith("/") else "/" + path)
        expected = any(fnmatch.fnmatch(s, p) for p in patterns for s in forms)
        assert greenlint._matches_any(path, patterns) is expected, path


def test_a_file_no_rule_targets_is_not_even_read(tmp_path):
    """`scan_file` returns before opening a file whose language no rule
    mentions: it could only ever match nothing, and a checkout is mostly those.
    """
    if os.geteuid() == 0:
        pytest.skip("root reads unreadable files, so the check cannot fail")
    f = write(tmp_path, "logo.png", "SELECT * FROM t;\n")
    f.chmod(0o000)  # unreadable: opening it at all would be the bug
    try:
        assert list(greenlint.scan_file(f)) == []
        assert list(greenlint.scan_file(f, text="SELECT * FROM t;\n")) == []
    finally:
        f.chmod(0o644)


# --- string literals are not code (GL033 follow-up: the false positives) -----
#
# The rules are regex over text, and the largest remaining source of noise in
# JS/Go/Rust was matching the *inside of a string literal*: a code sample in a
# fixture, a message that quotes the pattern, a SQL string that happens to hold
# a sleep call. Comments were already blanked; strings were not.


def scan_source(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source)
    return list(scan_file(path))


def ids_for(tmp_path, name, source):
    return sorted(f["rule"] for f in scan_source(tmp_path, name, source))


def test_code_shaped_rule_ignores_a_match_inside_a_string(tmp_path):
    # The pattern quoted in a fixture or an error message is not the pattern.
    real = ids_for(tmp_path, "a.go", "func f() {\n\ttime.Sleep(10 * time.Millisecond)\n}\n")
    assert "GL002" in real

    quoted = ids_for(
        tmp_path, "b.go", 'func f() {\n\tmsg := "time.Sleep(10 * time.Millisecond)"\n}\n'
    )
    assert "GL002" not in quoted


def test_embedded_content_rules_still_match_inside_strings(tmp_path):
    # The other half of the distinction, and the reason this is per-rule rather
    # than a blanket pass: `SELECT * FROM t` in a Go file is ALWAYS inside a
    # string literal, and it is a real query.
    found = ids_for(tmp_path, "q.go", 'func f() {\n\tq := "SELECT * FROM users"\n}\n')
    assert "GL005" in found


def test_blank_strings_preserves_offsets_and_lines(tmp_path):
    # Line numbers are computed against this view, so a byte lost here points
    # every finding in the file at the wrong line.
    src = 'a := "one"\nb := "two"\nc := 1\n'
    out = _blank_strings(src, tmp_path / "x.go")
    assert len(out) == len(src)
    assert out.count("\n") == src.count("\n")
    assert "one" not in out and "two" not in out
    assert "a :=" in out and "c := 1" in out


def test_blank_strings_handles_escaped_quotes(tmp_path):
    # A mishandled escape closes the string early and leaves the rest of the
    # line visible — which is the false positive coming straight back.
    src = 's := "he said \\"sleep(1)\\" loudly"; time.Sleep(1)\n'
    out = _blank_strings(src, tmp_path / "x.go")
    assert "he said" not in out
    assert "time.Sleep(1)" in out  # the real call survives


def test_blank_strings_does_not_trip_on_an_apostrophe(tmp_path):
    # The trap _blank_comments documents: `don't` opening a string that never
    # closes would blank the rest of the line, hiding real findings.
    src = "// it's fine\nx := 1; y := 2\n"
    out = _blank_strings(src, tmp_path / "x.go")
    assert "x := 1; y := 2" in out


def test_blank_strings_leaves_a_language_it_does_not_know(tmp_path):
    # Better a false negative than a scanner that desynchronises and produces
    # false positives for the rest of the file.
    src = 'key: "value"\n'
    assert _blank_strings(src, tmp_path / "x.yml") == src


def test_a_multiline_string_keeps_its_contents_visible(tmp_path):
    # Quote state resets at the newline, so this is a known false negative —
    # and it is the safe direction, since a linter that cries wolf is switched
    # off entirely.
    src = "s := `\n\ttime.Sleep(1 * time.Millisecond)\n`\n"
    out = _blank_strings(src, tmp_path / "x.go")
    assert "time.Sleep" in out
