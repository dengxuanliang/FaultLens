# FaultLens Scalable Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade FaultLens from a transient streaming pipeline to a persistent SQLite-backed run store so 2000+ case runs can resume safely, preserve LLM audit trails, and rebuild outputs from durable state.

**Architecture:** Keep the current CLI and deterministic/LLM analyzers, but replace the temporary join/checkpoint flow with a durable `run.db` state machine. The new flow ingests inputs once into persistent tables, records deterministic and LLM stage results separately, then renders reports from `final_results` so resume and rerender are independent of source JSONL files.

**Tech Stack:** Python 3 standard library, SQLite, pytest, existing FaultLens CLI/reporting modules

---

## File Structure

### New Files

- `src/faultlens/scale/schema.py`
  Initializes `run.db`, schema version metadata, and table/index DDL.
- `src/faultlens/scale/run_store.py`
  Owns database reads/writes, job state transitions, manifests, leases, and final result export queries.
- `tests/test_run_store.py`
  Covers schema creation, manifests, job state transitions, lease recovery, and resume safety checks.

### Modified Files

- `src/faultlens/scale/checkpointing.py`
  Either becomes a compatibility wrapper over `RunStore` or is trimmed to avoid dual persistence logic.
- `src/faultlens/normalize/joiner.py`
  Reworked from transient iterator join to persistent ingest snapshot builder plus database-backed case iteration.
- `src/faultlens/orchestrator.py`
  Split into ingest, deterministic, LLM, and finalize stages backed by `run.db`.
- `src/faultlens/llm/client.py`
  Exposes enough request/response metadata for per-attempt audit writes without breaking existing parsing behavior.
- `src/faultlens/llm/prompting.py`
  Adds a stable prompt contract version string for resume safety.
- `src/faultlens/config.py`
  Adds run-store related settings if needed for lease duration and schema version defaults.
- `src/faultlens/reporting/render.py`
  Reads run metadata/audit statistics from durable state and keeps the current Markdown output contract.
- `src/faultlens/cli.py`
  Keeps the `analyze` UX stable while pointing execution at the staged orchestration flow.
- `README.md`
  Documents `run.db`, manifests, resume safety, and audit artifacts.

### Existing Tests To Extend

- `tests/test_ingest.py`
- `tests/test_scaling.py`
- `tests/test_end_to_end.py`
- `tests/test_llm_client.py`
- `tests/test_cli.py`

## Task 1: Create Durable Run Store Foundations

**Files:**
- Create: `src/faultlens/scale/schema.py`
- Create: `src/faultlens/scale/run_store.py`
- Test: `tests/test_run_store.py`

- [ ] **Step 1: Write the failing schema bootstrap tests**

```python
def test_run_store_initializes_required_tables(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        tables = store.list_tables()
    finally:
        store.close()
    assert {"input_files", "ingest_events", "joined_cases", "analysis_jobs", "deterministic_results", "llm_attempts", "final_results"} <= tables


def test_run_store_persists_run_metadata_versions(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        store.initialize_run_metadata(
            analysis_version="det-v1",
            prompt_version="prompt-v1",
            settings={"llm_max_workers": 1},
        )
        row = store.load_run_metadata()
    finally:
        store.close()
    assert row["analysis_version"] == "det-v1"
    assert row["prompt_version"] == "prompt-v1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_store.py -k "initializes_required_tables or persists_run_metadata_versions" -v`
Expected: FAIL with import errors or missing `RunStore`

- [ ] **Step 3: Implement schema and store bootstrap**

```python
SCHEMA_VERSION = 1


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS run_metadata (...);
        CREATE TABLE IF NOT EXISTS input_files (...);
        CREATE TABLE IF NOT EXISTS ingest_events (...);
        CREATE TABLE IF NOT EXISTS joined_cases (...);
        CREATE TABLE IF NOT EXISTS analysis_jobs (...);
        CREATE TABLE IF NOT EXISTS deterministic_results (...);
        CREATE TABLE IF NOT EXISTS llm_attempts (...);
        CREATE TABLE IF NOT EXISTS final_results (...);
        """
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_store.py -k "initializes_required_tables or persists_run_metadata_versions" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/faultlens/scale/schema.py src/faultlens/scale/run_store.py tests/test_run_store.py
git commit -m "feat: add durable run store foundation"
```

## Task 2: Persist Input Snapshot And Resume Safety

**Files:**
- Modify: `src/faultlens/normalize/joiner.py`
- Modify: `src/faultlens/orchestrator.py`
- Modify: `src/faultlens/llm/prompting.py`
- Test: `tests/test_ingest.py`
- Test: `tests/test_scaling.py`
- Test: `tests/test_run_store.py`

- [ ] **Step 1: Write failing tests for ingest snapshot and input fingerprint validation**

```python
def test_build_ingest_snapshot_persists_joined_cases_and_jobs(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    result = run_analysis(input_paths=[inference_path, results_path], settings=settings, output_dir=output_dir)
    store = RunStore(output_dir / "run.db").open()
    try:
        assert store.count_joined_cases() == 4
        assert store.count_jobs(status="ingested") == 4
    finally:
        store.close()


def test_resume_rejects_changed_input_manifest(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        store.record_input_file(path="a.jsonl", sha256="old", size_bytes=10, mtime_epoch=1, detected_role="inference", declared_order=0, sample_record_count=1)
        with pytest.raises(ValueError, match="input manifest mismatch"):
            store.assert_resume_safe(current_inputs=[{"path": "a.jsonl", "sha256": "new", "size_bytes": 10, "mtime_epoch": 1}])
    finally:
        store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py tests/test_scaling.py tests/test_run_store.py -k "ingest_snapshot or resume_rejects_changed_input_manifest" -v`
Expected: FAIL because snapshot persistence and resume checks do not exist yet

- [ ] **Step 3: Implement persistent ingest snapshot**

```python
def build_ingest_snapshot(store: RunStore, inference_path: Path, results_path: Path) -> None:
    store.begin_ingest()
    # stream both files once, record input fingerprints/events, persist joined_cases and analysis_jobs
    store.finish_ingest()
```

- [ ] **Step 4: Add prompt/version snapshot support**

```python
PROMPT_VERSION = "attribution-v2"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py tests/test_scaling.py tests/test_run_store.py -k "ingest_snapshot or resume_rejects_changed_input_manifest" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/faultlens/normalize/joiner.py src/faultlens/orchestrator.py src/faultlens/llm/prompting.py tests/test_ingest.py tests/test_scaling.py tests/test_run_store.py
git commit -m "feat: persist ingest snapshot and resume safety checks"
```

## Task 3: Persist Deterministic Stage Results In The Run Store

**Files:**
- Modify: `src/faultlens/orchestrator.py`
- Modify: `src/faultlens/scale/run_store.py`
- Test: `tests/test_scaling.py`
- Test: `tests/test_end_to_end.py`

- [ ] **Step 1: Write failing tests for deterministic stage persistence**

```python
def test_deterministic_stage_writes_results_and_marks_llm_pending(tmp_path: Path) -> None:
    run_analysis(input_paths=[inference_path, results_path], settings=settings, output_dir=output_dir)
    store = RunStore(output_dir / "run.db").open()
    try:
        row = store.get_job("2")
        assert row["job_status"] == "llm_pending"
        deterministic = store.get_deterministic_result("2")
        assert deterministic["case_status"] == "attributable_failure"
    finally:
        store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scaling.py tests/test_end_to_end.py -k "deterministic_stage_writes_results" -v`
Expected: FAIL because deterministic outputs are not stored in `run.db`

- [ ] **Step 3: Implement deterministic stage writes**

```python
for case in store.iter_jobs(status="ingested"):
    analyzed = analyze_case_deterministically(...)
    store.save_deterministic_result(case_id, analyzed, findings)
    store.transition_job(case_id, "llm_pending" if eligible_for_llm else "deterministic_done")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scaling.py tests/test_end_to_end.py -k "deterministic_stage_writes_results" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/faultlens/orchestrator.py src/faultlens/scale/run_store.py tests/test_scaling.py tests/test_end_to_end.py
git commit -m "feat: persist deterministic stage results"
```

## Task 4: Add LLM Attempt Audit Trail And Recoverable Queueing

**Files:**
- Modify: `src/faultlens/orchestrator.py`
- Modify: `src/faultlens/scale/run_store.py`
- Modify: `src/faultlens/llm/client.py`
- Test: `tests/test_llm_client.py`
- Test: `tests/test_scaling.py`
- Test: `tests/test_end_to_end.py`

- [ ] **Step 1: Write failing tests for attempt audit and lease recovery**

```python
def test_llm_attempts_store_request_and_response_payloads(tmp_path: Path) -> None:
    run_analysis(...)
    store = RunStore(output_dir / "run.db").open()
    try:
        attempt = store.list_llm_attempts("2")[0]
        assert "\"role\": \"system\"" in attempt["request_messages_json"]
        assert "logic mismatch" in attempt["response_text"]
        assert attempt["parse_mode"] in {"strict_json", "adaptive_parse", "request_error"}
    finally:
        store.close()


def test_resume_requeues_expired_llm_running_jobs(tmp_path: Path) -> None:
    store.force_job_state(case_id="2", job_status="llm_running", worker_lease_until="2000-01-01T00:00:00Z")
    store.requeue_expired_leases(now="2026-04-03T00:00:00Z")
    assert store.get_job("2")["job_status"] == "llm_pending"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_client.py tests/test_scaling.py tests/test_end_to_end.py -k "llm_attempts_store_request_and_response_payloads or resume_requeues_expired_llm_running_jobs" -v`
Expected: FAIL because attempts and leases are not persisted this way yet

- [ ] **Step 3: Implement LLM queue + audit persistence**

```python
lease = store.claim_llm_job(now=utcnow(), lease_seconds=settings.llm_lease_seconds)
messages = build_attribution_messages(case)
llm_result = client.complete_json(messages)
store.record_llm_attempt(case_id, attempt_index, messages, client.last_completion_info, warning)
store.select_llm_attempt(case_id, attempt_id)
```

- [ ] **Step 4: Implement retryable vs terminal transitions**

```python
if retryable:
    store.fail_llm_job_retryable(case_id, next_retry_at, last_error)
else:
    store.fail_llm_job_terminal(case_id, last_error)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_llm_client.py tests/test_scaling.py tests/test_end_to_end.py -k "llm_attempts_store_request_and_response_payloads or resume_requeues_expired_llm_running_jobs" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/faultlens/orchestrator.py src/faultlens/scale/run_store.py src/faultlens/llm/client.py tests/test_llm_client.py tests/test_scaling.py tests/test_end_to_end.py
git commit -m "feat: add recoverable llm queue and audit trail"
```

## Task 5: Finalize Outputs From Durable State

**Files:**
- Modify: `src/faultlens/orchestrator.py`
- Modify: `src/faultlens/reporting/render.py`
- Modify: `src/faultlens/scale/run_store.py`
- Modify: `README.md`
- Test: `tests/test_end_to_end.py`
- Test: `tests/test_reporting.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for final-results export and rerender idempotence**

```python
def test_finalize_exports_case_analysis_from_final_results(tmp_path: Path) -> None:
    run_analysis(...)
    rows = [json.loads(line) for line in (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    store = RunStore(output_dir / "run.db").open()
    try:
        assert len(rows) == store.count_final_results()
    finally:
        store.close()


def test_finalize_can_rerender_without_reprocessing_inputs(tmp_path: Path) -> None:
    run_analysis(...)
    first_report = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    finalize_outputs(output_dir=output_dir, settings=settings, rerender_only=True)
    second_report = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert second_report == first_report
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_end_to_end.py tests/test_reporting.py tests/test_cli.py -k "finalize_exports_case_analysis_from_final_results or finalize_can_rerender_without_reprocessing_inputs" -v`
Expected: FAIL because outputs are still emitted from the transient in-memory path

- [ ] **Step 3: Implement durable finalize flow**

```python
def finalize_outputs(store: RunStore, output_dir: Path, settings: Settings) -> None:
    export_case_analysis_jsonl(store, output_dir / "case_analysis.jsonl")
    summary = build_summary_from_store(store)
    write_reports(summary, store, output_dir)
```

- [ ] **Step 4: Update CLI/docs and preserve existing UX**

```text
`faultlens analyze --input a.jsonl b.jsonl --output-dir out --resume`
still works, but now writes `run.db`, `input_manifest.json`, and durable LLM attempt history.
```

- [ ] **Step 5: Run targeted tests**

Run: `pytest tests/test_end_to_end.py tests/test_reporting.py tests/test_cli.py -k "finalize_exports_case_analysis_from_final_results or finalize_can_rerender_without_reprocessing_inputs" -v`
Expected: PASS

- [ ] **Step 6: Run full regression**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/faultlens/orchestrator.py src/faultlens/reporting/render.py src/faultlens/scale/run_store.py README.md tests/test_end_to_end.py tests/test_reporting.py tests/test_cli.py
git commit -m "feat: finalize reports from durable run state"
```

## Task 6: Demo Verification On Larger Fixtures

**Files:**
- Modify: `tests/test_scaling.py`
- Optional Create: `demo/large_fixture_builder.py` if the workspace still wants a local helper outside gitignore scope

- [ ] **Step 1: Expand the scaling fixture tests**

```python
def test_cli_handles_2000_case_resume_flow(tmp_path: Path) -> None:
    inference_path, results_path = build_large_fixture(tmp_path, count=2000)
    exit_code = main([...])
    assert exit_code == 0
```

- [ ] **Step 2: Run the scaling-focused tests**

Run: `pytest tests/test_scaling.py -v`
Expected: PASS

- [ ] **Step 3: Run a local manual verification command**

Run: `PYTHONPATH=src python3 -m faultlens.cli analyze --input <inference.jsonl> <results.jsonl> --output-dir <out> --llm-max-workers 1 --resume`
Expected: command completes and output directory contains `run.db`, manifests, reports, and `llm_raw_responses/`

- [ ] **Step 4: Commit**

```bash
git add tests/test_scaling.py
git commit -m "test: cover large durable ingestion flow"
```
