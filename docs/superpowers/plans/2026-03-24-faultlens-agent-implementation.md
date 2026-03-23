# FaultLens Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-usable CLI agent that ingests paired evaluation JSONL files, runs deterministic code-failure analysis first, optionally applies LLM attribution to failed cases, and emits batch + single-case reports.

**Architecture:** Use a standard-library-first Python package with focused modules for role detection/ingestion, normalization/failure gating, deterministic analyzers, isolated runner adapters, optional LLM attribution, and reporting. The orchestrator produces a normalized per-case record, enriches it with deterministic findings and provenance, then aggregates and renders markdown/json outputs.

**Tech Stack:** Python 3.9+, pytest, setuptools console script entrypoint, subprocess-based toolchain runners, dataclasses, pathlib, json, argparse, tempfile, urllib.

---

## File Structure

**Create:**
- `.env.example`
- `README.md`
- `pyproject.toml`
- `src/faultlens/__init__.py`
- `src/faultlens/cli.py`
- `src/faultlens/config.py`
- `src/faultlens/orchestrator.py`
- `src/faultlens/models.py`
- `src/faultlens/env.py`
- `src/faultlens/ingest/jsonl.py`
- `src/faultlens/ingest/resolver.py`
- `src/faultlens/normalize/joiner.py`
- `src/faultlens/normalize/failure_gate.py`
- `src/faultlens/deterministic/analyzers/code_extractor.py`
- `src/faultlens/deterministic/analyzers/language.py`
- `src/faultlens/deterministic/analyzers/diffing.py`
- `src/faultlens/deterministic/analyzers/harness.py`
- `src/faultlens/deterministic/signals.py`
- `src/faultlens/deterministic/pipeline.py`
- `src/faultlens/deterministic/runners/base.py`
- `src/faultlens/deterministic/runners/python_runner.py`
- `src/faultlens/deterministic/runners/cpp_runner.py`
- `src/faultlens/deterministic/runners/java_runner.py`
- `src/faultlens/deterministic/runners/go_runner.py`
- `src/faultlens/deterministic/runners/registry.py`
- `src/faultlens/llm/client.py`
- `src/faultlens/llm/prompting.py`
- `src/faultlens/attribution/engine.py`
- `src/faultlens/reporting/aggregate.py`
- `src/faultlens/reporting/render.py`
- `tests/conftest.py`
- `tests/fixtures/inference_sample.jsonl`
- `tests/fixtures/results_sample.jsonl`
- `tests/fixtures/ambiguous_input_a.jsonl`
- `tests/fixtures/ambiguous_input_b.jsonl`
- `tests/fixtures/broken_inference_sample.jsonl`
- `tests/fixtures/broken_results_sample.jsonl`
- `tests/test_cli.py`
- `tests/test_config.py`
- `tests/test_ingest.py`
- `tests/test_joiner.py`
- `tests/test_failure_gate.py`
- `tests/test_code_extractor.py`
- `tests/test_language.py`
- `tests/test_diffing.py`
- `tests/test_harness.py`
- `tests/test_deterministic_pipeline.py`
- `tests/test_runner_base.py`
- `tests/test_python_runner.py`
- `tests/test_toolchain_runners.py`
- `tests/test_attribution.py`
- `tests/test_reporting.py`
- `tests/test_end_to_end.py`

**Modify:**
- `.gitignore`

---

### Task 1: Bootstrap package, env loading, and shared models

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/faultlens/__init__.py`
- Create: `src/faultlens/config.py`
- Create: `src/faultlens/env.py`
- Create: `src/faultlens/models.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing configuration/model tests**
- [ ] **Step 2: Run `pytest tests/test_config.py -q` and verify failure**
- [ ] **Step 3: Implement minimal package bootstrap, `.env` loading, settings precedence, and core dataclasses/enums**
- [ ] **Step 4: Run `pytest tests/test_config.py -q` and verify pass**
- [ ] **Step 5: Commit with `git commit -m "feat: bootstrap package settings and models"`**

### Task 2: Implement schema-based input detection and JSONL ingestion

**Files:**
- Create: `src/faultlens/ingest/jsonl.py`
- Create: `src/faultlens/ingest/resolver.py`
- Test: `tests/test_ingest.py`
- Fixture: `tests/fixtures/inference_sample.jsonl`
- Fixture: `tests/fixtures/results_sample.jsonl`
- Fixture: `tests/fixtures/ambiguous_input_a.jsonl`
- Fixture: `tests/fixtures/ambiguous_input_b.jsonl`
- Fixture: `tests/fixtures/broken_inference_sample.jsonl`
- Fixture: `tests/fixtures/broken_results_sample.jsonl`

- [ ] **Step 1: Write failing tests for role detection, bad lines, empty lines, and ambiguous-input errors**
- [ ] **Step 2: Run `pytest tests/test_ingest.py -q` and verify failure**
- [ ] **Step 3: Implement JSONL reader, line-number tracking, role detection, and schema-validation warnings**
- [ ] **Step 4: Run `pytest tests/test_ingest.py -q` and verify pass**
- [ ] **Step 5: Commit with `git commit -m "feat: add schema-based input detection"`**

### Task 3: Implement join normalization and explicit failure gate

**Files:**
- Create: `src/faultlens/normalize/joiner.py`
- Create: `src/faultlens/normalize/failure_gate.py`
- Test: `tests/test_joiner.py`
- Test: `tests/test_failure_gate.py`

- [ ] **Step 1: Write failing tests for `1:1`, `1:0`, `0:1`, duplicate-join handling, `case_status` transitions, raw-record preservation, source line numbers, role-detection provenance, derived `metadata.slice_fields`, and metadata-conflict warnings**
- [ ] **Step 2: Run `pytest tests/test_joiner.py tests/test_failure_gate.py -q` and verify failure**
- [ ] **Step 3: Implement deterministic join policies, normalized `CaseRecord`, raw/source provenance fields, metadata conflict warnings, `accepted` vs `pass_metrics` conflict checks, and LLM gating eligibility**
- [ ] **Step 4: Run `pytest tests/test_joiner.py tests/test_failure_gate.py -q` and verify pass**
- [ ] **Step 5: Commit with `git commit -m "feat: add join normalization and failure gate"`**

### Task 4: Implement code extraction, language inference, diffing, and harness alignment analyzers

**Files:**
- Create: `src/faultlens/deterministic/analyzers/code_extractor.py`
- Create: `src/faultlens/deterministic/analyzers/language.py`
- Create: `src/faultlens/deterministic/analyzers/diffing.py`
- Create: `src/faultlens/deterministic/analyzers/harness.py`
- Create: `src/faultlens/deterministic/signals.py`
- Test: `tests/test_code_extractor.py`
- Test: `tests/test_language.py`
- Test: `tests/test_diffing.py`
- Test: `tests/test_harness.py`

- [ ] **Step 1: Write failing tests for fenced/unfenced code extraction, language precedence, parse/syntax checking, explicit signature analysis, canonical diff summaries, and harness/entrypoint alignment**
- [ ] **Step 2: Run `pytest tests/test_code_extractor.py tests/test_language.py tests/test_diffing.py tests/test_harness.py -q` and verify failure**
- [ ] **Step 3: Implement analyzers plus controlled signal vocabulary including `syntax_error`, `signature_mismatch`, `entrypoint_mismatch`, `api_mismatch`, `logic_mismatch`, `metadata_conflict`, and `suspicious_eval_mismatch`; emit `parse_status`, `parse_error_excerpt`, and `signature_check_status`**
- [ ] **Step 4: Run `pytest tests/test_code_extractor.py tests/test_language.py tests/test_diffing.py tests/test_harness.py -q` and verify pass**
- [ ] **Step 5: Commit with `git commit -m "feat: add deterministic analyzers and signal vocabulary"`**

### Task 5: Implement runner safety base and Python execution runner

**Files:**
- Create: `src/faultlens/deterministic/runners/base.py`
- Create: `src/faultlens/deterministic/runners/python_runner.py`
- Test: `tests/test_runner_base.py`
- Test: `tests/test_python_runner.py`

- [ ] **Step 1: Write failing tests for timeout, stdout/stderr truncation, cleanup, sanitized env, workspace-only execution behavior (documented confinement boundary), and Python harness execution**
- [ ] **Step 2: Run `pytest tests/test_runner_base.py tests/test_python_runner.py -q` and verify failure**
- [ ] **Step 3: Implement subprocess safety helper and Python runner with isolated temp-dir execution, sanitized cwd/env, explicit workspace-only confinement checks, and documented V1 sandbox limitations**
- [ ] **Step 4: Run `pytest tests/test_runner_base.py tests/test_python_runner.py -q` and verify pass**
- [ ] **Step 5: Commit with `git commit -m "feat: add safe runner base and python execution"`**

### Task 6: Implement C++ / Java / Go runners with degraded-mode behavior

**Files:**
- Create: `src/faultlens/deterministic/runners/cpp_runner.py`
- Create: `src/faultlens/deterministic/runners/java_runner.py`
- Create: `src/faultlens/deterministic/runners/go_runner.py`
- Create: `src/faultlens/deterministic/runners/registry.py`
- Test: `tests/test_toolchain_runners.py`

- [ ] **Step 1: Write failing tests for registry resolution, toolchain-unavailable degraded mode, C++ happy-path execution, and conditional Java/Go happy-path execution when toolchains are available**
- [ ] **Step 2: Run `pytest tests/test_toolchain_runners.py -q` and verify failure**
- [ ] **Step 3: Implement registry plus C++/Java/Go runners; require graceful degradation when toolchains are unavailable**
- [ ] **Step 4: Run `pytest tests/test_toolchain_runners.py -q` and verify pass**
- [ ] **Step 5: Commit with `git commit -m "feat: add multi-language toolchain runners"`**

### Task 7: Implement deterministic pipeline integration and structured findings

**Files:**
- Create: `src/faultlens/deterministic/pipeline.py`
- Modify: `src/faultlens/models.py`
- Test: `tests/test_deterministic_pipeline.py`

- [ ] **Step 1: Write failing tests for full deterministic findings, signal emission including `suspicious_eval_mismatch`, degraded-mode handling, and exclusion of `join_issue` from root-cause candidates**
- [ ] **Step 2: Run `pytest tests/test_deterministic_pipeline.py -q` and verify failure**
- [ ] **Step 3: Implement deterministic pipeline assembly, provenance fields, candidate root-cause hints, and compile/test finding summaries**
- [ ] **Step 4: Run `pytest tests/test_deterministic_pipeline.py -q` and verify pass**
- [ ] **Step 5: Commit with `git commit -m "feat: add deterministic analysis pipeline"`**

### Task 8: Implement LLM client, prompt contract, and attribution engine

**Files:**
- Create: `src/faultlens/llm/client.py`
- Create: `src/faultlens/llm/prompting.py`
- Create: `src/faultlens/attribution/engine.py`
- Test: `tests/test_attribution.py`

- [ ] **Step 1: Write failing tests for deterministic-only fallback, prompt contract construction, full attribution output contract (`case_status`, `accepted`, `deterministic_findings`, `deterministic_signals`, `llm_signals`, `observable_evidence`, `llm_judgment`, `improvement_hints`, `confidence`, `needs_human_review`, `review_reason`, `evidence_refs`, `final_decision_source`), and taxonomy enforcement for `root_cause` / `secondary_cause` with fallback to `insufficient_evidence`**
- [ ] **Step 2: Run `pytest tests/test_attribution.py -q` and verify failure**
- [ ] **Step 3: Implement standard-library HTTP client, prompt builder, LLM fallback logic, provenance-preserving attribution engine, and review-queue heuristics**
- [ ] **Step 4: Run `pytest tests/test_attribution.py -q` and verify pass**
- [ ] **Step 5: Commit with `git commit -m "feat: add llm attribution engine"`**

### Task 9: Implement aggregation, exemplars, markdown rendering, and CLI orchestration

**Files:**
- Create: `src/faultlens/reporting/aggregate.py`
- Create: `src/faultlens/reporting/render.py`
- Create: `src/faultlens/cli.py`
- Create: `src/faultlens/orchestrator.py`
- Modify: `README.md`
- Test: `tests/test_reporting.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_end_to_end.py`

- [ ] **Step 1: Write failing tests for `case_analysis.jsonl`, `summary.json`, cross-analysis, slice-analysis, review queue, exemplar generation, `analysis_report.md` required sections (Run Summary, Deterministic Analysis Summary, LLM Root Cause Distribution, Cross Analysis, Slice Analysis, Representative Exemplars, Review Queue), and single-case report generation by `--case-id` including required sections for code, language, parse/compile/test results, deterministic signals, root cause, explanation, canonical diff, harness alignment, evidence refs, and debug hints**
- [ ] **Step 2: Run `pytest tests/test_reporting.py tests/test_cli.py tests/test_end_to_end.py -q` and verify failure**
- [ ] **Step 3: Implement aggregators, exemplar selection, markdown/json rendering, CLI entrypoint, and orchestrator flow**
- [ ] **Step 4: Run `pytest tests/test_reporting.py tests/test_cli.py tests/test_end_to_end.py -q` and verify pass**
- [ ] **Step 5: Commit with `git commit -m "feat: add reporting and cli orchestration"`**

### Task 10: Full-suite verification and delivery cleanup

**Files:**
- Modify: any files required by review feedback
- Test: full suite and smoke run

- [ ] **Step 1: Run the full test suite with `pytest -q` and verify pass**
- [ ] **Step 2: Run a smoke analysis with `python3 -m faultlens.cli analyze --input tests/fixtures/inference_sample.jsonl tests/fixtures/results_sample.jsonl --output-dir /tmp/faultlens-smoke` and verify exit 0**
- [ ] **Step 3: Check `/tmp/faultlens-smoke/analysis_report.md`, `/tmp/faultlens-smoke/case_analysis.jsonl`, `/tmp/faultlens-smoke/summary.json`, `/tmp/faultlens-smoke/exemplars/`, and `/tmp/faultlens-smoke/cases/`**
- [ ] **Step 4: Commit final cleanup with `git commit -m "chore: finalize faultlens delivery"`**
