# Bootstrap Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove stale operator-facing configuration and harden bootstrap interpreter discovery so Linux clone-to-run setup behaves consistently.

**Architecture:** Keep the existing bootstrap/reporting/business logic intact. Tighten only the delivery shell around the product by correcting `.env.example` and making `scripts/bootstrap.sh` detect Python more robustly while still enforcing Python 3.11+.

**Tech Stack:** Bash, pytest, project docs

---

### Task 1: Harden bootstrap interpreter discovery

**Files:**
- Modify: `scripts/bootstrap.sh`
- Test: `tests/test_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add coverage asserting that `bootstrap.sh` checks `python3.11`, falls back to `python3`, and validates `>=3.11`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bootstrap.py -q`
Expected: FAIL because the script only hardcodes `python3.11`.

- [ ] **Step 3: Write minimal implementation**

Update `bootstrap.sh` to:
- honor explicit `PYTHON_BIN` if set
- otherwise prefer `python3.11`, then `python3`
- validate the chosen interpreter version with a short Python snippet
- keep failure messaging explicit

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bootstrap.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/bootstrap.sh tests/test_bootstrap.py
git commit -m "fix: harden bootstrap interpreter detection"
```

### Task 2: Remove stale checkpoint env setting

**Files:**
- Modify: `.env.example`
- Test: `tests/test_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add coverage asserting `.env.example` no longer mentions `FAULTLENS_ENABLE_CHECKPOINTS`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bootstrap.py -q`
Expected: FAIL because `.env.example` still includes the stale key.

- [ ] **Step 3: Write minimal implementation**

Delete the stale line from `.env.example`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bootstrap.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .env.example tests/test_bootstrap.py
git commit -m "fix: remove stale checkpoint env setting"
```

### Task 3: Final verification

**Files:**
- Verify: `README.md`
- Verify: `scripts/bootstrap.sh`
- Verify: `.env.example`
- Verify: `tests/test_bootstrap.py`

- [ ] **Step 1: Run targeted verification**

Run: `pytest tests/test_bootstrap.py -q`
Expected: PASS

- [ ] **Step 2: Run full verification**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 3: Manually smoke check bootstrap flow**

Run: `./scripts/bootstrap.sh` then `./scripts/run.sh --help`
Expected: bootstrap succeeds and CLI help renders.
