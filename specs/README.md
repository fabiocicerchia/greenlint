# Specifications of greenlint

What this code does, one atomic Gherkin scenario per behaviour, read from the code by code-atlas.
Tags: `@verified` a test asserts it · `@inferred` read from the code only · `@gap` an entry point no test covers · `@human` written or amended by a person, never rewritten.

## Code Energy Rules
The catalogue of source-code patterns greenlint flags as energy-wasteful, each with a rationale and a cheaper alternative.

- **Algorithmic waste**: [Flagging heap allocation inside C and C++ loops](code-energy-rules/algorithmic-waste/heap-allocation-in-loops.feature) (2), [Flagging quadratic work in Python](code-energy-rules/algorithmic-waste/python-quadratic-work.feature) (5)
- **Busy waiting and polling**: [Flagging busy waiting and tight polling](code-energy-rules/busy-waiting/busy-waiting-and-polling.feature) (6), [Flagging Python busy loops](code-energy-rules/busy-waiting/python-busy-loops.feature) (3)
- **Data and network access**: [Flagging wasteful queries, requests and file reads](code-energy-rules/data-and-network-access/data-and-network-access.feature) (3)
- **Other language idioms**: [Flagging energy-costly idioms in C#, Kotlin, Swift, Ruby and JSX](code-energy-rules/other-language-idioms/other-language-idioms.feature) (2)
- **Python idioms**: [Flagging energy-costly Python idioms](code-energy-rules/python-idioms/python-idioms.feature) (2), [Flagging wasteful Python idioms in loops](code-energy-rules/python-idioms/python-wasteful-idioms.feature) (3)
- **Web assets**: [Flagging heavy front-end asset delivery](code-energy-rules/web-assets/web-asset-delivery.feature) (2)

## Configuration and Suppression
How a project tunes which rules run, which paths are skipped and which existing findings are accepted.

- **Baselines**: [Accepting existing findings with a baseline](configuration/baselines/baselines.feature) (8), [Accepting existing findings with a baseline](configuration/baselines/cli-baselines.feature) (3)
- **Path exclusion**: [Matching ignore globs against scanned paths](configuration/path-exclusion/ignore-glob-matching.feature) (3)
- **Project config file**: [Tuning a scan with .greenlint.toml](configuration/project-config/project-config-file.feature) (8)

## Developer Tooling and Distribution
Building, packaging, running and demonstrating greenlint outside the core scan.

- **Command-line entry point**: [Running a scan from the command line](developer-tooling/command-line-entry/cli-scan.feature) (6), [Running greenlint from a checkout](developer-tooling/command-line-entry/run-as-python-module.feature) (2)
- **Container distribution**: [Running greenlint from its container image](developer-tooling/container-distribution/container-image.feature) (3)
- **Examples**: [Showing what greenlint flags with the basic example](developer-tooling/examples/basic-example.feature) (1)

## Infrastructure and CI Checks
Rules that find energy waste in container, cloud, orchestration and pipeline configuration files.

- **CI pipelines and schedules**: [Flagging full-history clones in CI](infrastructure-checks/ci-pipelines/ci-full-history-clones.feature) (4), [Flagging schedules that run every minute](infrastructure-checks/ci-pipelines/every-minute-schedules.feature) (2)
- **Cloud resources**: [Checking Terraform for oversized and inefficient cloud resources](infrastructure-checks/cloud-resources/cloud-resource-checks.feature) (3), [Flagging wasteful Terraform resources](infrastructure-checks/cloud-resources/terraform-resource-checks.feature) (4)
- **Container images**: [Checking Dockerfiles for bloated images](infrastructure-checks/container-images/container-image-checks.feature) (3), [Flagging separate install layers in Dockerfiles](infrastructure-checks/container-images/dockerfile-install-layers.feature) (3)
- **Workload orchestration**: [Flagging unbounded and non-elastic workloads](infrastructure-checks/workload-orchestration/workload-resource-bounds.feature) (4)

## Neovim Integration
The greenlint.nvim plugin that runs the CLI from the editor and shows its findings in place.

- **Editor commands**: [Reviewing and managing findings from Neovim](neovim-integration/editor-commands/nvim-editor-commands.feature) (8)
- **Health check and log**: [Troubleshooting the Neovim plugin](neovim-integration/health-and-logging/nvim-health-and-log.feature) (3)
- **In-editor diagnostics**: [Seeing findings in the editor](neovim-integration/in-editor-diagnostics/nvim-diagnostics.feature) (5)
- **Plugin setup**: [Configuring the Neovim plugin](neovim-integration/plugin-setup/nvim-plugin-setup.feature) (3)
- **Scan triggers**: [Scanning files as you edit](neovim-integration/scan-triggers/nvim-scan-triggers.feature) (7)

## Reporting
What greenlint tells the user after a scan, and in which format.

- **Carbon estimates**: [Rough carbon cost of each finding](reporting/carbon-estimates/carbon-estimates.feature) (3)
- **Output formats**: [Ordering findings by what is worth fixing first](reporting/output-formats/finding-order.feature) (1)

## Scanning
How greenlint finds the files to check, works out what language each is, and reads it without being fooled by comments or strings.

- **Comment and string masking**: [Ignoring prose, comments and quoted examples when scanning](scanning/comment-and-string-masking/comment-and-string-masking.feature) (8)
- **File discovery**: [Walking the files to scan](scanning/file-discovery/walking-scan-targets.feature) (4)
- **Finding placement**: [Placing findings in files](scanning/finding-placement/finding-placement.feature) (4), [Scanning a file for energy waste](scanning/finding-placement/scanning-a-file.feature) (6)
- **Language detection**: [Recognising Dockerfiles and other files by name or extension](scanning/language-detection/dockerfile-recognised-by-name.feature) (2)
- **Python structure analysis**: [Judging Python loops and scopes by their structure](scanning/python-structure-analysis/python-loop-and-scope-judgement.feature) (5)
