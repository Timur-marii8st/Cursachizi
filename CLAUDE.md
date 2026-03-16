# CLAUDE.md — CourseForge

Comprehensive guide for AI assistants working in this repository.

---

## AI Senior Engineer (Plan Mode)

Before writing any code, review the plan thoroughly.
Do NOT start implementation until the review is complete and the direction is approved.

For every issue or recommendation:
- Explain the concrete tradeoffs
- Give an opinionated recommendation
- Ask for input before proceeding

Engineering principles to follow:
- Prefer DRY — aggressively flag duplication
- Well-tested code is mandatory (better too many tests than too few)
- Code should be "engineered enough" — not fragile or hacky, but not over-engineered
- Optimize for correctness and edge cases over speed of implementation
- Prefer explicit solutions over clever ones

### Review Sections

**Architecture Review** — system design and component boundaries, dependency coupling, data flow bottlenecks, scaling/SPOF, security boundaries (auth, data access, API limits).

**Code Quality Review** — project structure, DRY violations, error handling, technical debt, over/under-engineering.

**Test Review** — coverage (unit, integration, e2e), assertion quality, missing edge cases, failure scenarios.

**Performance Review** — N+1 queries, memory risks, CPU hotspots, caching opportunities, latency concerns.

For each issue found: description → why it matters → 2–3 options with effort/risk/impact/maintenance cost → recommendation. Then ask for approval.

### Workflow Rules

- Do NOT assume priorities or timelines
- After each section (Architecture → Code → Tests → Performance), pause and ask for feedback
- Do NOT implement anything until confirmed

### Start Mode

Before starting, ask: **Is this a BIG change or a SMALL change?**

- **BIG**: Review all sections step-by-step; highlight top 3–4 issues per section.
- **SMALL**: Ask one focused question per section; keep the review concise.

### Output Style

Structured and concise. Opinionated recommendations, not neutral summaries. Focus on real risks and tradeoffs. Think and act like a Staff/Senior Engineer reviewing a production system.

---

## Project Overview

**CourseForge** is an AI-powered academic paper generation platform targeting Russian universities. It accepts a coursework topic + parameters via a Telegram bot, runs a 6-stage LLM pipeline (research → outline → write → verify → format → humanize), and delivers a GOST-compliant `.docx` file.

**Stack at a glance:**
- FastAPI backend + arq async task queue
- PostgreSQL (asyncpg) + Redis
- Multiple LLM providers (Anthropic, OpenAI, OpenRouter)
- Telegram frontend (aiogram v3)
- MinIO/S3 for document storage
- Robokassa payment gateway

---

## Repository Layout

```
/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py              # Auth + rate-limit FastAPI dependencies
│   │   │   └── routes/
│   │   │       ├── jobs.py          # Job CRUD, download, reference upload
│   │   │       ├── payments.py      # Credits, packages, Robokassa webhook
│   │   │       ├── health.py        # /health endpoint
│   │   │       └── offer.py         # Public offer page
│   │   ├── db/
│   │   │   ├── base.py              # SQLAlchemy declarative Base
│   │   │   └── session.py           # Async engine + session factory
│   │   ├── llm/
│   │   │   ├── provider.py          # Abstract LLMProvider interface
│   │   │   ├── factory.py           # create_llm_provider() factory
│   │   │   ├── anthropic.py         # Anthropic Claude adapter
│   │   │   ├── openai_provider.py   # OpenAI adapter
│   │   │   └── openrouter.py        # OpenRouter adapter (supports vision)
│   │   ├── models/
│   │   │   ├── job.py               # Job ORM model
│   │   │   ├── user.py              # User ORM model
│   │   │   └── payment.py           # Payment ORM model
│   │   ├── pipeline/
│   │   │   ├── orchestrator.py      # 6-stage pipeline orchestration
│   │   │   ├── research/            # Query expansion, scraping, ranking
│   │   │   ├── writer/              # Outline + section writing + citation fixing
│   │   │   ├── verifier/            # Fact extraction + checking + correction
│   │   │   └── formatter/           # .docx generation, GOST references, visual matching
│   │   ├── services/
│   │   │   ├── storage.py           # S3/MinIO client
│   │   │   └── robokassa.py         # Payment gateway client
│   │   ├── workers/
│   │   │   └── tasks.py             # arq WorkerSettings + run_pipeline task
│   │   ├── utils/
│   │   │   └── retry.py             # Async retry decorator
│   │   ├── config.py                # Pydantic BaseSettings (all env vars)
│   │   ├── main.py                  # FastAPI app factory + lifespan hooks
│   │   └── testing.py               # MockLLMProvider, MockSearchProvider
│   ├── alembic/                     # DB migrations
│   └── tests/                       # pytest suite (mirrors app/ structure)
├── bot/
│   ├── app/
│   │   ├── handlers/
│   │   │   ├── start.py             # /start command
│   │   │   ├── generate.py          # Job creation FSM
│   │   │   ├── status.py            # Job status polling
│   │   │   └── payment.py           # Credit purchase flow
│   │   ├── keyboards/               # Inline + reply keyboard builders
│   │   ├── services/
│   │   │   └── api_client.py        # Async httpx wrapper for backend API
│   │   ├── config.py                # BotSettings (token, API URL, Redis URL)
│   │   └── main.py                  # aiogram app setup + router registration
│   └── tests/
│       ├── test_api_client.py
│       └── test_keyboards.py
├── shared/
│   └── schemas/
│       ├── job.py                   # WorkType, JobStatus, JobStage, JobCreate, JobResponse
│       ├── pipeline.py              # Source, ResearchResult, Outline, SectionContent,
│       │                            #   BibliographyRegistry, FactCheckResult, PipelineConfig
│       ├── payment.py               # PaymentStatus, CreditPackage, CREDIT_PACKAGES
│       └── template.py              # Template-related schemas
├── infra/
│   ├── docker/
│   │   ├── Dockerfile.backend       # python:3.12-slim + libreoffice + poppler
│   │   ├── Dockerfile.worker        # python:3.12-slim + libreoffice + poppler
│   │   └── Dockerfile.bot           # python:3.12-slim (no heavy deps)
│   ├── nginx/
│   │   └── default.conf             # Reverse proxy, X-Forwarded-* headers
│   └── docker-compose.yml           # postgres, redis, minio, backend, worker, bot, nginx
├── docs/                            # Architecture/design docs
├── pyproject.toml                   # Root: ruff, mypy, pytest config
├── .env.example                     # All required env vars with defaults + comments
└── .github/workflows/ci.yml         # CI: ruff → mypy → pytest
```

---

## Development Workflows

### Local Setup

```bash
# Install all packages in editable mode (required for pytest path resolution)
pip install -e ./shared -e ./backend[dev] -e ./bot[dev]

# Copy and configure environment
cp .env.example .env
# Fill in required keys: OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN, etc.
```

### Running Services

```bash
# API server (with hot reload)
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

# arq background worker
python -m arq backend.app.workers.tasks.WorkerSettings

# Telegram bot
python -m bot.app.main

# Full stack via Docker (recommended for integration testing)
docker compose -f infra/docker-compose.yml up --build
```

### Quality Gates (run before every commit)

```bash
ruff check .          # Lint + import sort
mypy backend bot shared   # Strict type checking
pytest                # Full test suite
```

CI runs all three in sequence on every push and PR targeting `main`.

---

## Architecture Deep Dive

### Request Lifecycle

```
Telegram User
    │
    ▼
aiogram Bot (bot/app/)
    │  POST /api/jobs  (X-API-Key header)
    ▼
FastAPI (backend/app/api/routes/jobs.py)
    ├─ verify_internal_api_key (deps.py)
    ├─ enforce_job_rate_limit  (deps.py)
    ├─ Deduct 1 credit atomically (SQL UPDATE)
    ├─ INSERT Job (status=PENDING)
    └─ arq_pool.enqueue_job("run_pipeline", job_id)
            │
            ▼
    arq Worker (workers/tasks.py)
            │
            ▼
    Pipeline Orchestrator (pipeline/orchestrator.py)
    Stage 1 → Research   (expand queries → search → scrape → rank sources)
    Stage 2 → Outline    (generate chapter/section structure)
    Stage 3 → Write      (section-by-section content + citations)
    Stage 4 → Verify     (extract claims → fact-check → apply corrections)
    Stage 5 → Format     (build .docx → GOST bibliography → visual matching)
    Stage 6 → Humanize   (optional, translation-based text humanization)
            │
            ▼
    Upload .docx to S3 → mark Job COMPLETED
            │
    Bot polls GET /api/jobs/{id} → notifies user → sends download link
```

### Pipeline Orchestrator (`backend/app/pipeline/orchestrator.py`)

The orchestrator runs stages sequentially, persisting intermediate state into the `Job` JSONB columns (`research_data`, `outline_data`, `fact_check_data`). A `JobProgressCallback` updates `status`, `stage`, `progress_pct`, and `stage_message` between stages.

Stage modules follow a consistent pattern:
```python
class SomeStage:
    def __init__(self, llm: LLMProvider, search: SearchProvider, config: PipelineConfig): ...
    async def run(self, ctx: PipelineContext) -> PipelineContext: ...
```

### LLM Provider Abstraction (`backend/app/llm/`)

All LLM interaction goes through the `LLMProvider` ABC:

```python
class LLMProvider(ABC):
    async def generate(messages, model, system_prompt, temperature, max_tokens) -> LLMResponse
    async def generate_structured(messages, response_schema, ...) -> LLMResponse
```

`factory.py::create_llm_provider(provider, api_key, default_model)` returns the correct implementation.

Default models (configurable via env):
- Writer: `google/gemini-3.1-flash-lite-preview` (via OpenRouter)
- Light tasks: `stepfun/step-3.5-flash` (via OpenRouter)
- Vision (template matching): `google/gemini-3.1-flash-lite-preview` (via OpenRouter)

When adding a new provider: implement `LLMProvider`, register in `factory.py`, add env vars to `config.py` and `.env.example`.

### Database Models (`backend/app/models/`)

| Model | Table | Key Fields |
|-------|-------|------------|
| `User` | users | `telegram_id` (unique), `credits_remaining`, `total_papers_generated` |
| `Job` | jobs | `status`, `stage`, `progress_pct`, pipeline JSONB blobs, `document_s3_key` |
| `Payment` | payments | `package_id`, `credits`, `amount_rub`, `robokassa_inv_id`, `status` |

`Job.pipeline_config`, `Job.research_data`, `Job.outline_data`, `Job.fact_check_data` are JSONB — flexible but unvalidated at the DB level. Always deserialize through the corresponding Pydantic schema.

### Shared Schemas (`shared/schemas/`)

Imported by both `backend` and `bot`. Never put business logic here — schemas only.

Key types:
- `WorkType`: `COURSEWORK | ARTICLE`
- `JobStatus`: `PENDING | RUNNING | COMPLETED | FAILED | CANCELLED`
- `JobStage`: `QUEUED | RESEARCHING | OUTLINING | WRITING | FACT_CHECKING | FORMATTING | FINALIZING`
- `BibliographyRegistry`: deduplicates sources by URL, formats numbered bibliography for LLM prompts, validates citation references.
- `PipelineConfig`: all tunable pipeline parameters (search limits, token caps, timeouts, etc.)

---

## Coding Conventions

### Python Style

- Python 3.11+ minimum; Docker images use 3.12.
- 4-space indentation. Type hints on all public interfaces.
- `snake_case` for modules/functions, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants/env names.
- Line length: 100 characters (ruff enforces this; E501 is ignored for Cyrillic strings).
- Ruff rules active: `E, W, F, I, N, UP, B, SIM, TCH, RUF`. RUF001/003 ignored (Cyrillic unicode).

### Async Patterns

The entire backend is async. Use `async def` + `await` consistently. DB sessions come from `AsyncSession` via dependency injection. Do not mix sync and async DB calls.

```python
# Correct
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db)) -> JobResponse:
    result = await db.execute(select(Job).where(Job.id == job_id))
    ...
```

### Error Handling

- Raise `HTTPException` at the API boundary (routes layer).
- Let pipeline stages raise domain exceptions; the orchestrator catches and records `error_message` on the Job.
- Use the `retry` decorator from `backend/app/utils/retry.py` for transient LLM/network failures.

### Configuration Access

Never import `os.environ` directly. Always use the `Settings` instance from `backend/app/config.py`:

```python
from backend.app.config import settings

api_key = settings.OPENROUTER_API_KEY
```

---

## Testing Guidelines

### Framework

`pytest` + `pytest-asyncio` (`asyncio_mode = auto`). All async tests work without any decorator.

### Test Layout

```
backend/tests/
    conftest.py          # mock_llm, mock_search, sample_sources fixtures
    test_api/            # Route-level tests (jobs, payments, health)
    test_llm/            # Provider factory + OpenRouter tests
    test_pipeline/       # One file per pipeline stage/component
    test_services/       # Robokassa, S3 storage
    test_utils/          # Retry decorator
    test_workers/        # arq task integration
bot/tests/
    test_api_client.py
    test_keyboards.py
```

### Key Fixtures (from `conftest.py`)

- `mock_llm` → `MockLLMProvider` from `backend.app.testing` — returns configurable canned responses
- `mock_search` → `MockSearchProvider` — returns `sample_sources`
- `sample_sources` → list of `Source` objects with Russian-language academic content

### Patterns

```python
# Mock LLM for pipeline unit tests
async def test_research_stage(mock_llm, mock_search, sample_sources):
    mock_llm.set_response('{"expanded_queries": [...]}')
    stage = ResearchStage(llm=mock_llm, search=mock_search, config=PipelineConfig())
    result = await stage.run(initial_context)
    assert len(result.research.sources) > 0

# Mock HTTP for bot API client
async def test_create_job(respx_mock):
    respx_mock.post("/api/jobs").mock(return_value=Response(200, json={...}))
    client = CourseForgeAPIClient(base_url="http://test")
    response = await client.create_job(JobCreate(...))
    assert response.status == JobStatus.PENDING
```

### Running Tests

```bash
pytest                          # All tests
pytest -m "not integration"     # Skip integration tests
pytest -m "not slow"            # Skip slow tests
pytest backend/tests/test_pipeline/ -v   # Specific module
pytest --tb=short -q            # CI-style output
```

---

## Security Notes

### API Authentication

All job/payment endpoints require `X-API-Key: <INTERNAL_API_KEY>` header. The bot sets this automatically. In production, `INTERNAL_API_KEY` must be set (validated at startup).

### Rate Limiting

`enforce_job_rate_limit` in `api/deps.py` uses Redis to count requests per user. Respects `TRUSTED_PROXY_IPS` for `X-Forwarded-For` validation. Default: `10/hour` (configurable via `RATE_LIMIT_PER_USER`).

### Credit Atomicity

Credit deduction uses an atomic SQL `UPDATE ... WHERE credits_remaining > 0 RETURNING id` — no race condition possible.

### File Upload Validation

Reference template uploads in `POST /api/jobs/{job_id}/reference` validate ZIP magic bytes (`PK\x03\x04`) before processing.

### Secrets

- Never commit `.env`. Use `.env.example` as the template.
- `ADMIN_TELEGRAM_IDS` grants unlimited credits to listed user IDs.
- Robokassa webhooks validated via MD5 signature check in `services/robokassa.py`.

---

## Environment Variables Reference

Defined in `backend/app/config.py` (Pydantic `BaseSettings`). See `.env.example` for defaults.

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL DSN with `asyncpg` driver |
| `REDIS_URL` | Yes | Redis DSN for arq queue + rate limiter |
| `INTERNAL_API_KEY` | Prod | Shared secret for bot↔backend auth |
| `OPENROUTER_API_KEY` | Yes | Primary LLM provider API key |
| `ANTHROPIC_API_KEY` | No | Optional Anthropic direct access |
| `OPENAI_API_KEY` | No | Optional OpenAI direct access |
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `TELEGRAM_WEBHOOK_URL` | No | Webhook URL (polling if unset) |
| `API_BASE_URL` | Yes | Backend URL visible to the bot |
| `S3_ENDPOINT_URL` | Yes | MinIO or S3 endpoint |
| `S3_ACCESS_KEY` | Yes | Object storage credentials |
| `S3_SECRET_KEY` | Yes | Object storage credentials |
| `S3_BUCKET_NAME` | Yes | Target bucket name |
| `ROBOKASSA_LOGIN` | No | Payment gateway credentials |
| `ROBOKASSA_PASSWORD1` | No | Robokassa password 1 |
| `ROBOKASSA_PASSWORD2` | No | Robokassa password 2 |
| `ROBOKASSA_TEST_MODE` | No | Enable test payments (default: true) |
| `DEFAULT_LLM_PROVIDER` | No | `openrouter` / `anthropic` / `openai` |
| `DEFAULT_WRITER_MODEL` | No | Model for section writing |
| `DEFAULT_LIGHT_MODEL` | No | Model for lightweight tasks |
| `VISION_MODEL` | No | Model for visual template matching |
| `TAVILY_API_KEY` | No | Tavily web search provider |
| `SERPER_API_KEY` | No | Serper web search provider |
| `ADMIN_TELEGRAM_IDS` | No | Comma-separated IDs with unlimited credits |
| `RATE_LIMIT_PER_USER` | No | e.g. `10/hour` |
| `TRUSTED_PROXY_IPS` | No | Comma-separated IPs for X-Forwarded-For |
| `PIPELINE_TIMEOUT_SECONDS` | No | Max pipeline run time (default: 3600) |
| `FACT_CHECK_MAX_ROUNDS` | No | Verifier iteration limit |
| `VISUAL_MATCH_MAX_ITERATIONS` | No | Visual template matching iteration limit |

---

## Commit & Pull Request Guidelines

- Conventional Commits style: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
- One concern per commit; include tests and lint fixes alongside code changes.
- PR body must include:
  - Problem/solution summary
  - Linked issue or task
  - `pytest`, `ruff`, `mypy` output
  - Request/response snippets or screenshots when API or bot behavior changes

---

## CI Pipeline (`.github/workflows/ci.yml`)

Triggers on push and PRs to `main`.

1. Checkout + Python 3.11 setup
2. `pip install -e ./shared -e ./backend[dev] -e ./bot[dev]`
3. `ruff check .`
4. `mypy backend bot shared`
5. `pytest --tb=short -q`

All three gates must pass. Fix lint and type errors before pushing.

---

## Common Pitfalls

1. **Importing `os.environ` directly** — use `settings` from `config.py` instead.
2. **Sync DB calls in async context** — all DB operations must be `await`ed through `AsyncSession`.
3. **Adding business logic to `shared/schemas/`** — schemas are data contracts only; logic belongs in services or pipeline stages.
4. **Skipping `BibliographyRegistry.validate_citations()`** after writing sections — invalid citation numbers will cause DOCX formatting errors.
5. **Not mocking `MockLLMProvider` responses** — the mock returns empty strings by default; call `mock_llm.set_response(...)` for each test.
6. **Hard-coding model names** — use `settings.DEFAULT_WRITER_MODEL` and related settings so deployments can swap models via env.
7. **Running pipeline integration tests without provider keys** — mark them `@pytest.mark.integration` and use `-m "not integration"` in unit test runs.

# Claude / AI Senior Engineer Prompt (Plan Mode)

Before writing any code, review the plan thoroughly.  
Do NOT start implementation until the review is complete and I approve the direction.

For every issue or recommendation:
- Explain the concrete tradeoffs
- Give an opinionated recommendation
- Ask for my input before proceeding

Engineering principles to follow:
- Prefer DRY — aggressively flag duplication
- Well-tested code is mandatory (better too many tests than too few)
- Code should be “engineered enough” — not fragile or hacky, but not over-engineered
- Optimize for correctness and edge cases over speed of implementation
- Prefer explicit solutions over clever ones

---

## 1. Architecture Review

Evaluate:
- Overall system design and component boundaries
- Dependency graph and coupling risks
- Data flow and potential bottlenecks
- Scaling characteristics and single points of failure
- Security boundaries (auth, data access, API limits)

---

## 2. Code Quality Review

Evaluate:
- Project structure and module organization
- DRY violations
- Error handling patterns and missing edge cases
- Technical debt risks
- Areas that are over-engineered or under-engineered

---

## 3. Test Review

Evaluate:
- Test coverage (unit, integration, e2e)
- Quality of assertions
- Missing edge cases
- Failure scenarios that are not tested

---

## 4. Performance Review

Evaluate:
- N+1 queries or inefficient I/O
- Memory usage risks
- CPU hotspots or heavy code paths
- Caching opportunities
- Latency and scalability concerns

---

## For each issue found:

Provide:
1. Clear description of the problem
2. Why it matters
3. 2–3 options (including “do nothing” if reasonable)
4. For each option:
   - Effort
   - Risk
   - Impact
   - Maintenance cost
5. Your recommended option and why

Then ask for approval before moving forward.

---

## Workflow Rules

- Do NOT assume priorities or timelines
- After each section (Architecture → Code → Tests → Performance), pause and ask for feedback
- Do NOT implement anything until I confirm

---

## Start Mode

Before starting, ask:

**Is this a BIG change or a SMALL change?**

BIG change:
- Review all sections step-by-step
- Highlight the top 3–4 issues per section

SMALL change:
- Ask one focused question per section
- Keep the review concise

---

## Output Style

- Structured and concise
- Opinionated recommendations (not neutral summaries)
- Focus on real risks and tradeoffs
- Think and act like a Staff/Senior Engineer reviewing a production system