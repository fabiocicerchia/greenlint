# Rules reference

Every rule below follows the same shape: a language/file-type match, a
detection mechanism (a single regex, an AST walk, or a whole-file/whole-block
check), a message, and a `suggestion` that doubles as the energy rationale.
Run `greenlint --list-rules` for the always-current, terse version of this
list — this file adds the *why* and a minimal trigger/fix example for each.

Detection mechanism key:

- **regex** — a single compiled pattern matched against the file's raw text.
- **AST** — a Python `ast` walk (more precise than regex, Python-only).
- **whole-file/block** — a small dedicated function that checks for the
  *absence* of something across a whole file or resource block (what a
  single regex match can't express — see `docs/architecture.md`).

---

## GL001 — busy loop without sleep

- **Languages:** `.py` · **Severity:** medium · **Mechanism:** AST
- **Triggers on:** a Python `while True:` loop whose body never reaches a
  `sleep()` call (walked via AST, not a text search, so a `sleep` elsewhere
  in the file doesn't hide a real busy loop, and a real `sleep()` doesn't get
  flagged just because the word "sleep" is absent nearby).
- **Example:** `while True: check_queue()`
- **Fix:** poll with a backoff/sleep, or switch to an event-driven wait
  (queue, webhook, condition variable).

## GL002 — sub-100ms polling interval

- **Languages:** `.py .js .ts .sh .go .rs .java .php .pl .c .h .cpp .cc .hpp .kt .swift .cs`
- **Severity:** low · **Mechanism:** regex (one alternative per language idiom)
- **Triggers on:** a sleep/timer call configured under 100ms: JS
  `setInterval(fn, 50)`, Python `time.sleep(0.05)`, bash `sleep 0.05`, Go
  `time.Sleep(50 * time.Millisecond)`, Rust
  `thread::sleep(Duration::from_millis(50))`, Java/Kotlin/C# `Thread.sleep(50)`,
  PHP/Perl/C/C++ `usleep(50000)`, Kotlin coroutine `delay(50)`, Swift
  `Timer.scheduledTimer(withTimeInterval: 0.05, ...)`.
- **Fix:** tight polling burns CPU on wake-ups that usually find nothing
  changed; prefer push/webhooks/events, or at least widen the interval.

## GL003 — cron job scheduled every minute

- **Languages:** `.yml .yaml` · **Severity:** high · **Mechanism:** regex
- **Triggers on:** a GitHub Actions `cron:` or Kubernetes `CronJob`
  `schedule:` value of `* * * * *`.
- **Fix:** every-minute schedules rarely need it; widen to the loosest
  interval the job can tolerate.

## GL004 — full git history clone in CI

- **Languages:** `.yml .yaml` · **Severity:** medium · **Mechanism:** regex
- **Triggers on:** `fetch-depth: 0` (an unshallow clone) in a CI workflow.
- **Fix:** unshallow clones download and store far more history than most
  jobs need; use a shallow fetch-depth unless full history is required.

## GL005 — SELECT * query

- **Languages:** `.sql .py .php .go .js .ts .rs .java .c .h .cpp .cc .hpp .pl .sh`
- **Severity:** medium · **Mechanism:** regex
- **Triggers on:** `SELECT * FROM` in any file, source or SQL (plain-text
  match, so it also catches SQL embedded as a string literal).
- **Fix:** fetch only the columns you need — less I/O, less network, less
  RAM on both ends.

## GL006 — full-fat base image

- **Languages:** `Dockerfile` · **Severity:** medium · **Mechanism:** regex
- **Triggers on:** `FROM ubuntu` / `FROM debian` without a `-slim` variant.
- **Fix:** prefer `-slim`/alpine/distroless: smaller pulls, less storage,
  faster cold starts.

## GL007 — append inside loop (possible O(n) rebuild pattern)

- **Languages:** `.py` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** a `.append(...)` call on the line after a `for`.
- **Fix:** consider a comprehension or generator; less allocation churn per
  iteration.

## GL008 — very large instance type hardcoded

- **Languages:** `.tf .tofu` · **Severity:** high · **Mechanism:** regex
- **Triggers on:** an `instance_type` of `m/c/r*.8xlarge` or larger.
- **Fix:** check real utilisation; rightsize or move to autoscaling instead
  of provisioning for peak.

## GL009 — apt-get install without --no-install-recommends

- **Languages:** `Dockerfile` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `apt-get install` with no `--no-install-recommends` flag
  on the same line.
- **Fix:** recommended/suggested packages bloat the image; skip them to cut
  pull, transfer, and storage energy.

## GL010 — pip install without --no-cache-dir

- **Languages:** `Dockerfile` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `pip`/`pip3 install` with no `--no-cache-dir` flag on the
  same line.
- **Fix:** the wheel cache gets baked into the image layer otherwise; skip
  it to shrink pulls and storage.

## GL011 — img tag missing lazy loading

- **Languages:** `.html` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** an `<img>` tag with no `loading=` attribute.
- **Fix:** add `loading="lazy"` to defer offscreen image loads — less
  bandwidth and render work on initial page load.

## GL012 — database query executed inside a loop (N+1 pattern)

- **Languages:** `.py` · **Severity:** medium · **Mechanism:** regex
- **Triggers on:** a `.execute(...)` call on the line right after a `for`
  header (e.g. `for id in ids: cursor.execute(...)`).
- **Fix:** batch into one query (`WHERE id IN (...)`) instead of one
  round-trip per item; cuts DB CPU and network energy.

## GL013 — S3 bucket without a lifecycle policy

- **Languages:** `.tf .tofu` · **Severity:** low · **Mechanism:** whole-block
- **Triggers on:** an `aws_s3_bucket` resource block with no `lifecycle`
  keyword anywhere inside it.
- **Fix:** add a `lifecycle_rule` (or a separate
  `aws_s3_bucket_lifecycle_configuration`) to tier or expire stale data
  instead of leaving it in hot storage forever.

## GL014 — Kubernetes workload without CPU/memory requests or limits

- **Languages:** `.yml .yaml` · **Severity:** medium · **Mechanism:** whole-file
- **Triggers on:** a manifest with `kind: Deployment/StatefulSet/DaemonSet/Pod`
  and no `resources:` key anywhere in the file. File-wide, so it can miss
  values injected via a separate Helm/Kustomize overlay.
- **Fix:** set `resources.requests`/`limits` so the scheduler can right-size
  nodes instead of over-provisioning for unbounded containers.

## GL015 — base image pinned to an end-of-life runtime/OS version

- **Languages:** `Dockerfile` · **Severity:** medium · **Mechanism:** regex
- **Triggers on:** `FROM` referencing a known-EOL tag: `python:2*`,
  `node:6/8/10/12/14`, `ubuntu:14.04/16.04/18.04`,
  `debian:7/8/9/wheezy/jessie/stretch`, `centos:6/7`.
- **Fix:** older runtimes lack the performance/efficiency work in newer
  releases and accumulate more security-patch layers over time; move to a
  current stable version. (The exact EOL list is a moving target — expect
  to extend it as more versions age out.)

## GL016 — x86 instance family with an ARM/Graviton equivalent available

- **Languages:** `.tf .tofu` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `instance_type` in the `t2/t3/m4/m5/c4/c5/r4/r5` families.
- **Fix:** ARM-based instances (`t4g`/`m6g`/`c6g`/`r6g`) draw roughly **40%
  less** energy for equal work — an informational nudge, not every workload can
  move. Deliberately not the "3-4x more efficient" claim that circulates: AWS's
  own published figure is *up to 60% less energy for equal work*
  ([Graviton](https://aws.amazon.com/ec2/graviton/)) and independent benchmarks
  land nearer 45-50%, so 40% is the conservative end. The sibling carbon-badge
  tool uses the same 40%.

## GL017 — GIF referenced for image/animation

- **Languages:** `.html .css` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** a `.gif` file referenced in an `<img src=...>` or a CSS
  `url(...)`. (Can't distinguish an animated GIF from a static one from text
  alone — treat as a nudge, not a certainty.)
- **Fix:** GIF is an obsolete, inefficient animation format; MP4/WebP/AVIF
  (or SVG/CSS animation) give smaller files and less energy per view.

## GL018 — nested loop iterating over the same collection (possible O(n²))

- **Languages:** `.py` · **Severity:** low · **Mechanism:** AST
- **Triggers on:** an inner `for` loop iterating the exact same named
  variable as its enclosing `for` loop (`for i in items: for j in items:`).
  Only matches plain variable names, so `range(n)`/`enumerate(...)` nested
  loops (often legitimate matrix/grid code) are left alone.
- **Fix:** a manual all-pairs scan over the same list costs O(n²); use a
  set/dict for membership tests, or `itertools.combinations`.

## GL019 — HTTP request executed inside a loop (N+1-style network calls)

- **Languages:** `.py` · **Severity:** medium · **Mechanism:** regex
- **Triggers on:** `requests.get/post/put/patch/delete(...)` on the line
  right after a `for` header.
- **Fix:** batch the calls, reuse a `requests.Session`, or gather them
  concurrently instead of one request per iteration.

## GL020 — logging call built eagerly with an f-string or .format()

- **Languages:** `.py` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `logging.debug(f"...")` or `logging.info("...".format(...))`.
- **Fix:** the interpolation runs even when the log level is disabled; use
  `logging.debug("x=%s", x)` for lazy formatting.

## GL021 — row-wise pandas iteration (iterrows/apply(axis=1))

- **Languages:** `.py` · **Severity:** medium · **Mechanism:** regex
- **Triggers on:** `.iterrows()` or `.apply(..., axis=1)`.
- **Fix:** row-wise pandas ops run one Python-level call per row; use
  vectorised column operations for 10-100x fewer CPU cycles.

## GL022 — file opened/read inside a loop

- **Languages:** `.py` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `open(...)`, `pd.read_csv(...)`, or `pd.read_json(...)` on
  the line right after a `for` header.
- **Fix:** repeated opens/reads add a syscall and parse pass per iteration;
  load once outside the loop, or read in chunks.

## GL023 — nested loop with an element swap (manual O(n²) sort)

- **Languages:** `.py` · **Severity:** medium · **Mechanism:** AST
- **Triggers on:** a `for` loop nested in another `for` loop, where the
  inner loop's body contains the idiomatic swap `a[i], a[j] = a[j], a[i]`
  (the textbook shape of a hand-rolled bubble/selection sort).
- **Fix:** built-in `sorted()`/`list.sort()` use Timsort (O(n log n),
  implemented in C); replace the manual swap-based sort.

## GL024 — autoscaling group with min_size == max_size

- **Languages:** `.tf .tofu` · **Severity:** medium · **Mechanism:** whole-block
- **Triggers on:** an `aws_autoscaling_group` whose `min_size` and
  `max_size` are the same literal value.
- **Fix:** a fixed-size "autoscaling" group is provisioned for peak load
  24/7; widen the range so it can actually scale down under low demand.

## GL025 — EBS volume using gp2 instead of gp3

- **Languages:** `.tf .tofu` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `volume_type = "gp2"`.
- **Fix:** gp3 gives the same baseline performance at lower cost and power
  draw per IOP than gp2; migrate unless you rely on gp2's specific burst
  behaviour.

## GL026 — CloudWatch log group without a retention period

- **Languages:** `.tf .tofu` · **Severity:** medium · **Mechanism:** whole-block
- **Triggers on:** an `aws_cloudwatch_log_group` block with no
  `retention_in_days` set.
- **Fix:** logs are kept forever by default, growing storage (and its
  energy footprint) indefinitely; set `retention_in_days`.

## GL027 — static assets served without a cache duration (Express)

- **Languages:** `.js .ts` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `express.static(path)` called with a single argument (no
  options object, so no `maxAge`).
- **Fix:** without `maxAge`, Express sends no `Cache-Control`, so browsers
  re-fetch unchanged files every visit; set
  `{ maxAge: '1y', immutable: true }` for hashed assets.

## GL028 — wildcard import

- **Languages:** `.py` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `from module import *`.
- **Fix:** star imports bind every public name in the module, bloating the
  namespace and import time; import only the names you use.

## GL029 — separate RUN install layer (image layer bloat)

- **Languages:** `Dockerfile` · **Severity:** low · **Mechanism:** whole-file
- **Triggers on:** more than one separate `RUN apt/pip/npm/yum install` line
  (flags every occurrence after the first).
- **Fix:** each `RUN install` creates a new image layer that must be pulled
  and stored; chain installs with `&&` into one `RUN`.

## GL030 — dict .items() iteration discards the key or value

- **Languages:** `.py` · **Severity:** low · **Mechanism:** AST
- **Triggers on:** `for _, v in d.items():` or `for k, _ in d.items():`.
- **Fix:** use `.keys()` or `.values()` directly instead of `.items()` when
  only one side is needed; skips building/unpacking the discarded half.

## GL031 — try/except inside a loop

- **Languages:** `.py` · **Severity:** low · **Mechanism:** AST
- **Triggers on:** a `try` block anywhere inside a `for`/`while` loop.
- **Fix:** exception handling has real per-entry overhead versus a plain
  if-check; hoist the loop inside a single `try`/`except` instead of
  wrapping each iteration.

## GL032 — heap allocation inside a loop

- **Languages:** `.c .h .cpp .cc .hpp` · **Severity:** medium · **Mechanism:** regex
- **Triggers on:** `malloc`/`calloc`/`realloc`/`new` on the line right after
  a `for`/`while` header.
- **Fix:** repeats allocator overhead every iteration; allocate once before
  the loop and reuse the buffer (or `reserve()`/`resize()` for containers).

## GL033 — HorizontalPodAutoscaler with minReplicas == maxReplicas

- **Languages:** `.yml .yaml` · **Severity:** medium · **Mechanism:** whole-file
- **Triggers on:** an HPA manifest whose `minReplicas` and `maxReplicas` are
  the same literal value.
- **Fix:** a fixed-range HPA can't scale down under low demand; widen the
  range so it actually elasticity-scales.

## GL034 — docker-compose service(s) without resource limits

- **Languages:** `.yml .yaml` · **Severity:** medium · **Mechanism:** whole-file
- **Triggers on:** a `services:` (docker-compose/Swarm) file with no
  `mem_limit`, `cpus:`, `memory:`, or `nano_cpus` anywhere in it.
- **Fix:** unbounded containers can consume a whole host's CPU/RAM; set
  `deploy.resources.limits` (Swarm) or `mem_limit`/`cpus` (Compose v2).

## GL035 — LINQ .Count() used just to check emptiness

- **Languages:** `.cs` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `.Count() == 0`, `.Count() != 0`, or `.Count() > 0`.
- **Fix:** `Count()` enumerates the whole sequence; use `.Any()` (or
  `!seq.Any()`), which short-circuits on the first element.

## GL036 — Hash membership check via keys/values.include?

- **Languages:** `.rb` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `.keys.include?(...)` or `.values.include?(...)`.
- **Fix:** materialises the whole keys/values array for an O(n) scan; use
  `.key?`/`.value?` for an O(1) hash lookup.

## GL037 — select().map() chain (two passes over the collection)

- **Languages:** `.rb` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** `.select { ... }.map { ... }` or
  `.select(&:x).map(&:y)`.
- **Fix:** use `filter_map` to select and transform in a single pass instead
  of two full iterations.

## GL038 — inline function or object literal passed as a JSX prop

- **Languages:** `.jsx .tsx` · **Severity:** low · **Mechanism:** regex
- **Triggers on:** a prop value of `={() => ...}` or `={{...}}`.
- **Fix:** a new function/object is allocated every render, defeating
  `memo`/`PureComponent`; hoist it with `useCallback`/`useMemo` or move it
  outside the component.

## Rules

38 rules (GL001–GL038, see `--list-rules`) spanning Python, JS/TS/JSX/TSX,
Go, Rust, Java, Kotlin, Swift, C#, C/C++, PHP, Perl, Ruby, Bash, SQL, HTML,
CSS, Dockerfile, Terraform/OpenTofu, Kubernetes, and docker-compose/Swarm.
See [`docs/rules.md`](rules.md) for the full reference — what each rule
detects, how it's triggered, and the remediation. Rule development is
deliberately open-ended — the rule set *is* the product. Proposals with an
energy rationale are the most valuable contribution.
