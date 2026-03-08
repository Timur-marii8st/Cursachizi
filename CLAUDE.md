# CourseForge — AI Assistant Guide

CourseForge is a production-grade, AI-powered coursework and article generation platform targeting Russian universities. It exposes a Telegram bot as its user interface, backed by a FastAPI service, an arq async task queue, and a four-stage LLM pipeline that researches, writes, verifies, and formats documents to ГОСТ standards.

---

## Table of Contents

1. [Project Layout](#1-project-layout)
2. [Architecture Overview](#2-architecture-overview)
3. [Environment & Configuration](#3-environment--configuration)
4. [Build, Run & Development Commands](#4-build-run--development-commands)
5. [Coding Style & Conventions](#5-coding-style--conventions)
6. [Testing Guidelines](#6-testing-guidelines)
7. [Commit & PR Guidelines](#7-commit--pr-guidelines)
8. [Security Guidelines](#8-security-guidelines)
9. [Key Module Reference](#9-key-module-reference)
10. [AI Senior Engineer Review Protocol](#10-ai-senior-engineer-review-protocol)

---

## 1. Project Layout

```
Cursachizi/
├── backend/                   # FastAPI API + arq worker + pipeline
│   ├── app/
│   │   ├── api/               # Routes, dependency injection, middleware
│   │   │   ├── deps.py        # Rate-limit, auth, LLM/search provider factories
│   │   │   └── routes/        # health, jobs, payments, offer
│   │   ├── db/                # SQLAlchemy async engine, session, base model
│   │   ├── llm/               # LLM abstraction layer
│   │   │   ├── provider.py    # Abstract LLMProvider, LLMMessage, LLMResponse
│   │   │   ├── factory.py     # Creates provider by name
│   │   │   ├── openrouter.py  # OpenRouter (default, vision-capable)
│   │   │   ├── anthropic.py   # Direct Anthropic client
│   │   │   └── openai_provider.py
│   │   ├── models/            # SQLAlchemy ORM models (User, Job, Payment)
│   │   ├── pipeline/          # Four-stage generation pipeline
│   │   │   ├── orchestrator.py
│   │   │   ├── research/      # query expansion → search → scrape → rank
│   │   │   ├── writer/        # outline → section writer → evaluator → humanizer
│   │   │   ├── verifier/      # claim extractor → fact checker → correction applier
│   │   │   └── formatter/     # ГОСТ docx generator → visual matcher
│   │   ├── services/          # Robokassa payment gateway
│   │   ├── workers/           # arq task definitions (execute_pipeline)
│   │   ├── config.py          # Pydantic BaseSettings (all env vars)
│   │   ├── main.py            # FastAPI app factory, lifespan, CORS, docs
│   │   └── testing.py         # MockLLMProvider, MockSearchProvider
│   ├── alembic/               # Database migrations (4 revisions)
│   ├── tests/                 # 27 pytest files mirroring app structure
│   └── pyproject.toml         # Backend package + dev deps
├── bot/                       # Telegram bot (aiogram 3)
│   ├── app/
│   │   ├── handlers/          # start, generate (FSM), status, payment
│   │   ├── keyboards/         # Inline & reply keyboards
│   │   ├── services/
│   │   │   └── api_client.py  # HTTP client wrapping backend endpoints
│   │   ├── config.py          # Bot settings (token, API URL, Redis)
│   │   └── main.py            # Bot + dispatcher factory, router registration
│   ├── tests/                 # api_client + keyboards tests
│   └── pyproject.toml
├── shared/                    # Pydantic schemas shared by backend + bot
│   └── schemas/
│       ├── job.py             # WorkType, JobStatus, JobStage, JobCreate/Response
│       ├── payment.py         # CreditPackage, PaymentCreate/Response, BalanceResponse
│       ├── pipeline.py        # Source, ResearchResult, Outline, SectionContent, etc.
│       └── template.py        # GostTemplate, FontConfig, MarginConfig, HeadingStyle
├── infra/
│   ├── docker-compose.yml     # postgres, redis, minio, backend, worker, nginx, bot
│   ├── Dockerfile.backend     # python:3.12-slim + libreoffice-writer + uvicorn
│   ├── Dockerfile.worker      # same system deps, runs arq
│   ├── Dockerfile.bot         # minimal, runs bot.app.main
│   └── nginx/default.conf     # Reverse proxy to backend:8000
├── .github/workflows/ci.yml   # Lint → type-check → test on push/PR to main
├── .env.example               # All required env vars with defaults
├── pyproject.toml             # Root: ruff + mypy + pytest config
└── CLAUDE.md                  # This file
```

---

## 2. Architecture Overview

```
Telegram User
     │
     ▼
[Telegram Bot] ──httpx──▶ [FastAPI Backend :8000]
                                    │
                           ┌────────┴────────┐
                           │                 │
                       [Postgres]         [arq Worker]
                                              │
                                    [Pipeline Orchestrator]
                                    ┌─────┬──────┬──────┐
                                 Research Writer Verify Format
                                    │                    │
                              [Tavily/Serper]       [MinIO / S3]
                              [OpenRouter LLM]
                              [Anthropic/OpenAI]
```

**Data Flow for a Job:**

1. Bot collects topic/discipline/page count via FSM → calls `POST /jobs`.
2. API validates (rate limit, API key, credits) → creates `Job` row → enqueues arq task.
3. Worker runs `PipelineOrchestrator.run()`:
   - **Research**: expands queries → searches web → scrapes → ranks sources.
   - **Writer**: generates outline → writes each chapter section → evaluates quality → optional humanization.
   - **Verifier**: extracts claims → fact-checks against sources → applies corrections.
   - **Formatter**: generates `.docx` → visual-matches against reference template (iterative).
4. Worker uploads `.docx` to MinIO → updates `Job.status = completed` + `document_s3_key`.
5. Bot polls `GET /jobs/{id}` → sends document to user on completion.

**Key architectural decisions:**
- LLM providers and search providers are swappable via factory pattern (`deps.py`). Fallback chain: OpenRouter → Anthropic → OpenAI (LLM); Tavily → Serper (search).
- Default LLM model: `google/gemini-2.5-flash` via OpenRouter.
- All database access is async (asyncpg + SQLAlchemy asyncio). Pool: 10 + 20 overflow.
- Pipeline stages are independently testable — each has its own module and test file.
- ГОСТ compliance is enforced at the formatter level (ГОСТ 7.32-2017 document structure, ГОСТ 7.1-2003 bibliography).

---

## 3. Environment & Configuration

Copy `.env.example` → `.env` and fill in secrets. Never commit `.env`.

Key variable groups:

| Group | Variables | Notes |
|---|---|---|
| App | `APP_ENV`, `DEBUG`, `LOG_LEVEL` | `production` disables Swagger docs, enforces CORS |
| Database | `DATABASE_URL` | Async PostgreSQL on port 5433 |
| Redis | `REDIS_URL` | Task queue + rate-limit state |
| LLM | `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | At least one required |
| Search | `TAVILY_API_KEY`, `SERPER_API_KEY` | At least one required |
| Storage | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` | MinIO-compatible |
| Bot | `TELEGRAM_BOT_TOKEN`, `WEBHOOK_URL`, `INTERNAL_API_KEY` | `INTERNAL_API_KEY` guards internal routes |
| Pipeline | `MAX_SEARCH_SOURCES`, `MAX_TOKENS_PER_SECTION`, `VISUAL_MATCHING_ITERATIONS` | Tuning knobs |
| Payments | `ROBOKASSA_MERCHANT_LOGIN`, `ROBOKASSA_PASSWORD1/2` | Russian payment gateway |

`INTERNAL_API_KEY` is required in production (`is_production` check in `config.py`). Always pass it as `X-API-Key` header when calling backend from the bot.

---

## 4. Build, Run & Development Commands

### Local Development (recommended)

```bash
# Install all packages in editable mode
pip install -e ./shared -e "./backend[dev]" -e "./bot[dev]"

# Start external services (Postgres, Redis, MinIO) via Docker
docker compose -f infra/docker-compose.yml up postgres redis minio -d

# Run database migrations
alembic -c backend/alembic.ini upgrade head

# Start API (auto-reload)
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

# Start arq worker (separate terminal)
python -m arq backend.app.workers.tasks.WorkerSettings

# Start Telegram bot (separate terminal)
python -m bot.app.main
```

### Full Stack via Docker

```bash
docker compose -f infra/docker-compose.yml up --build
```

### Quality Checks (run before every commit)

```bash
ruff check .                          # Lint + import sort
mypy backend bot shared               # Strict type checking
pytest                                # Full test suite
pytest -m "not slow"                  # Skip slow tests
pytest -m integration                 # Only integration tests
pytest --tb=short -q                  # CI-style quiet output
pytest --cov=backend --cov=bot        # With coverage
```

---

## 5. Coding Style & Conventions

- **Python version**: 3.11+ syntax; target is 3.12 for type checking.
- **Indentation**: 4 spaces. Line length: 100 chars (enforced by Ruff).
- **Type hints**: Required on all public function signatures and class attributes.
- **Naming**:
  - `snake_case` for modules, functions, variables
  - `PascalCase` for classes and Pydantic models
  - `UPPER_SNAKE_CASE` for constants and env variable names
- **Imports**: Ruff manages ordering (stdlib → third-party → local). Never use wildcard imports.
- **Async**: All I/O-bound code must be async. Do not use `time.sleep()` or blocking calls in async contexts.
- **Pydantic v2**: Use `model_validator`, `field_validator`, `model_config` — not v1 patterns.
- **Structured logging**: Use `structlog` — not `print()` or bare `logging`.
- **Error handling**: Raise specific exceptions; catch at boundaries. Do not swallow exceptions silently.
- **DRY**: Before adding a new utility, check `backend/app/testing.py`, `shared/schemas/`, and `api/deps.py` for existing helpers.

---

## 6. Testing Guidelines

- **Framework**: `pytest` + `pytest-asyncio` (`asyncio_mode = auto` — no `@pytest.mark.asyncio` needed).
- **Test paths**: `backend/tests/` and `bot/tests/`.
- **File naming**: `test_*.py`; one file per feature module (e.g., `test_outliner.py`, `test_fact_checker.py`).
- **Fixtures** (in `backend/tests/conftest.py`):
  - `mock_llm`: `MockLLMProvider` — returns predetermined responses, tracks call history.
  - `mock_search`: `MockSearchProvider` — returns sample Russian-language sources.
  - `sample_sources`: List of realistic `Source` objects for pipeline tests.
- **Mocking HTTP**: Use `respx` for mocking httpx calls (bot API client tests).
- **Test factories**: `factory-boy` for ORM model factories.
- **Markers**:
  - `@pytest.mark.integration` — requires external services (DB, Redis, LLM APIs).
  - `@pytest.mark.slow` — long-running tests.
- **Coverage target**: Aim for >80% on new pipeline modules. Every new pipeline component must have a corresponding `test_*.py`.
- **Assertions**: Be specific — assert on exact values, not just truthiness. Include negative cases and edge cases (empty inputs, API errors, malformed LLM responses).

---

## 7. Commit & PR Guidelines

### Commit Messages

Follow Conventional Commits:

```
<type>: <imperative subject, ≤72 chars>

[optional body: what and why, not how]
```

Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `perf`, `ci`.

Examples:
```
feat: add SerperSearchProvider as Tavily fallback
fix: handle empty LLM response in section_writer
test: add fact_checker edge cases for empty claims list
chore: bump anthropic SDK to 0.40.0
```

Each commit should be **atomic**: one logical change + its tests + lint/type fixes.

### Pull Request Requirements

- **Title**: Short, imperative (`Add visual matcher convergence threshold config`).
- **Body must include**:
  - Problem statement and solution summary.
  - Linked issue/task reference.
  - Test evidence: paste `pytest --tb=short -q` output.
  - Lint/type evidence: paste `ruff check .` and `mypy` output.
  - For API changes: request/response examples.
  - For bot changes: screenshot or behavior description.

---

## 8. Security Guidelines

- **Secrets**: Never commit `.env`, API keys, or credentials. Use `.env.example` for documentation.
- **Internal API key**: All bot-to-backend calls must send `X-API-Key: <INTERNAL_API_KEY>`. Guarded by `verify_internal_api_key()` in `deps.py`.
- **Rate limiting**: Redis-backed per IP/API-key rate limiting on `POST /jobs`. Default: 10 requests/hour. Configurable via env.
- **CORS**: In production (`APP_ENV=production`), CORS is disabled (no wildcard). Do not change this.
- **SQL injection**: Use SQLAlchemy ORM/parameterized queries only. Never construct raw SQL strings.
- **Input validation**: Validate at system boundaries (API routes, bot handlers). Trust internal schemas once deserialized.
- **Payments**: Robokassa signature verification is required. Do not skip `ROBOKASSA_PASSWORD2` validation on result callbacks.
- **LLM prompt injection**: Pipeline prompts include user-supplied topic/instructions — treat these as untrusted. Do not concatenate raw user input into system prompts without sanitization.

---

## 9. Key Module Reference

### LLM Provider (`backend/app/llm/`)

```python
# All LLM calls go through the abstract interface:
provider: LLMProvider = get_llm_provider()

response: LLMResponse = await provider.generate(
    messages=[LLMMessage(role="user", content="...")],
    model="google/gemini-2.5-flash",
    max_tokens=4096,
)

# Structured JSON output:
result: dict = await provider.generate_structured(
    messages=[...],
    schema={"type": "object", "properties": {...}},
)
```

**Fallback chain**: OpenRouter (primary) → Anthropic → OpenAI. Vision tasks: OpenRouter only.

### Pipeline Orchestrator (`backend/app/pipeline/orchestrator.py`)

```python
orchestrator = PipelineOrchestrator(
    llm_provider=llm,
    vision_llm_provider=vision_llm,
    search_provider=search,
    settings=settings,
)
result: PipelineResult = await orchestrator.run(
    job=job,
    callback=stage_callback,   # optional progress updates
)
# result.document_bytes — the generated .docx
```

Stages run sequentially: Research → Writer → Verifier → Formatter.

### Shared Schemas (`shared/schemas/`)

- **`JobCreate`**: `topic`, `university`, `discipline`, `page_count` (5–80), `language` (ru/en), `work_type` (coursework/article), `template_id`, `additional_instructions`.
- **`JobResponse`**: Full job with `status`, `stage`, `progress` (0–100), S3 keys, error info, token usage.
- **`Source`**: `url`, `title`, `snippet`, `full_text`, `relevance_score`, `is_academic`, `language`.
- **`Outline`**: `title`, `intro_points`, `chapters` (list of `OutlineChapter`), `conclusion_points`, `keywords`, `abstract_points`.
- **`GostTemplate`**: ГОСТ 7.32-2017 compliant — A4, margins 20/20/30/15 mm, 5 heading styles, Times New Roman 14pt body, ГОСТ 7.1-2003 bibliography.

### Credit Packages (`shared/schemas/payment.py`)

| Package | Credits | Price (RUB) |
|---|---|---|
| starter | 1 | 199 |
| standard | 3 | 549 (~183/ea) |
| pro | 5 | 849 (~170/ea) |
| enterprise | 10 | 1490 (~149/ea) |

New users receive 1 free credit (`credits_remaining = 1` on User creation).

### Database Models (`backend/app/models/`)

- **`User`**: `telegram_id` (unique, indexed), `username`, `credits_remaining`, `total_papers_generated`.
- **`Job`**: `work_type`, `topic`, `university`, `discipline`, `page_count`, `language`, `template_id`; `status` (pending/processing/completed/failed), `stage`, `progress`; `pipeline_data` (JSON), `document_s3_key`, `reference_s3_key`; `error_message`, `retry_count`, `tokens_used`.
- **`Payment`**: `package_id`, `credits`, `amount_rub`, `status` (pending/completed/failed), `robokassa_inv_id`.

### arq Worker (`backend/app/workers/tasks.py`)

Task: `execute_pipeline(ctx, job_id)` — fetches job from DB, runs orchestrator, uploads `.docx` to MinIO, updates job status. Retry logic is handled by arq via `max_tries` config.

---

## 10. AI Senior Engineer Review Protocol

Before writing any code, review the plan thoroughly. **Do NOT start implementation until the review is complete and the direction is approved.**

### Start Mode

First, ask: **Is this a BIG change or a SMALL change?**

- **BIG**: Review all sections; highlight top 3–4 issues per section.
- **SMALL**: One focused question per section; keep it concise.

### For every issue or recommendation, provide:

1. Clear description of the problem.
2. Why it matters (concrete risk or impact).
3. 2–3 options (include "do nothing" if reasonable).
4. For each option: effort, risk, impact, maintenance cost.
5. Opinionated recommendation with rationale.

**Then ask for approval before moving forward.**

### Section 1: Architecture Review

Evaluate: system design and component boundaries, dependency graph and coupling risks, data flow and bottlenecks, scaling characteristics and single points of failure, security boundaries (auth, data access, API limits).

### Section 2: Code Quality Review

Evaluate: project structure and module organization, DRY violations, error handling patterns and missing edge cases, technical debt risks, over- or under-engineered areas.

### Section 3: Test Review

Evaluate: coverage (unit, integration, e2e), quality of assertions, missing edge cases, untested failure scenarios.

### Section 4: Performance Review

Evaluate: N+1 queries or inefficient I/O, memory usage risks, CPU hotspots, caching opportunities, latency and scalability concerns.

### Engineering Principles

- **DRY**: Aggressively flag duplication.
- **Well-tested**: More tests over fewer. Every new pipeline component needs its own test file.
- **Engineered enough**: Not fragile, not over-engineered. No premature abstractions.
- **Correctness first**: Optimize for edge-case correctness over speed of implementation.
- **Explicit over clever**: If it requires a comment to understand, make it explicit instead.

### Workflow Rules

- Do NOT assume priorities or timelines.
- After each section (Architecture → Code → Tests → Performance), pause and ask for feedback.
- Do NOT implement anything until confirmed.
