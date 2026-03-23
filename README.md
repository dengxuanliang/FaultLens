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

If LLM settings are absent or the endpoint is unavailable, FaultLens falls back to deterministic-only attribution and still writes reports.

## Output

A normal analysis run writes:
- `analysis_report.md`
- `case_analysis.jsonl`
- `summary.json`
- `cases/<case_id>.md`
- `exemplars/*.md`

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
