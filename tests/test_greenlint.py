from greenlint import load_config, main, scan


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
        "def poll():\n    while True:\n        check()\n\n"
        "def other():\n    time.sleep(1)\n",
    )
    assert "GL001" in rule_ids(scan([str(tmp_path)]))


def test_ast_busy_loop_not_flagged_when_loop_actually_sleeps(tmp_path):
    write(tmp_path, "a.py", "def poll():\n    while True:\n        time.sleep(1)\n")
    assert "GL001" not in rule_ids(scan([str(tmp_path)]))


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
    write(tmp_path, "a.py", 'cursor.execute(f"SELECT * FROM users WHERE id IN {user_ids}")\n')
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
    write(tmp_path, "main.tf", 'resource "aws_instance" "web" {\n  instance_type = "m5.large"\n}\n')
    assert "GL016" in rule_ids(scan([str(tmp_path)]))


def test_graviton_instance_family_not_flagged(tmp_path):
    write(tmp_path, "main.tf", 'resource "aws_instance" "web" {\n  instance_type = "m6g.large"\n}\n')
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
    write(tmp_path, "a.py", "def f(items):\n    for i in items:\n        for j in items:\n            pass\n")
    assert "GL018" in rule_ids(scan([str(tmp_path)]))


def test_nested_loop_over_different_collections_not_flagged(tmp_path):
    write(tmp_path, "a.py", "def f(items, others):\n    for i in items:\n        for j in others:\n            pass\n")
    assert "GL018" not in rule_ids(scan([str(tmp_path)]))


def test_detects_http_request_in_loop(tmp_path):
    write(tmp_path, "a.py", "def f(ids):\n    for i in ids:\n        requests.get(f'/x/{i}')\n")
    assert "GL019" in rule_ids(scan([str(tmp_path)]))


def test_batched_http_request_not_flagged(tmp_path):
    write(tmp_path, "a.py", "def f(ids):\n    session.get('/batch', params={'ids': ids})\n")
    assert "GL019" not in rule_ids(scan([str(tmp_path)]))


def test_detects_eager_logging_fstring(tmp_path):
    write(tmp_path, "a.py", 'import logging\ndef f(x):\n    logging.debug(f"x={x}")\n')
    assert "GL020" in rule_ids(scan([str(tmp_path)]))


def test_lazy_logging_not_flagged(tmp_path):
    write(tmp_path, "a.py", 'import logging\ndef f(x):\n    logging.debug("x=%s", x)\n')
    assert "GL020" not in rule_ids(scan([str(tmp_path)]))


def test_detects_pandas_iterrows(tmp_path):
    write(tmp_path, "a.py", "def f(df):\n    for i, row in df.iterrows():\n        print(row)\n")
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
    write(tmp_path, "asg.tf", 'resource "aws_autoscaling_group" "bad" {\n  min_size = 3\n  max_size = 3\n}\n')
    assert "GL024" in rule_ids(scan([str(tmp_path)]))


def test_elastic_autoscaling_group_not_flagged(tmp_path):
    write(tmp_path, "asg.tf", 'resource "aws_autoscaling_group" "good" {\n  min_size = 1\n  max_size = 5\n}\n')
    assert "GL024" not in rule_ids(scan([str(tmp_path)]))


def test_detects_gp2_volume(tmp_path):
    write(tmp_path, "vol.tf", 'resource "aws_ebs_volume" "v" {\n  volume_type = "gp2"\n}\n')
    assert "GL025" in rule_ids(scan([str(tmp_path)]))


def test_gp3_volume_not_flagged(tmp_path):
    write(tmp_path, "vol.tf", 'resource "aws_ebs_volume" "v" {\n  volume_type = "gp3"\n}\n')
    assert "GL025" not in rule_ids(scan([str(tmp_path)]))


def test_detects_log_group_without_retention(tmp_path):
    write(tmp_path, "log.tf", 'resource "aws_cloudwatch_log_group" "l" {\n  name = "app"\n}\n')
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


def test_detects_try_except_in_loop(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(items):\n    for i in items:\n        try:\n            g(i)\n        except ValueError:\n            pass\n",
    )
    assert "GL031" in rule_ids(scan([str(tmp_path)]))


def test_try_except_around_loop_not_flagged(tmp_path):
    write(
        tmp_path,
        "a.py",
        "def f(items):\n    try:\n        for i in items:\n            g(i)\n    except ValueError:\n        pass\n",
    )
    assert "GL031" not in rule_ids(scan([str(tmp_path)]))


def test_detects_malloc_in_loop(tmp_path):
    write(tmp_path, "a.c", "void f(int n) {\n    for (int i = 0; i < n; i++) {\n        int *buf = malloc(100);\n    }\n}\n")
    assert "GL032" in rule_ids(scan([str(tmp_path)]))


def test_malloc_outside_loop_not_flagged(tmp_path):
    write(tmp_path, "a.c", "void f(int n) {\n    int *buf = malloc(100 * n);\n    for (int i = 0; i < n; i++) {\n    }\n}\n")
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


def test_detects_compose_service_without_limits(tmp_path):
    write(tmp_path, "docker-compose.yml", "services:\n  web:\n    image: nginx\n")
    assert "GL034" in rule_ids(scan([str(tmp_path)]))


def test_compose_service_with_mem_limit_not_flagged(tmp_path):
    write(tmp_path, "docker-compose.yml", "services:\n  web:\n    image: nginx\n    mem_limit: 512m\n")
    assert "GL034" not in rule_ids(scan([str(tmp_path)]))


def test_opentofu_files_use_the_same_terraform_rules(tmp_path):
    write(tmp_path, "main.tofu", 'resource "aws_instance" "web" {\n  instance_type = "m5.large"\n}\n')
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
    write(tmp_path, "Poll.swift", "Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { _ in tick() }\n")
    assert "GL002" in rule_ids(scan([str(tmp_path)]))


def test_swift_long_timer_interval_not_flagged(tmp_path):
    write(tmp_path, "Poll.swift", "Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { _ in tick() }\n")
    assert "GL002" not in rule_ids(scan([str(tmp_path)]))
