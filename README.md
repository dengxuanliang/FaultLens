# FaultLens

FaultLens is a deterministic-first CLI agent for paired code-evaluation JSONL analysis.

## What it does

- detects which input file is inference-side and which is results-side
- joins records on `inference.id == results.task_id`
- finds failed cases
- extracts generated code from `completion`
- runs deterministic analysis first:
  - language inference
  - syntax checks
  - compile / test execution when supported and sandboxed
  - harness/signature alignment checks
  - canonical/reference diff summaries
- optionally calls an LLM for higher-level attribution
- writes batch + single-case markdown reports plus structured JSON outputs

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

## Quickstart

### Run directly from source

```bash
PYTHONPATH=src python3 -m faultlens.cli analyze \
  --input path/to/file-a.jsonl path/to/file-b.jsonl \
  --output-dir ./outputs
```

### Optional LLM configuration

Create a project-local `.env` file (auto-loaded from the current working directory):

```bash
cp .env.example .env
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
- `FAULTLENS_ENABLE_CHECKPOINTS`

CLI flags:
- `--llm-max-workers`
- `--llm-max-retries`
- `--llm-retry-backoff-seconds`
- `--llm-retry-on-5xx` / `--no-llm-retry-on-5xx`
- `--resume`
- `--disable-checkpoints`

If LLM settings are absent or the endpoint is unavailable, FaultLens falls back to deterministic-only attribution and still writes reports.

## Output

A normal analysis run writes:
- `analysis_report.md`
- `case_analysis.jsonl`
- `summary.json`
- `run_metadata.json`
- `hierarchical_root_cause_report.md`
- `cases/<case_id>.md`
- `exemplars/*.md`
- `llm_raw_responses/<case_id>.txt` when an LLM raw reply or error body is available
- `faultlens_checkpoint.sqlite3` when checkpoints are enabled

Structured outputs include:
- `case_analysis.jsonl`: per-case attribution, parse mode, parse reason, raw-response path, raw-response sha256
- `run_metadata.json`: join stats, model summary, LLM warning log, response-quality stats, checkpoint path

If an LLM request fails with a provider response body, FaultLens persists that raw body into `llm_raw_responses/` for later manual audit.

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

## Tests

```bash
pytest -q
```
