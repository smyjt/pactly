# Pactly — AI Contract Intelligence Engine

Pactly turns legal contracts into structured, queryable intelligence. Upload a PDF or DOCX and Pactly automatically extracts every significant clause, scores its risk, and lets you ask plain-English questions about the document — all grounded in the actual contract text, not AI guesswork.

Built for teams that review contracts at volume and can't afford to miss what's buried on page 14.

---

## What it does

- **Clause extraction** — identifies and structures termination, liability, indemnity, payment, confidentiality, IP, and other clause types using an LLM
- **Risk scoring** — combines rule-based pattern matching with LLM judgment to produce a risk score per clause and an overall contract risk level
- **Plain-English Q&A** — ask "what's the notice period for termination?" and get an answer drawn directly from the contract text (RAG-powered, with source references)
- **Cost visibility** — every LLM call is logged with token counts, cost in USD, and latency

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI (Python 3.12) |
| Background processing | Celery |
| Database | PostgreSQL 16 + pgvector |
| Cache / message broker | Redis |
| LLM | OpenAI GPT-4o-mini (or Groq) |
| Embeddings | OpenAI text-embedding-3-small |

---

## Architecture

```
POST /contracts (upload)
       │
       ▼
  FastAPI → saves file → returns contract ID immediately
       │
       ▼
  Redis (task queue)
       │
       ▼
  Celery Worker (processes in background)
       ├── Extract text (PDF/DOCX)
       ├── Chunk into 500-token segments with overlap
       ├── LLM: extract and structure clauses
       ├── Generate + store vector embeddings (pgvector)
       └── Score risk per clause (rule-based + LLM)
       │
       ▼
  PostgreSQL + pgvector
```

Processing is asynchronous. The API responds immediately with a contract ID. Poll `GET /contracts/:id` until `status` is `completed`, then use the analysis and query endpoints.

---

## Setup

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) and an [OpenAI API key](https://platform.openai.com).

**1. Clone and configure**

```bash
git clone https://github.com/smyjt/pactly.git
cd pactly
cp .env.example .env
```

Open `.env` and set your `OPENAI_API_KEY`. All other defaults work as-is with Docker.

**2. Start everything**

```bash
docker compose up --build
```

Starts PostgreSQL, Redis, the FastAPI server, and the Celery worker. First run takes a few minutes to build.

**3. Run migrations**

```bash
docker compose exec app alembic upgrade head
```

**4. Verify**

```bash
curl http://localhost:8000/health
# {"status": "healthy", "version": "0.1.0"}
```

Interactive API docs: http://localhost:8000/docs

---

## API

### Upload a contract

```bash
curl -X POST http://localhost:8000/api/v1/contracts \
  -F "file=@/path/to/contract.pdf"
```

```json
{
  "id": "3f7a2c1d-...",
  "filename": "contract.pdf",
  "status": "pending",
  "message": "Contract uploaded. Processing will begin shortly."
}
```

### Check processing status

```bash
curl http://localhost:8000/api/v1/contracts/3f7a2c1d-...
```

Status flow: `pending` → `processing` → `completed` / `failed`

### Get extracted clauses and risk scores

```bash
curl http://localhost:8000/api/v1/contracts/3f7a2c1d-.../analysis
```

### Ask a question about the contract

```bash
curl -X POST http://localhost:8000/api/v1/contracts/3f7a2c1d-.../query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the notice period for termination?"}'
```

Returns a grounded answer with the source contract excerpts it was drawn from.

### Delete a contract

```bash
curl -X DELETE http://localhost:8000/api/v1/contracts/3f7a2c1d-...
```

---

## Development

**Stop / reset**

```bash
docker compose down        # stop, keep data
docker compose down -v     # stop and delete all data
```

**Rebuild after dependency changes**

```bash
docker compose up --build
```

**View logs**

```bash
docker compose logs -f app      # FastAPI (live)
docker compose logs -f worker   # Celery worker (live)
docker compose logs app         # FastAPI (historical)
docker compose logs worker      # Celery worker (historical)
```

**Connect to the database**

```bash
docker compose exec postgres psql -U pactly -d pactly
```

Useful queries:

```sql
-- Contract status overview
SELECT id, filename, status, page_count, token_count, created_at FROM contracts;

-- Chunks and clauses per contract
SELECT c.filename,
       COUNT(DISTINCT ch.id) AS chunks,
       COUNT(DISTINCT cl.id) AS clauses
FROM contracts c
LEFT JOIN contract_chunks ch ON ch.contract_id = c.id
LEFT JOIN clauses cl ON cl.contract_id = c.id
GROUP BY c.filename;

-- Embedding coverage
SELECT contract_id,
       COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded,
       COUNT(*) AS total
FROM contract_chunks GROUP BY contract_id;

-- LLM usage and cost by operation
SELECT operation, model,
       SUM(input_tokens) AS in_tokens,
       SUM(output_tokens) AS out_tokens,
       ROUND(SUM(cost_usd)::numeric, 6) AS cost_usd
FROM llm_usage_logs GROUP BY operation, model;
```

**Migrations**

```bash
# Generate migration from model changes
docker compose exec app alembic revision --autogenerate -m "description"

# Apply
docker compose exec app alembic upgrade head

# Roll back one step
docker compose exec app alembic downgrade -1
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `GROQ_API_KEY` | No | — | Groq API key (if using Groq) |
| `LLM_PROVIDER` | No | `openai` | `openai` or `groq` |
| `LLM_MODEL` | No | `gpt-4o-mini` | Model for extraction and analysis |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model |
| `EMBEDDING_DIMENSION` | No | `1536` | Vector dimensions — must match the embedding model |
| `DATABASE_URL` | Yes | — | Async PostgreSQL connection string |
| `DATABASE_URL_SYNC` | Yes | — | Sync PostgreSQL connection string (Alembic) |
| `REDIS_URL` | No | `redis://redis:6379/0` | Redis connection string |
| `CHUNK_SIZE` | No | `500` | Tokens per text chunk |
| `CHUNK_OVERLAP` | No | `50` | Overlap tokens between chunks |
| `MAX_UPLOAD_SIZE_MB` | No | `20` | Maximum upload file size |

---

## Project Structure

```
pactly/
├── app/
│   ├── main.py              # FastAPI app factory + DI wiring
│   ├── config.py            # Settings (loaded from .env)
│   ├── database.py          # SQLAlchemy engine + session factory
│   ├── exceptions.py        # Custom exception classes
│   ├── models/              # SQLAlchemy ORM models
│   ├── schemas/             # Pydantic request/response models
│   ├── repositories/        # Data access layer (SQL + vector queries)
│   ├── services/            # Business logic
│   │   └── llm/             # LLM provider abstraction + prompts
│   ├── routers/             # HTTP route handlers (thin layer)
│   ├── workers/             # Celery task definitions
│   └── events/              # Internal event bus
├── alembic/                 # Database migrations
├── docs/plans/              # Implementation plan documents
├── tests/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```
