# Execution Plan — CourseForge Audit Fixes

Based on `docs/PROJECT_AUDIT.md` (2026-03-15).

---

## Wave 1 — Critical Fixes (P0/P1) 🔴

- [x] FIX-001: **`total_words` UnboundLocalError in orchestrator** — `orchestrator.py:445`. Added recalculation before final log.
- [x] FIX-002: **Search provider httpx clients never closed** — `tasks.py`. Added `search.aclose()` and `translator.aclose()` in finally block.
- [x] FIX-003: **SSRF: blocking DNS in async context** — `scraper.py`. Made `_is_safe_url` async with `asyncio.to_thread()` for DNS resolution.
- [x] FIX-004: **`list_jobs` exposes all users' data** — `jobs.py`. Added `telegram_id` query param filter.
- [x] FIX-005: **`cancel_job` doesn't refund credit** — `jobs.py`. Atomically returns credit when cancelling PENDING job.
- [x] FIX-006: **Race condition in user creation** — `user_service.py`. Uses `INSERT ... ON CONFLICT DO NOTHING`.
- [x] FIX-007: **`query_expander.py` curly brace crash** — `query_expander.py`. Escapes `{` `}` in user input before `.format()`.

## Wave 2 — Architecture Improvements 🟠

- [x] ARCH-001: **Pipeline timeout enforcement** — `tasks.py`. Wraps `orchestrator.run()` in `asyncio.wait_for(timeout)`.
- [x] ARCH-002: **Consolidate S3 code (DRY)** — Removed duplicated S3 functions from `tasks.py`, now uses `storage.py` with new `ensure_bucket()` and `generate_presigned_url()`.
- [x] ARCH-003: **Bot API client: persistent httpx** — `api_client.py`. Replaced per-request client with persistent `AsyncClient` + `aclose()`.

## Wave 3 — Code Quality & Refactoring 🟡

- [x] REFACT-001: **Inline imports in jobs.py** — Moved `get_settings`, `download_document`, `upload_document`, `quote` to top-level imports.
- [x] REFACT-002: **`set_response` alias** — Added `set_response()` convenience method to `MockLLMProvider`.
- [x] REFACT-003: **Inconsistent logging** — Switched `storage.py` and `retry.py` from stdlib `logging` to `structlog`.
- [x] REFACT-004: **`get_balance` phantom credits** — Now creates user on first balance check, returning real DB state.
- [x] REFACT-005: **`session.py` import-time settings** — Prefixed with `_settings` to clarify it's module-scoped via `lru_cache`.
- [x] REFACT-006: **CORS wildcard + credentials** — Set `allow_credentials=False` when `allow_origins=["*"]`.

## Wave 4 — Dependencies 🔵

- [x] DEPS-001: **Remove unused `playwright`** — Removed from `pyproject.toml` (saves ~150MB in Docker images).
- [x] DEPS-002: **Remove unused `factory-boy`** — Removed from dev dependencies.

---

## 📊 Execution Report

### Statistics
- Total items: 18
- Completed: 18
- Skipped: 0
- New files: 1 (EXECUTION_PLAN.md)
- Modified files: 15
- Deleted files: 0
- Test fixes: 3 (scraper tests updated for async `_is_safe_url`)

### Files Changed
| File | Changes |
|------|---------|
| `backend/app/pipeline/orchestrator.py` | FIX-001: total_words recalculation |
| `backend/app/workers/tasks.py` | FIX-002: resource cleanup, ARCH-001: timeout, ARCH-002: use storage.py |
| `backend/app/pipeline/research/scraper.py` | FIX-003: async DNS resolution |
| `backend/app/api/routes/jobs.py` | FIX-004: filter by telegram_id, FIX-005: credit refund, REFACT-001: imports |
| `backend/app/services/user_service.py` | FIX-006: ON CONFLICT upsert |
| `backend/app/pipeline/research/query_expander.py` | FIX-007: brace escaping |
| `backend/app/services/storage.py` | ARCH-002: consolidated S3 ops, REFACT-003: structlog |
| `bot/app/services/api_client.py` | ARCH-003: persistent httpx client |
| `backend/app/testing.py` | REFACT-002: set_response alias |
| `backend/app/utils/retry.py` | REFACT-003: structlog |
| `backend/app/api/routes/payments.py` | REFACT-004: create user on balance check |
| `backend/app/db/session.py` | REFACT-005: clarified import-time init |
| `backend/app/main.py` | REFACT-006: CORS credentials fix |
| `backend/pyproject.toml` | DEPS-001: -playwright, DEPS-002: -factory-boy |
| `backend/tests/test_pipeline/test_scraper.py` | Updated for async _is_safe_url |

### Test Results
- 346 passed, 1 pre-existing failure (DNS resolution unavailable in sandbox)
- No new failures introduced
- Ruff: no new lint errors (pre-existing B008/F821 unchanged)

### Not Addressed (Deferred)
These items from the audit require larger architectural changes or are lower priority:
- ARCH-004: Service layer extraction (high effort, breaks all routes)
- ARCH-005: Magic numbers for CHAPTER_INTRO/CONCLUSION (cosmetic)
- ARCH-006: API versioning (breaking change)
- ARCH-008: Structured error responses (medium effort)
- SEC-002: SSRF TOCTOU mitigation (needs httpx transport-level changes)
- SEC-004: MD5 signatures (Robokassa API requirement, cannot change)
- TEST-001: Integration tests with real DB (needs testcontainers setup)
- LOG-001/LOG-002: Correlation IDs and metrics (new infrastructure)
- FEAT-001 through FEAT-008: New features (separate sprint)
