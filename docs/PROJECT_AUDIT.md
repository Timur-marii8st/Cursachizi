# CourseForge — Deep Project Audit

**Date:** 2026-03-15
**Auditor:** Senior Staff Engineer / System Architect
**Scope:** Full codebase review — backend, bot, shared, infrastructure, tests

---

## ФАЗА 0: КАРТА ПРОЕКТА

### Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI (Python 3.12) |
| Task Queue | arq (Redis-backed) |
| Database | PostgreSQL 16 (asyncpg + SQLAlchemy 2.0) |
| Cache/Queue | Redis 7 |
| Object Storage | MinIO (S3-compatible) |
| LLM Providers | OpenRouter (primary), Anthropic, OpenAI |
| Search Providers | Tavily (primary), Serper (fallback) |
| Telegram Bot | aiogram v3 |
| Document Gen | python-docx + LibreOffice (PDF rendering) |
| Payments | Robokassa |
| Reverse Proxy | nginx 1.27 |
| CI | GitHub Actions (ruff → mypy → pytest) |

### Entry Points
1. **Telegram Bot** (`bot/app/main.py`) → FSM-driven conversation → API calls
2. **FastAPI** (`backend/app/main.py`) → REST API → Job creation → arq enqueue
3. **arq Worker** (`backend/app/workers/tasks.py`) → Pipeline orchestration → S3 upload
4. **Robokassa Webhook** (`backend/app/api/routes/payments.py`) → Payment confirmation

### Data Flow
```
User → Telegram Bot → FastAPI API → PostgreSQL (job record)
                                   → Redis (arq queue)
                                   → arq Worker → LLM Pipeline (6 stages)
                                                → S3 (document upload)
                                                → PostgreSQL (status update)
User ← Telegram Bot ← FastAPI API ← PostgreSQL (polling)
                                   ← S3 (download proxy)
```

### Codebase Size
- **~60 Python source files**, **~36 test files**
- **Backend**: 40+ modules across API, pipeline, LLM, services, models
- **Bot**: 10 modules (handlers, keyboards, API client)
- **Shared**: 4 schema modules
- **Infrastructure**: 3 Dockerfiles, docker-compose, nginx config

---

## ФАЗА 1: КРИТИЧЕСКИЕ ОШИБКИ И УЯЗВИМОСТИ

### [P0] BUG-001: `total_words` может быть undefined в orchestrator.py

- **Файл:** `backend/app/pipeline/orchestrator.py:445`
- **Проблема:** Переменная `total_words` используется в финальном логе (`pipeline_complete`), но она определяется только внутри условных блоков (`if config.enable_section_rewrite`, `if config.enable_humanizer`, цикл цитат). Если все эти блоки пропущены (например, `enable_section_rewrite=False`, `enable_humanizer=False`, пустая библиография), `total_words` будет определена на строке 223, но если после stage 3 выполнение пройдёт мимо всех пересчётов — используется устаревшее значение. Более критично: если `sections` пустой, `sum(s.word_count ...)` = 0, но `total_words` объявляется поздно.
- **Влияние:** Может вызвать `UnboundLocalError` в граничных случаях или логировать неверный счёт слов.
- **Решение:** Переместить `total_words = sum(s.word_count for s in result.sections)` перед финальным логом:
```python
# Before the final log
total_words = sum(s.word_count for s in result.sections)
logger.info("pipeline_complete", ..., words=total_words, ...)
```

### [P0] BUG-002: Search provider httpx clients never closed

- **Файл:** `backend/app/pipeline/research/searcher.py:37-40`, `searcher.py:94-96`
- **Проблема:** `TavilySearchProvider` и `SerperSearchProvider` создают persistent `httpx.AsyncClient` с `aclose()` метод, но в `run_pipeline` task (`tasks.py:268-272`) закрываются только `llm` и `vision_llm`. Search provider's `aclose()` никогда не вызывается.
- **Влияние:** Утечка TCP-соединений при каждом запуске пайплайна. В production с `max_jobs=3` и многими задачами это приведёт к исчерпанию файловых дескрипторов.
- **Решение:**
```python
# In tasks.py, after the finally block:
finally:
    if hasattr(llm, "aclose"):
        await llm.aclose()
    if vision_llm is not None and hasattr(vision_llm, "aclose"):
        await vision_llm.aclose()
    if hasattr(search, "aclose"):
        await search.aclose()
```

### [P0] SEC-001: SSRF protection uses synchronous DNS resolution in async context

- **Файл:** `backend/app/pipeline/research/scraper.py:32`
- **Проблема:** `socket.getaddrinfo()` — блокирующий вызов. В async-контексте с `asyncio.gather()` (до 5 concurrent scrapes) это блокирует event loop на время DNS-резолвинга каждого URL.
- **Влияние:** Блокировка event loop при скрейпинге. При медленных DNS-серверах — заметные задержки.
- **Решение:** Обернуть в `asyncio.to_thread()` или использовать `aiodns`:
```python
addr_infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
```

### [P0] SEC-002: TOCTOU race condition в SSRF protection

- **Файл:** `backend/app/pipeline/research/scraper.py:18-39, 74, 90`
- **Проблема:** DNS резолвится в `_is_safe_url()`, затем отдельный HTTP-запрос делается в `_scrape_single()`. Между проверкой и запросом DNS может измениться (DNS rebinding attack). Атакующий контролирует DNS: первый resolve → public IP, второй (httpx) → 127.0.0.1.
- **Влияние:** Потенциальный SSRF к внутренним сервисам (Redis, PostgreSQL, MinIO).
- **Решение:** Использовать httpx transport с pre-resolved IP или проверять IP после соединения. Минимальный фикс — добавить `follow_redirects=False` или проверять redirect targets.

### [P1] SEC-003: Robokassa webhook не проверяет IP-адрес отправителя

- **Файл:** `backend/app/api/routes/payments.py:103-181`
- **Проблема:** Endpoint `/payments/result` доступен публично и защищён только MD5-подписью. Robokassa рекомендует дополнительно проверять IP-адрес отправителя из белого списка.
- **Влияние:** Если `ROBOKASSA_PASSWORD2` утечёт, атакующий может подделать webhook и начислить себе кредиты.
- **Решение:** Добавить проверку `request.client.host` по белому списку IP Robokassa.

### [P1] SEC-004: MD5 для подписи платежей — криптографически слабый

- **Файл:** `backend/app/services/robokassa.py:14-17`
- **Проблема:** Robokassa использует MD5 для подписей. Хотя это требование Robokassa API и мы не можем его изменить, важно знать, что MD5 криптографически сломан. `hmac.compare_digest` используется правильно (timing-safe).
- **Влияние:** Низкий риск при текущем размере данных, но MD5 collision attacks существуют.
- **Решение:** Документировать риск. При возможности — переход на SHA-256 подпись (если Robokassa поддержит).

### [P1] BUG-003: `list_jobs` endpoint не фильтрует по user_id

- **Файл:** `backend/app/api/routes/jobs.py:157-172`
- **Проблема:** Endpoint `GET /api/jobs` возвращает ВСЕ jobs всех пользователей. Нет фильтрации по `user_id` или `telegram_id`. Любой запрос с валидным API-ключом видит все задания.
- **Влияние:** Information disclosure — пользователи могут видеть темы и статусы чужих работ.
- **Решение:** Добавить фильтрацию по `telegram_id`:
```python
@router.get("", response_model=list[JobResponse])
async def list_jobs(
    telegram_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[JobResponse]:
    query = select(Job).order_by(Job.created_at.desc())
    if telegram_id:
        query = query.join(User).where(User.telegram_id == telegram_id)
    query = query.limit(limit).offset(offset)
    ...
```

### [P1] BUG-004: `cancel_job` не возвращает кредит пользователю

- **Файл:** `backend/app/api/routes/jobs.py:175-193`
- **Проблема:** При отмене job (status PENDING) кредит уже списан при создании, но не возвращается при отмене.
- **Влияние:** Потеря кредитов пользователем. Особенно плохо при cancellation PENDING jobs, когда работа ещё не начата.
- **Решение:** При отмене PENDING job — атомарно вернуть кредит:
```python
if job.status == JobStatus.PENDING:
    await db.execute(
        sql_update(User)
        .where(User.id == job.user_id)
        .values(credits_remaining=User.credits_remaining + 1)
    )
```

### [P1] BUG-005: Race condition в `get_or_create_user_by_telegram_id`

- **Файл:** `backend/app/services/user_service.py:15-36`
- **Проблема:** `get → check None → create` — классический TOCTOU race. Два concurrent запроса от одного telegram_id могут оба пройти `get` = None и попытаться создать двух пользователей. UNIQUE constraint на `telegram_id` защитит от дупликации, но вызовет IntegrityError.
- **Влияние:** 500 ошибка при одновременных запросах от нового пользователя.
- **Решение:** Использовать `INSERT ... ON CONFLICT`:
```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = pg_insert(User).values(
    telegram_id=telegram_id,
    credits_remaining=1,
).on_conflict_do_nothing(index_elements=["telegram_id"])
await db.execute(stmt)
return await get_user_by_telegram_id(db, telegram_id)
```

### [P2] BUG-006: `lru_cache` на `get_s3_client` кеширует с secret_key в ключе

- **Файл:** `backend/app/services/storage.py:13-22`
- **Проблема:** `@lru_cache(maxsize=4)` использует все аргументы (включая `secret_key`) как ключ кеша. Secret key появляется в `__wrapped__.__cache_info__`. Также boto3 S3 client не thread-safe — если вызывается из нескольких потоков (через `asyncio.to_thread`), возможны проблемы.
- **Влияние:** Низкий риск утечки (только внутри процесса), но boto3 thread-safety — потенциальная проблема.
- **Решение:** Создавать клиент один раз при старте приложения или использовать `contextvar` / module-level singleton.

### [P2] BUG-007: `get_balance` возвращает 1 кредит для несуществующих пользователей

- **Файл:** `backend/app/api/routes/payments.py:189-206`
- **Проблема:** Если пользователь не найден, endpoint возвращает `credits_remaining=1`. Это hardcoded и не связано с реальным состоянием. Если пользователь был создан, потратил свой 1 кредит (0 remaining), и у нас баг в базе — мы покажем 1 вместо 0.
- **Влияние:** Ложная информация о балансе для новых пользователей до их первого взаимодействия.
- **Решение:** Создать пользователя при первом запросе баланса или возвращать 0 с флагом `is_new_user`.

### [P2] BUG-008: Worker создаёт новый S3 client на каждый job

- **Файл:** `backend/app/workers/tasks.py:25-66`
- **Проблема:** `_upload_document_to_s3` и `_download_from_s3` создают новый `boto3.client` при каждом вызове (в отличие от `storage.py` с кэшированием). Это дублирование логики.
- **Влияние:** Дублирование кода, лишнее создание клиентов. Потенциально разное поведение (worker не вызывает `head_bucket`/`create_bucket` в download, но вызывает в upload).
- **Решение:** Использовать `storage.py` функции:
```python
from backend.app.services.storage import upload_document, download_document
```

### [P2] SEC-005: `download_job_document` — нет проверки владельца job

- **Файл:** `backend/app/api/routes/jobs.py:196-240`
- **Проблема:** Любой с валидным API-ключом может скачать документ любого job по его ID. Нет проверки, что запрашивающий — владелец job.
- **Влияние:** Утечка сгенерированных документов между пользователями.
- **Решение:** Добавить проверку `telegram_id` из запроса или header.

### [P2] SEC-006: CORS `allow_origins=["*"]` в development

- **Файл:** `backend/app/main.py:82-88`
- **Проблема:** В debug mode — `allow_origins=["*"]` с `allow_credentials=True`. По спецификации, `*` с credentials не работает в браузерах, но это плохая практика. В production `allow_origins=[]` — API вообще не будет доступен с браузера.
- **Влияние:** Низкий (API защищён ключом), но потенциальный вектор для CSRF если ключ утечёт.
- **Решение:** Указать конкретные origins даже в dev mode.

### [P3] BUG-009: `query_expander.py` не экранирует фигурные скобки в topic

- **Файл:** `backend/app/pipeline/research/query_expander.py:53`
- **Проблема:** `QUERY_EXPANSION_PROMPT.format(topic=topic, ...)` — topic не проходит через `_safe()`. Если тема содержит `{` или `}`, произойдёт `KeyError`.
- **Влияние:** Crash пайплайна при редких темах с фигурными скобками.
- **Решение:** Добавить `_safe()` аналогично `section_writer.py`.

### [P3] BUG-010: `settings` computed at module level в `session.py`

- **Файл:** `backend/app/db/session.py:13`
- **Проблема:** `settings = get_settings()` вызывается при импорте модуля. Если env vars ещё не загружены или тесты хотят override — невозможно.
- **Влияние:** Затрудняет тестирование, невозможно override database_url после импорта.
- **Решение:** Использовать lazy initialization или dependency injection для engine.

---

## ФАЗА 2: АРХИТЕКТУРА

### [P1] ARCH-001: Нет Pipeline timeout enforcement

- **Файл:** `backend/app/pipeline/orchestrator.py`, `backend/app/workers/tasks.py`
- **Проблема:** `PipelineConfig.timeout_seconds` (default 900) объявлен, но нигде не используется для реального таймаута. `arq` имеет `job_timeout=1200`, но это грубый kill. Отдельные LLM-вызовы могут зависнуть на `httpx timeout=120s` каждый, и при 20+ вызовах в pipeline суммарное время может превысить любой лимит.
- **Влияние:** Job может зависнуть на часы, блокируя один из 3 worker slots.
- **Решение:** Обернуть `orchestrator.run()` в `asyncio.wait_for(timeout=config.timeout_seconds)`.

### [P1] ARCH-002: Нет graceful shutdown / cancellation propagation

- **Файл:** `backend/app/workers/tasks.py:228-231`
- **Проблема:** Cancellation проверяется только ПОСЛЕ завершения pipeline (`if job.status == JobStatus.CANCELLED`). Во время выполнения — нет проверки. Весь pipeline (5-15 минут) отработает полностью, потратив LLM-токены.
- **Влияние:** Трата денег на LLM API при cancelled jobs.
- **Решение:** Передать `CancellationToken` в orchestrator, проверять перед каждым stage:
```python
class CancellationToken:
    async def check(self, job_id: str) -> bool:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            return job and job.status == JobStatus.CANCELLED
```

### [P1] ARCH-003: Bot API client создаёт новый httpx.AsyncClient на каждый запрос

- **Файл:** `bot/app/services/api_client.py:26, 37, 47, ...`
- **Проблема:** Каждый метод `create_job`, `get_job`, `list_jobs` создаёт новый `httpx.AsyncClient` через `async with`. Это означает новый TLS handshake на каждый запрос к backend.
- **Влияние:** Увеличенная latency и расход ресурсов, особенно при polling status.
- **Решение:** Использовать persistent client:
```python
def __init__(self, base_url: str, api_key: str = ""):
    self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)

async def aclose(self):
    await self._client.aclose()
```

### [P2] ARCH-004: Отсутствие слоя repository / service в backend

- **Проблема:** Routes напрямую выполняют SQL-запросы (`db.execute(select(Job)...)`, `db.execute(sql_update(User)...)`). Бизнес-логика (credit deduction, admin check) находится в route handlers.
- **Влияние:** Дублирование логики, сложнее тестировать бизнес-правила отдельно от HTTP.
- **Решение:** Вынести в service layer:
```
api/routes/jobs.py  →  services/job_service.py  →  models/job.py
                       services/credit_service.py →  models/user.py
```

### [P2] ARCH-005: Shared schemas содержат `CHAPTER_INTRO = 0` и `CHAPTER_CONCLUSION = 99` — магические числа

- **Файл:** `shared/schemas/pipeline.py:7-8`
- **Проблема:** Sentinel values `0` и `99` для intro/conclusion разбросаны по всей кодовой базе. Если добавить >99 глав (невероятно, но fragile design).
- **Влияние:** Magic numbers затрудняют понимание кода.
- **Решение:** Уже объявлены как константы, но стоит использовать enum или отдельный `SectionType` для intro/conclusion вместо sentinel numbers в `chapter_number`.

### [P2] ARCH-006: Нет API versioning

- **Проблема:** API routes на `/api/jobs`, `/api/payments` — без версии. Нет возможности эволюционировать API без breaking changes.
- **Влияние:** При изменении контракта придётся мигрировать бота и API одновременно.
- **Решение:** `prefix="/api/v1"` — минимальное изменение.

### [P2] ARCH-007: Duplicated S3 upload/download logic

- **Файл:** `backend/app/workers/tasks.py:25-96` vs `backend/app/services/storage.py`
- **Проблема:** Два полностью отдельных набора S3 функций: `storage.py` (с caching) и `tasks.py` (без caching, с bucket creation). Разное поведение, дублирование.
- **Влияние:** DRY violation, баги при изменении одной копии без другой.
- **Решение:** Консолидировать в `storage.py`, добавить `ensure_bucket()` метод.

### [P3] ARCH-008: Нет structured error responses

- **Проблема:** API возвращает ошибки в формате FastAPI по умолчанию (`{"detail": "..."}`) — нет error codes, трacing IDs, локализованных сообщений.
- **Влияние:** Бот не может различать типы ошибок программно (кроме HTTP status code).
- **Решение:** Добавить error schema: `{"error": {"code": "INSUFFICIENT_CREDITS", "message": "...", "trace_id": "..."}}`

---

## ФАЗА 3: КАЧЕСТВО КОДА

### Читаемость и поддерживаемость

#### [P2] CODE-001: Orchestrator.run() — God Method (130+ строк)

- **Файл:** `backend/app/pipeline/orchestrator.py:115-461`
- **Проблема:** Единственный метод `run()` выполняет все 6+ stages последовательно. 350+ строк, 10+ условных блоков.
- **Решение:** Разбить на отдельные методы: `_run_research()`, `_run_outline()`, `_run_write()`, `_run_verify()`, `_run_format()`, `_run_visual_match()`.

#### [P2] CODE-002: Inline imports в route handlers

- **Файл:** `backend/app/api/routes/jobs.py:92, 210-211, 276-279`
- **Проблема:** `from backend.app.config import get_settings` импортируется inline внутри функций вместо top-of-file.
- **Влияние:** Нарушение PEP 8, затрудняет поиск зависимостей.
- **Решение:** Переместить все импорты в начало файла.

#### [P3] CODE-003: `set_response` vs `set_responses` в MockLLMProvider

- **Файл:** `backend/app/testing.py:16`
- **Проблема:** В CLAUDE.md упоминается `mock_llm.set_response()`, но в коде только `set_responses()` (plural). Несоответствие документации и API.
- **Влияние:** Путаница для разработчиков.
- **Решение:** Добавить alias `set_response` или обновить документацию.

### Type Safety

#### [P2] TYPE-001: Широкое использование `str` для enum-like полей в ORM

- **Файл:** `backend/app/models/job.py:28-39`
- **Проблема:** `status: Mapped[str]`, `stage: Mapped[str]`, `work_type: Mapped[str]` — все строки. Валидация только при чтении через Pydantic schemas. В базе может оказаться любое значение.
- **Влияние:** Data integrity risk — невалидные значения в БД.
- **Решение:** Использовать PostgreSQL ENUM types или CHECK constraints.

#### [P2] TYPE-002: `progress_callback` без type hint в нескольких местах

- **Файл:** `backend/app/pipeline/verifier/stage.py:32`, `backend/app/pipeline/writer/stage.py:53`
- **Проблема:** `progress_callback=None` без type annotation. mypy strict не поймает ошибки в callback signature.
- **Решение:** Определить `Protocol`:
```python
class ProgressCallback(Protocol):
    async def __call__(self, done: int, total: int) -> None: ...
```

### Тестирование

#### [P1] TEST-001: Нет integration tests с реальной БД

- **Проблема:** Все API tests используют mock DB или пропускают route-level тесты. `conftest.py` не создаёт test database. Нет тестов с SQLite/PostgreSQL.
- **Влияние:** Баги в SQL-запросах (credit deduction, atomic updates) не обнаруживаются тестами.
- **Решение:** Добавить `pytest-postgresql` или `testcontainers` fixture с реальной БД.

#### [P2] TEST-002: Orchestrator test мокает слишком глубоко

- **Файл:** `backend/tests/test_pipeline/test_orchestrator.py`
- **Проблема:** Тест устанавливает 15+ mock responses для каждого LLM-вызова. При изменении порядка вызовов или добавлении нового — все тесты ломаются.
- **Влияние:** Хрупкие тесты, тормозящие рефакторинг.
- **Решение:** Использовать higher-level mocks на уровне stages, не на уровне LLM.

#### [P2] TEST-003: Нет тестов для edge cases в payments

- **Проблема:** Нет тестов для: concurrent credit addition, double webhook, payment for non-existent user, webhook with tampered OutSum.
- **Влияние:** Не протестированы финансовые edge cases.
- **Решение:** Добавить тесты для race conditions в payment flow.

### Логирование и observability

#### [P1] LOG-001: Нет correlation ID / request tracing

- **Проблема:** Логи используют structlog, но нет `job_id` или `request_id` привязки к контексту. При нескольких concurrent pipelines невозможно различить логи.
- **Влияние:** Затруднённая отладка в production.
- **Решение:** Добавить structlog contextvars с `job_id` в worker и `request_id` в FastAPI middleware.

#### [P2] LOG-002: Отсутствие метрик (Prometheus/StatsD)

- **Проблема:** Нет сбора метрик: latency по stages, error rates, LLM token usage, job throughput.
- **Влияние:** Невозможно мониторить производительность и расходы.
- **Решение:** Добавить `prometheus-fastapi-instrumentator` + custom metrics.

#### [P2] LOG-003: Inconsistent logging — structlog vs logging

- **Файл:** `backend/app/utils/retry.py:16`, `backend/app/services/storage.py:10`
- **Проблема:** Часть модулей использует `structlog.get_logger()`, часть — `logging.getLogger()`. Разный формат вывода.
- **Влияние:** Несогласованные логи, сложнее парсить.
- **Решение:** Унифицировать на structlog везде.

---

## ФАЗА 4: НОВЫЕ ФИЧИ И УЛУЧШЕНИЯ

### [HIGH IMPACT] FEAT-001: Job progress via WebSocket

- **Описание:** Сейчас бот поллит `GET /api/jobs/{id}`. Добавить WebSocket endpoint для real-time updates.
- **Benefit:** Мгновенные уведомления, снижение нагрузки на API.
- **Effort:** Medium

### [HIGH IMPACT] FEAT-002: Retry failed jobs

- **Описание:** `retry_jobs = False` в WorkerSettings. Если LLM API временно недоступен — job навсегда FAILED. Добавить automatic retry с exponential backoff (1-3 попытки).
- **Benefit:** Надёжность при transient failures.
- **Effort:** Low

### [HIGH IMPACT] FEAT-003: Pipeline stage resume

- **Описание:** Если pipeline упал на stage 4 (verify), при retry — перезапускает с stage 1. Сохранять промежуточные результаты в Job JSONB и возобновлять с последнего успешного stage.
- **Benefit:** Экономия LLM-токенов, быстрое восстановление.
- **Effort:** Medium

### [MEDIUM IMPACT] FEAT-004: Admin dashboard

- **Описание:** Простой web UI для мониторинга: active jobs, queue depth, error rates, user credits. Можно на FastAPI + Jinja2 или отдельный frontend.
- **Benefit:** Операционная видимость.
- **Effort:** Medium

### [MEDIUM IMPACT] FEAT-005: Rate limiting per-user (не per-IP/API-key)

- **Описание:** Текущий rate limiter использует API key или IP. Добавить per-telegram_id limiting, чтобы один пользователь не мог создать 10 jobs через разные IP.
- **Benefit:** Защита от abuse.
- **Effort:** Low

### [MEDIUM IMPACT] FEAT-006: Health check с проверкой зависимостей

- **Файл:** `backend/app/api/routes/health.py`
- **Описание:** Текущий `/health` возвращает просто `{"status": "ok"}`. Добавить проверку PostgreSQL, Redis, S3 connectivity.
- **Benefit:** Реальная readiness probe для Kubernetes/Docker healthchecks.
- **Effort:** Low

### [LOW IMPACT] FEAT-007: Pre-commit hooks

- **Описание:** Добавить `.pre-commit-config.yaml` с ruff + mypy для автоматической проверки перед каждым коммитом.
- **Benefit:** Стабильность CI, быстрая обратная связь.
- **Effort:** Low

### [LOW IMPACT] FEAT-008: Makefile для общих команд

- **Описание:** `make test`, `make lint`, `make run`, `make docker-up` — удобство для разработчиков.
- **Effort:** Low

---

## ФАЗА 5: DEPENDENCY AUDIT

### Используемые зависимости (backend)

| Package | Version | Status | Notes |
|---------|---------|--------|-------|
| fastapi | >=0.115.0 | OK | Current stable |
| uvicorn | >=0.32.0 | OK | |
| pydantic | >=2.10.0 | OK | |
| pydantic-settings | >=2.6.0 | OK | |
| sqlalchemy | >=2.0.36 | OK | |
| asyncpg | >=0.30.0 | OK | |
| alembic | >=1.14.0 | OK | |
| arq | >=0.26.1 | OK | |
| redis | >=5.2.0 | OK | |
| httpx | >=0.28.0 | OK | |
| anthropic | >=0.39.0 | OK | |
| openai | >=1.56.0 | OK | |
| python-docx | >=1.1.2 | OK | |
| pdf2image | >=1.17.0 | OK | Requires poppler system dependency |
| trafilatura | >=1.12.0 | OK | |
| **playwright** | **>=1.49.0** | **UNUSED** | **Нигде не импортируется в коде. 150+ MB зависимость** |
| boto3 | >=1.35.0 | OK | |
| python-multipart | >=0.0.18 | OK | Required for file uploads |
| structlog | >=24.4.0 | OK | |

### [P1] DEP-001: Playwright — неиспользуемая зависимость (150+ MB)

- **Файл:** `backend/pyproject.toml:22`
- **Проблема:** `playwright>=1.49.0` в зависимостях, но НИ ОДИН файл не импортирует `playwright`. Document rendering использует LibreOffice + pdf2image.
- **Влияние:** +150 MB к Docker image, увеличение build time, потенциальные CVE.
- **Решение:** Удалить `playwright` из dependencies.

### [P2] DEP-002: `anthropic` и `openai` SDK — условные зависимости

- **Файл:** `backend/pyproject.toml:17-18`
- **Проблема:** Оба SDK в основных dependencies, хотя default provider — OpenRouter. Если пользователь использует только OpenRouter, ~50MB лишних пакетов.
- **Решение:** Перенести в `[project.optional-dependencies]`:
```toml
[project.optional-dependencies]
anthropic = ["anthropic>=0.39.0"]
openai = ["openai>=1.56.0"]
```

### [P3] DEP-003: `factory-boy` в dev dependencies — не используется

- **Файл:** `backend/pyproject.toml:40`
- **Проблема:** `factory-boy>=3.3.0` в dev deps, но тесты не используют фабрики.
- **Решение:** Удалить.

### Лицензионная совместимость

Все основные зависимости используют MIT, BSD или Apache 2.0 лицензии — совместимы друг с другом и с коммерческим использованием.

---

## EXECUTIVE SUMMARY

### Топ-5 критических проблем для немедленного исправления

| # | Issue | Severity | Effort |
|---|-------|----------|--------|
| 1 | **BUG-002**: Search provider TCP leak (httpx clients never closed) | P0 | Low |
| 2 | **SEC-002**: SSRF TOCTOU race condition in scraper | P0 | Medium |
| 3 | **BUG-004**: Cancel job doesn't refund credit | P1 | Low |
| 4 | **BUG-003**: list_jobs exposes all users' data | P1 | Low |
| 5 | **BUG-005**: Race condition in user creation | P1 | Low |

### Топ-5 архитектурных улучшений

| # | Improvement | Impact | Effort |
|---|-------------|--------|--------|
| 1 | ARCH-001: Pipeline timeout enforcement | High | Low |
| 2 | ARCH-002: Cancellation propagation during pipeline | High | Medium |
| 3 | ARCH-003: Persistent httpx client in bot | Medium | Low |
| 4 | ARCH-007: Consolidate S3 upload/download code | Medium | Low |
| 5 | ARCH-004: Service layer extraction | Medium | High |

### Топ-5 предлагаемых фич

| # | Feature | Impact | Effort |
|---|---------|--------|--------|
| 1 | FEAT-002: Retry failed jobs | High | Low |
| 2 | FEAT-003: Pipeline stage resume | High | Medium |
| 3 | FEAT-006: Readiness health check | Medium | Low |
| 4 | FEAT-001: WebSocket progress updates | Medium | Medium |
| 5 | FEAT-005: Per-user rate limiting | Medium | Low |

### Общая оценка зрелости: **6.5 / 10**

**Обоснование:**

**Сильные стороны (что хорошо):**
- Чёткая архитектура: разделение на backend/bot/shared, абстракции LLM providers, pipeline stages
- Atomic credit operations (SQL UPDATE ... WHERE > 0)
- SSRF protection (хоть и с TOCTOU)
- Structured logging (structlog)
- Comprehensive test suite (36 test files, покрытие pipeline stages)
- Clean Pydantic schemas, type hints на public interfaces
- Docker infrastructure с health checks
- Robokassa signature verification с timing-safe comparison
- CI pipeline (ruff + mypy + pytest)
- Good documentation (CLAUDE.md)

**Слабые стороны (что нужно улучшить):**
- Resource leaks (httpx clients не закрываются)
- Missing authorization on several endpoints
- No pipeline timeout/cancellation mechanism
- DRY violations (duplicated S3 code)
- No integration tests with real database
- No monitoring/metrics
- Unused dependency (playwright ~150MB)
- Missing service layer — business logic in route handlers
- No API versioning
- No correlation ID in logs
