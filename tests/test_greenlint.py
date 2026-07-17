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
