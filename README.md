# Pactly — AI Contract Intelligence Engine

Pactly is a backend system that analyzes legal contracts using AI. Upload a PDF or DOCX contract and get back structured clause extraction, risk scoring, and the ability to ask plain-English questions about the document.

---

## What it does

- **Accepts contract uploads** — PDF and DOCX supported
- **Extracts clauses automatically** — identifies termination, liability, indemnity, payment, and other clause types using an LLM
- **Scores risk** — combines rule-based pattern matching with LLM judgment to produce a risk score per clause and an overall contract risk score
- **Answers questions** — ask "what happens if I breach section 4?" and get an answer grounded in the actual contract text (RAG-powered)
- **Tracks costs** — every LLM call is logged with token counts, cost in USD, and latency

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI (Python 3.12) |
| Background processing | Celery |
| Database | PostgreSQL 16 |
| Vector search | pgvector |
| Cache / message broker | Redis |
| LLM | OpenAI GPT-4o-mini (extensible to Claude, Ollama) |
| Embeddings | OpenAI text-embedding-3-small |
| Containerization | Docker Compose |

---

## Architecture

```
Client
  │
  ▼
FastAPI (port 8000)
  │
  ├── POST /api/v1/contracts               → upload contract
  ├── GET  /api/v1/contracts/:id           → check processing status
  ├── GET  /api/v1/contracts/:id/analysis  → get clauses + risk scores
  └── POST /api/v1/contracts/:id/query     → ask a question about the contract
  │
  ▼
Redis (task queue)
  │
  ▼
Celery Worker
  │
  ├── Parse PDF/DOCX → raw text
  ├── Chunk text → 500-token segments with overlap
  ├── LLM: extract structured clauses
  ├── Generate embeddings → store in pgvector
  └── Score risk per clause
  │
  ▼
PostgreSQL + pgvector
```

Uploads are processed asynchronously. The API responds immediately with a contract ID. The client polls `GET /contracts/:id` to check when processing is complete.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- An OpenAI API key — get one at [platform.openai.com](https://platform.openai.com)

---

## Setup

**1. Clone the repository**

```bash
git clone https://github.com/smyjt/pactly.git
cd pactly
```

**2. Create your environment file**

```bash
cp .env.example .env
```

Open `.env` and set your OpenAI API key:

```env
OPENAI_API_KEY=sk-your-key-here
```

The rest of the defaults work out of the box with Docker Compose.

**3. Start the application**

```bash
docker compose up --build
```

This starts PostgreSQL, Redis, the FastAPI server, and the Celery worker. On first run, Docker builds the image and installs dependencies — this takes a few minutes.

**4. Run database migrations**

In a separate terminal:

```bash
docker compose exec app alembic upgrade head
```

**5. Verify everything is running**

```bash
curl http://localhost:8000/health
# {"status": "healthy", "version": "0.1.0"}
```

---

## API Usage

### Interactive docs

Open `http://localhost:8000/docs` for the Swagger UI — you can test all endpoints directly from the browser.

### Upload a contract

```bash
curl -X POST http://localhost:8000/api/v1/contracts \
  -F "file=@/path/to/contract.pdf"
```

Response:
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

Response:
```json
{
  "id": "3f7a2c1d-...",
  "filename": "contract.pdf",
  "status": "completed",
  "page_count": 12,
  "token_count": 4821
}
```

Status values: `pending` → `processing` → `completed` / `failed`

---

## Development

**Stop the application**

```bash
docker compose down          # stop containers, keep data
docker compose down -v       # stop containers and delete database
```

**View logs**

```bash
docker compose logs app      # FastAPI logs
docker compose logs worker   # Celery worker logs
docker compose logs -f app   # follow live logs
```

**Rebuild after dependency changes**

```bash
docker compose up --build
```

**Connect to the database directly**

```bash
docker compose exec postgres psql -U pactly -d pactly
```

---

## Local Development (without Docker)

```bash
# Requires Python 3.12+
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start postgres and redis via Docker, run app locally
docker compose up postgres redis -d

# Update DATABASE_URL in .env to use localhost instead of 'postgres'
# DATABASE_URL=postgresql+asyncpg://pactly:pactly@localhost:5432/pactly
# DATABASE_URL_SYNC=postgresql://pactly:pactly@localhost:5432/pactly

alembic upgrade head
uvicorn app.main:app --reload
```

---

## Project Structure

```
pactly/
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── config.py            # Settings (loaded from .env)
│   ├── database.py          # SQLAlchemy engine + session factory
│   ├── exceptions.py        # Custom exception classes
│   ├── models/              # SQLAlchemy ORM models (DB tables)
│   ├── schemas/             # Pydantic models (API request/response)
│   ├── repositories/        # Data access layer (SQL queries)
│   ├── services/            # Business logic
│   │   └── llm/             # LLM provider abstraction
│   ├── routers/             # HTTP route handlers
│   └── workers/             # Celery background tasks
├── alembic/                 # Database migrations
├── tests/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example             # Environment variable template
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | Your OpenAI API key |
| `LLM_PROVIDER` | No | `openai` | LLM provider (`openai`, `claude`, `ollama`) |
| `LLM_MODEL` | No | `gpt-4o-mini` | Model used for extraction and analysis |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model |
| `DATABASE_URL` | Yes | — | Async PostgreSQL connection string |
| `DATABASE_URL_SYNC` | Yes | — | Sync PostgreSQL connection string (Alembic) |
| `REDIS_URL` | No | `redis://redis:6379/0` | Redis connection string |
| `CHUNK_SIZE` | No | `500` | Tokens per text chunk |
| `CHUNK_OVERLAP` | No | `50` | Overlap tokens between chunks |
| `MAX_UPLOAD_SIZE_MB` | No | `20` | Maximum upload file size |
