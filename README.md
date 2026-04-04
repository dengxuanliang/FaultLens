# FaultLens

FaultLens is a deterministic-first CLI agent for paired code-evaluation JSONL analysis.

## Project goal

FaultLens is built around two delivery goals:

- read paired evaluation-log JSONL inputs and automatically analyze wrong-answer causes plus capability weaknesses
- stably process runs up to 1000 cases, persist progress locally, and resume safely after interruption

The current implementation treats `run.db` as the durable source of truth for ingest, deterministic analysis, LLM attribution, final results, resume, and rerender.

## What it does

FaultLens provides the following core capabilities:

- detects which input file is inference-side and which is results-side
- joins records on `inference.id == results.task_id`
- identifies failed cases and separates attributable failures from data/join issues
- extracts generated code from `completion`
- runs deterministic analysis first:
  - language inference
  - syntax checks
  - compile / test execution when supported and sandboxed
  - harness/signature alignment checks
  - canonical/reference diff summaries
- optionally calls an LLM for higher-level root-cause attribution
- aggregates wrong-answer causes into three-layer cause/capability views for reporting
- writes batch reports, full per-case markdown reports, structured JSON outputs, and raw LLM evidence
- persists a durable `run.db` state store so long runs can resume and rerender from local state

## Acceptance status

As of the current `main` branch, the core v1 scope is implemented and validated in tests:

- wrong-answer cause analysis: implemented
- deterministic + LLM attribution pipeline: implemented
- three-layer capability weakness aggregation: implemented
- durable resume after interruption: implemented
- rerender reports from persisted state: implemented
- 1000-case scale handling in tests: implemented
- retryable LLM failure capture with retry ceiling and backlog visibility: implemented

## Inputs

Pass any two JSONL files with the expected schemas; file names do not need to match fixed names.

Inference-side records should include:
- `id`
- `content`
- `canonical_solution`
- `completion`
- optional `labels.*`
- optional `test.code`

Results-side records should include:
- `task_id`
- `accepted`
- optional pass metrics and metadata tags

## Recommended usage flow

For production-style usage, treat FaultLens as a staged local pipeline:

1. Run `analyze` on the paired JSONL files.
2. Let FaultLens ingest records into `run.db`, run deterministic analysis, and attempt LLM attribution where enabled.
3. If the process is interrupted, rerun the same `analyze ... --resume` command against the same inputs.
4. If you only want to rebuild reports from existing state, run `rerender`.

This means resume is driven by persisted task state inside `run.db`, not by rescanning outputs and trying to infer what was already finished.

## Quickstart

### Linux clone-to-run setup

FaultLens targets Python `>=3.11`. On a Linux host that already has Python 3.11 installed:

```bash
git clone <your-repo-url>
cd FaultLens
./scripts/bootstrap.sh
source .venv/bin/activate
faultlens --help
```

If you do not want to activate the virtual environment, use the thin wrapper instead:

```bash
./scripts/run.sh --help
```

### Analyze a paired input batch

After bootstrap, run the CLI either through the activated environment:

```bash
faultlens analyze \
  --input path/to/file-a.jsonl path/to/file-b.jsonl \
  --output-dir ./outputs
```

Or through the wrapper script without activating `.venv`:

```bash
./scripts/run.sh analyze \
  --input path/to/file-a.jsonl path/to/file-b.jsonl \
  --output-dir ./outputs
```

### Optional LLM configuration

Create a project-local `.env` file (auto-loaded from the current working directory):

```bash
cp .env.example .env
```

Then fill your provider settings, for example:

```dotenv
FAULTLENS_API_KEY=your-key
FAULTLENS_BASE_URL=https://your-provider.example/v1
FAULTLENS_MODEL=your-model
```

If you prefer not to store credentials in `.env`, shell environment variables override `.env` values:

```bash
export FAULTLENS_API_KEY=your-key
export FAULTLENS_BASE_URL=https://your-provider.example/v1
export FAULTLENS_MODEL=your-model
faultlens analyze --input path/to/file-a.jsonl path/to/file-b.jsonl
```

Supported environment variables:
- `FAULTLENS_API_KEY`
- `FAULTLENS_BASE_URL`
- `FAULTLENS_MODEL`
- `FAULTLENS_OUTPUT_DIR`
- `FAULTLENS_REQUEST_TIMEOUT`
- `FAULTLENS_EXECUTION_TIMEOUT`
- `FAULTLENS_LLM_MAX_WORKERS`
- `FAULTLENS_LLM_MAX_RETRIES`
- `FAULTLENS_LLM_RETRY_BACKOFF_SECONDS`
- `FAULTLENS_LLM_RETRY_ON_5XX`
- `FAULTLENS_RESUME`

CLI flags:
- `--llm-max-workers`
- `--llm-max-retries`
- `--llm-retry-backoff-seconds`
- `--llm-retry-on-5xx` / `--no-llm-retry-on-5xx`
- `--resume`
- `--case-id` to export one failed case as an extra exemplar alongside the normal full-case export

If LLM settings are absent or the endpoint is unavailable, FaultLens falls back to deterministic-only attribution and still writes reports.

### Resume an interrupted run

Use the exact same input files and output directory:

```bash
faultlens analyze \
  --input path/to/file-a.jsonl path/to/file-b.jsonl \
  --output-dir ./outputs \
  --resume
```

Resume safety is checked against:

- input path and declared order
- detected role
- file size and modification time
- file sha256
- sampled record count
- analysis version
- prompt version
- model and LLM retry/worker settings persisted in `run.db`

If any of these drift, FaultLens rejects resume instead of continuing unsafely.

### Rerender existing outputs

If `run.db` already exists, you can rebuild reports without rescanning the source JSONL files:

```bash
faultlens rerender \
  --output-dir ./outputs
```

### Inspect run status

For operational checks against an existing output directory:

```bash
faultlens status \
  --output-dir ./outputs
```

This prints the current run context as JSON, including case counts, `job_status_counts`, `pending_llm_backlog`, `health_summary`, warning summaries, stored model configuration, capability snapshot, and failure taxonomy.

For a human-readable terminal summary instead of JSON:

```bash
faultlens status \
  --output-dir ./outputs \
  --pretty
```

### Inspect output directory integrity

To quickly validate whether an existing output directory still has the expected top-level artifacts:

```bash
faultlens inspect-output \
  --output-dir ./outputs
```

This prints a small JSON health report and exits non-zero if required artifacts are missing.

`inspect-output` now also performs read-only consistency checks across:
- `case_analysis.jsonl` row count and case ids
- `cases/*.md` full per-case markdown coverage
- `exemplars/*.md` coverage for summary-selected exemplar cases
- `llm_raw_responses/*` coverage for persisted per-case raw-response references
- `summary.json` total case count
- `run_metadata.json` case-count consistency
- `input_manifest.json` and `analysis_manifest.json` presence

If any of these drift, the command reports the exact mismatch and exits non-zero.
When possible, it also returns `recommended_actions` describing whether `rerender`, `analyze --resume`, or a fresh `analyze` is the right next step.

### Diagnose local environment

To quickly inspect whether the current host can run the expected deterministic pipeline:

```bash
faultlens diagnose-env \
  --output-dir ./outputs
```

This prints a read-only JSON snapshot with Python version, sandbox availability, runner/toolchain visibility, LLM env presence, and whether the target output directory already contains `run.db`.

### Export one case markdown on demand

To rerender a single case markdown from persisted state:

```bash
faultlens export-case \
  --output-dir ./outputs \
  --case-id 42
```

By default this rewrites `cases/42.md`. Use `--dest` to export to a different path.

## Output

A normal analysis run writes:
- `run.db`
- `input_manifest.json`
- `analysis_manifest.json`
- `analysis_report.md`
- `case_analysis.jsonl`
- `summary.json`
- `run_metadata.json`
- `hierarchical_root_cause_report.md`
- `cases/<case_id>.md` for every finalized case
- `exemplars/*.md`
- `llm_raw_responses/<case_id>.txt` when an LLM raw reply or error body is available

`run.db` is the durable source of truth for resume and rerender. New runs do not depend on or generate a separate checkpoint database.

Structured outputs include:
- `case_analysis.jsonl`: per-case attribution, parse mode, parse reason, raw-response path, raw-response sha256
- `run_metadata.json`: join stats, model summary, LLM warning log, response-quality stats, `job_status_counts`, `pending_llm_backlog`, and `health_summary`
- `run_metadata.json` also carries provenance fields such as `faultlens_version` and `git_commit` when available

If an LLM request fails with a provider response body, FaultLens persists that raw body into `llm_raw_responses/` for later manual audit.

### Key output files

- `analysis_report.md`: top-level delivery report, including case distribution, root-cause distribution, health summary, input warnings, LLM quality stats, and current job backlog
- `hierarchical_root_cause_report.md`: three-layer cause and capability aggregation report
- `case_analysis.jsonl`: machine-readable per-case final results
- `cases/<case_id>.md`: detailed per-case analysis for every finalized case
- `run_metadata.json`: run-level metadata for validation and operations
- `run.db`: durable working state and the source of truth for resume/rerender

### Job-state interpretation

`run_metadata.json` and `analysis_report.md` expose `job_status_counts`.

Important states:

- `ingested`: data stored, deterministic stage not yet completed
- `llm_pending`: deterministic stage finished and the case is waiting for LLM work
- `llm_running`: the case is currently leased by an LLM worker
- `llm_failed_retryable`: LLM failed in a retryable way and is waiting for the next retry window
- `llm_failed_terminal`: LLM failed and will not be retried again
- `finalized`: final result has been written

`pending_llm_backlog` is the operational number to watch. It is the sum of:

- `llm_pending`
- `llm_running`
- `llm_failed_retryable`

If backlog is non-zero, the run still has unfinished or retry-waiting LLM work even if deterministic fallback results already exist.

`health_summary` is the higher-level operator view:
- `run_health`: `healthy`, `warning`, or `blocked`
- `ready_for_delivery`: whether export state is deliverable without known blockers
- `finalized_ratio`: finalized job coverage over total cases
- `blocking_issues` / `warnings`: short human-readable summaries

## Scaling and stability

The current pipeline is designed for larger local runs:

- joined cases, deterministic results, LLM attempts, and final results are persisted in SQLite
- resume continues from persisted task state instead of recomputing completion by scanning old outputs
- retryable LLM failures keep evidence and fallback results, then retry later within the configured retry budget
- retryable jobs are capped by `llm_max_retries` and do not loop forever across resumed runs
- tests cover a 1000-case run path with durable state handling

This is the current intended operating model for long-running analysis batches.

## Language support

V1 focuses on:
- Python
- C++
- Java
- Go

Current machine-dependent behavior:
- Python and C++ execution run when toolchains are available
- Java and Go gracefully degrade when toolchains or runtime support are unavailable
- runtime execution requires macOS `sandbox-exec`; when unavailable, execution is disabled and FaultLens degrades to static analysis for safety
- execution uses a temporary workspace, sanitized environment, timeouts, truncated output capture, and cleanup

## Known boundaries

FaultLens is aimed at durable local batch analysis, but the following boundaries still matter:

- runtime execution quality depends on host toolchains and sandbox availability
- LLM attribution quality still depends on upstream model behavior and endpoint stability
- non-retryable LLM failures fall back to deterministic-only finalization
- input resume validation is intentionally strict; modified source files require a fresh run

## Verification

The current repository state has fresh full-test verification on `main`:

- `pytest -q`
- latest verified result: `144 passed`

## Exit Codes

CLI exit codes are intentionally stable for automation:

- `0`: success
- `2`: CLI usage / argument parsing error
- `3`: user/configuration error
- `4`: output integrity check failed
- `5`: required input file missing

## Tests

```bash
pytest -q
```
