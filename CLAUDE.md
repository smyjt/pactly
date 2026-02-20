# PACTLY - AI Contract Intelligence Engine

## Project Overview

Pactly is a production-grade AI Contract Intelligence Engine that accepts contract uploads (PDF/DOC), extracts and structures clauses, computes risk scores, and supports free-text RAG queries against contract content. This is NOT a chatbot — it's a structured analysis system that returns JSON.

**Owner:** @smyjt

**Stack:** Python 3.11, FastAPI, PostgreSQL + pgvector, Redis, Celery, OpenAI API, Docker

---

## Architecture

### System Pattern: Modular Monolith with Celery Workers

```
Client → FastAPI → Celery task queue → Workers
              |                           |
         Quick responses            Heavy processing (LLM, embedding)
              |
         pgvector + Redis (broker)
```

- **FastAPI** handles HTTP requests and returns immediately for async operations
- **Celery workers** process contracts in the background (PDF parse → chunk → extract clauses → embed → risk score)
- **PostgreSQL + pgvector** stores relational data AND vector embeddings in one database
- **Redis** serves as Celery broker and result backend
- **OpenAI API** provides LLM (GPT-4o-mini) and embeddings (text-embedding-3-small)

### Two Query Modes

1. **Auto-analysis (pre-computed):** Upload triggers automatic clause extraction + risk scoring. `GET /analysis` reads from DB. No LLM call at query time.
2. **Free-text RAG queries (on-demand):** `POST /query` embeds the question, retrieves relevant chunks from pgvector, builds a prompt, and calls the LLM. Returns answer + source chunks.

### LLM Provider Abstraction (Strategy Pattern)

All LLM calls go through `services/llm/base.py` → `LLMProvider` abstract class. OpenAI is the active provider. Adding Claude/Ollama = one new provider class + one config change. Zero business logic changes.

---

## Project Structure

```
pactly/
├── CLAUDE.md                    # This file — project context and standards
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env                         # NEVER commit this (contains OPENAI_API_KEY)
├── .env.example                 # Template for .env (committed)
├── alembic/                     # DB migrations
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory
│   ├── config.py                # pydantic-settings configuration
│   ├── dependencies.py          # Dependency injection
│   ├── routers/                 # HTTP layer — thin, no business logic
│   │   ├── contracts.py         #   POST /contracts, GET /contracts/:id
│   │   ├── analysis.py          #   GET /contracts/:id/analysis
│   │   └── query.py             #   POST /contracts/:id/query
│   ├── schemas/                 # Pydantic models (request/response validation)
│   │   ├── contract.py
│   │   ├── clause.py
│   │   ├── risk.py
│   │   └── query.py
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── base.py
│   │   ├── contract.py
│   │   ├── clause.py
│   │   ├── chunk.py
│   │   ├── risk_assessment.py
│   │   └── llm_usage_log.py
│   ├── services/                # All business logic lives here
│   │   ├── contract_service.py
│   │   ├── extraction_service.py  # PDF/DOCX parsing
│   │   ├── chunking_service.py    # Text chunking with overlap
│   │   ├── clause_service.py      # LLM clause extraction
│   │   ├── risk_service.py        # Rule engine + LLM risk scoring
│   │   ├── query_service.py       # Free-text RAG query pipeline
│   │   └── llm/
│   │       ├── base.py            # Abstract LLMProvider interface
│   │       ├── openai_provider.py
│   │       └── factory.py         # Provider factory (reads config)
│   ├── repositories/            # Data access only — SQL, vector search
│   │   ├── contract_repo.py
│   │   ├── clause_repo.py
│   │   ├── chunk_repo.py
│   │   └── embedding_repo.py     # pgvector similarity queries
│   └── workers/                 # Celery tasks — thin, call services
│       ├── celery_app.py
│       └── contract_tasks.py
├── tests/
│   ├── conftest.py              # Shared fixtures
│   ├── unit/
│   └── integration/
└── uploads/                     # Temporary file storage (volume-mounted)
```

---

## Database Schema

### Tables

- **contracts** — Core document record. Fields: id (UUID), filename, file_path, file_hash (SHA-256, UNIQUE — prevents duplicate uploads), content_type, raw_text, status (pending→processing→completed→failed), page_count, token_count, error_message, created_at, updated_at.
- **contract_chunks** — Raw text segments for vector retrieval. Fields: id (UUID), contract_id (FK), chunk_index, content, token_count, embedding (VECTOR(1536)), metadata (JSONB), created_at. Unique on (contract_id, chunk_index).
- **clauses** — LLM-extracted structured clauses. Fields: id (UUID), contract_id (FK), clause_type, title, content, summary, section_reference, embedding (VECTOR(1536)), metadata (JSONB), created_at.
- **risk_assessments** — Per-clause risk scoring. Fields: id (UUID), clause_id (FK, UNIQUE), risk_level (low/medium/high/critical), risk_score (0.0-1.0), rule_score, llm_score, explanation, flags (JSONB), created_at.
- **llm_usage_logs** — Every LLM call tracked. Fields: id (UUID), contract_id (FK nullable), provider, model, operation, input_tokens, output_tokens, cost_usd, latency_ms, success, error_message, created_at.

### pgvector Notes

- Extension: `CREATE EXTENSION vector;` in first Alembic migration
- Embedding dimension: 1536 (matches text-embedding-3-small)
- Cosine distance operator: `<=>` for similarity search
- If embedding model changes, ALL embeddings must be regenerated

---

## Layer Rules (STRICTLY ENFORCED)

### Routers (app/routers/)
- Parse request, call service, return response. That's it.
- NO business logic. NO direct DB queries. NO LLM calls.
- Depend on services via FastAPI dependency injection.
- Return Pydantic response schemas, never raw dicts.

### Services (app/services/)
- ALL business logic lives here.
- Services call repositories for data access and LLM providers for AI operations.
- Services NEVER import from routers.
- Services can call other services.
- Every public method must have clear input/output types.

### Repositories (app/repositories/)
- Data access ONLY — SQL queries, vector searches, CRUD.
- NO business decisions. NO LLM calls.
- Return ORM model instances or simple data types.
- All queries use parameterized statements (no string interpolation for SQL).

### Schemas (app/schemas/)
- Pydantic models for ALL request/response validation.
- ALL LLM outputs MUST be validated through a Pydantic schema before use.
- Use strict types where possible (e.g., `float` with `ge=0, le=1` for scores).
- Separate request schemas from response schemas.

### Workers (app/workers/)
- Celery tasks are THIN — they call services and handle task lifecycle.
- Do not put business logic in task functions.
- Always set task timeouts and max retries.

### LLM Layer (app/services/llm/)
- Abstract base class defines the interface.
- Each provider implements the interface.
- Factory creates the provider from config.
- Business logic NEVER calls OpenAI/Claude directly — always through the abstraction.

---

## Coding Standards

### Python Style
- Python 3.11, use modern syntax (type hints, `match` statements, `|` union types).
- Use `async/await` for all I/O operations (DB queries, HTTP calls, file reads).
- Type hints on ALL function signatures — parameters and return types.
- Use `Enum` or `Literal` for constrained string values (status fields, risk levels).
- Prefer dataclasses or Pydantic models over raw dicts.

### Naming Conventions
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`
- Database tables: `snake_case` plural (e.g., `contracts`, `clauses`)
- Database columns: `snake_case`

### Error Handling
- Define custom exception classes in `app/exceptions.py`.
- Services raise domain-specific exceptions (e.g., `ContractNotFoundError`, `LLMProviderError`).
- Routers catch exceptions and return appropriate HTTP status codes.
- NEVER catch bare `except Exception` in services — be specific.
- LLM calls MUST have retry with exponential backoff (3 retries, base delay 1s).
- All failures must be logged with context (contract_id, operation, error details).

### LLM-Specific Standards
- Every LLM call MUST be logged to `llm_usage_logs` (tokens, cost, latency, success/failure).
- Every LLM output MUST be validated against a Pydantic schema. LLMs hallucinate structure — trust nothing.
- Prompts must be stored as templates in a dedicated location, not inline in service code.
- Always include grounding instructions in prompts: "Only use information from the provided text."
- Set temperature to 0 for structured extraction tasks (deterministic output).
- Set max_tokens explicitly to prevent runaway costs.
- Include the model name and version in LLM usage logs for reproducibility.

### Database Standards
- All schema changes via Alembic migrations — never modify the DB manually.
- Use UUIDs as primary keys (not auto-increment integers).
- All timestamps use `TIMESTAMPTZ` (timezone-aware).
- Use `ON DELETE CASCADE` for child records (chunks, clauses belong to a contract).
- Index foreign keys and frequently queried columns.
- Use `JSONB` (not `JSON`) for flexible metadata fields.

### API Standards
- RESTful resource naming: `/contracts`, `/contracts/:id/analysis`, `/contracts/:id/query`.
- Always return consistent response envelopes.
- Use HTTP status codes correctly: 201 for creation, 202 for accepted async tasks, 404 for not found, 422 for validation errors.
- All endpoints must have OpenAPI documentation (FastAPI generates this automatically from type hints).
- File uploads via `multipart/form-data`, not base64.
- Maximum upload size: 20MB (configurable).

### Security
- NEVER commit `.env` or any file containing API keys.
- Validate and sanitize uploaded filenames (prevent path traversal).
- Limit file types to PDF and DOCX only (reject at upload, not after processing).
- Use parameterized queries for all database operations (SQLAlchemy handles this).
- Set CORS appropriately (restrictive by default).
- Rate limit the `/query` endpoint (it costs money per call).

### Testing
- Unit tests for services (mock repositories and LLM providers).
- Integration tests for repositories (use a test database).
- Test LLM provider abstraction with a mock provider.
- Test Pydantic schemas with edge cases (missing fields, wrong types, boundary values).
- Use pytest with async support (`pytest-asyncio`).
- Fixtures for common test data (sample contracts, chunks, clauses).

### Git Practices
- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
- One logical change per commit.
- Never commit generated files, uploads, or `.env`.
- `.gitignore` must include: `.env`, `uploads/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`.

---

## Configuration

All config via environment variables, loaded through `pydantic-settings`:

```
# .env
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql+asyncpg://pactly:pactly@postgres:5432/pactly
REDIS_URL=redis://redis:6379/0
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
CHUNK_SIZE=500                    # tokens per chunk
CHUNK_OVERLAP=50                  # overlap tokens between chunks
MAX_UPLOAD_SIZE_MB=20
LOG_LEVEL=INFO
```

---

## Docker Setup

```bash
# Start everything
docker compose up --build

# Stop (keep data)
docker compose down

# Stop and destroy all data
docker compose down -v
```

Services:
- `app` — FastAPI on port 8000 (`uvicorn`)
- `worker` — Celery worker (same image, different entrypoint)
- `postgres` — PostgreSQL 16 + pgvector on port 5432 (`pgvector/pgvector:pg16`)
- `redis` — Redis on port 6379
- `pgadmin` — (dev only) DB admin UI on port 5050

App and worker share the same Docker image. Alembic migrations run on app startup.

---

## Build Phases

### Phase 1: Foundation
- Project structure, Docker Compose, DB schema, Alembic migrations
- Basic upload endpoint (save file, create DB record, return contract ID)
- Health check endpoint

### Phase 2: Clause Extraction
- PDF/DOCX text extraction
- Text chunking with overlap
- LLM structured output for clause extraction
- Pydantic validation of LLM responses

### Phase 3: Embeddings & Storage
- Generate embeddings via OpenAI API
- Store chunk and clause embeddings in pgvector
- Implement similarity search in embedding_repo

### Phase 4: RAG Pipeline
- Free-text query endpoint
- Embed query → retrieve chunks → build prompt → generate answer
- Return structured response with source references

### Phase 5: Risk Scoring
- Rule-based risk engine (pattern matching, keyword detection)
- LLM-based risk assessment
- Hybrid scoring (weighted combination)
- Per-clause and overall contract risk scores

### Phase 6: Production Hardening
- LLM cost tracking and observability
- Retry with exponential backoff for all external calls
- Error handling and failure recovery
- Evaluation framework for retrieval and extraction quality

---

## Key Dependencies

| Package | Purpose |
|---------|---------|
| fastapi | Web framework |
| uvicorn | ASGI server |
| sqlalchemy[asyncio] | ORM with async support |
| asyncpg | Async PostgreSQL driver |
| alembic | Database migrations |
| pgvector | pgvector SQLAlchemy integration |
| celery[redis] | Task queue |
| pydantic-settings | Configuration management |
| openai | OpenAI API client |
| pymupdf | PDF text extraction |
| python-docx | DOCX text extraction |
| tiktoken | Token counting (matches OpenAI tokenizer) |
| tenacity | Retry with exponential backoff |
| python-multipart | File upload support |
| pytest / pytest-asyncio | Testing |
| httpx | Async HTTP client for tests |

---

## Common Mistakes to Avoid

1. **Putting business logic in routers.** Routers are HTTP adapters. Logic goes in services.
2. **Trusting LLM output without schema validation.** LLMs hallucinate fields, wrong types, extra data. Always validate.
3. **Not logging LLM usage.** You will lose track of costs. Log every call.
4. **Fixed-boundary chunking.** Always use overlap to avoid splitting clauses at chunk boundaries.
5. **Catching bare exceptions.** Be specific. `except openai.RateLimitError` not `except Exception`.
6. **Hardcoding model names.** Always read from config. Models change frequently.
7. **Synchronous LLM calls in async endpoints.** Use `await` or run in thread pool. Blocking calls freeze the event loop.
8. **Embedding dimension mismatch.** If you switch embedding models, dimensions change. All embeddings must be regenerated.
9. **Not setting max_tokens on LLM calls.** Without limits, a confused LLM can generate thousands of tokens and rack up costs.
10. **Committing .env files.** Use .env.example as a template. Never commit real keys.
