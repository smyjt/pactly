# Phase 2: Contract Processing Pipeline Implementation Plan

**Goal:** Implement the full background processing pipeline — PDF/DOCX extraction → text chunking → LLM clause extraction → save to DB.

**Architecture:** When a contract is uploaded, a Celery task runs in the background: (1) parse raw text from the file using pymupdf/python-docx, (2) split into 500-token overlapping chunks using tiktoken, (3) call GPT-4o-mini to extract structured clauses with Pydantic validation. All LLM calls are logged with token counts, cost, and latency. The Celery task uses `asyncio.run()` to call async services since Celery workers run synchronously.

**Tech Stack:** pymupdf, python-docx, tiktoken, openai (async), tenacity (retry), Pydantic v2, SQLAlchemy async, Alembic, Celery

---

## Context

Phase 1 is complete. The app accepts file uploads, saves to `/app/uploads/`, creates a DB record with `status=pending`. The `process_contract` Celery task exists but is a no-op placeholder.

**Problem to fix first:** `contract_chunks.embedding` is `NOT NULL` in the DB. Phase 2 doesn't generate embeddings yet (Phase 3 does). Need a migration to make it nullable before we can insert chunks.

**Key files:**
- `app/services/contract_service.py` — has TODO comment for Celery dispatch
- `app/workers/contract_tasks.py` — the no-op task we're implementing
- `app/repositories/contract_repo.py` — `update_status()` needs extending
- `app/models/chunk.py` — embedding column currently NOT NULL
- `app/config.py` — CHUNK_SIZE, CHUNK_OVERLAP, LLM_MODEL settings

---

## Task 1: Make chunk embedding nullable (Alembic migration)

**Files:**
- Create: `alembic/versions/<rev>_make_chunk_embedding_nullable.py`
- Modify: `app/models/chunk.py`

**Steps:**
1. Run `alembic revision --autogenerate -m "make_chunk_embedding_nullable"` inside the app container
2. Inspect the generated file — if autogenerate missed the pgvector column, write the `op.alter_column` upgrade/downgrade manually
3. Update the `embedding` column in `app/models/chunk.py` to `nullable=True` with type `list[float] | None`
4. Apply with `alembic upgrade head` and verify via `\d contract_chunks` in psql
5. Commit: `chore: make contract_chunks.embedding nullable for phase 2`

---

## Task 2: Extend ContractRepository with update()

**Files:**
- Modify: `app/repositories/contract_repo.py`

**Steps:**
1. Add a general `update(contract_id, **kwargs)` method that sets any fields via `setattr` and calls `flush()`
2. This replaces the need to call `update_status()` for every field combination
3. Commit: `feat: add update() method to ContractRepository`

---

## Task 3: LLM Provider Abstraction

**Files:**
- Create: `app/services/llm/__init__.py`
- Create: `app/services/llm/base.py` — `LLMResponse` dataclass + `LLMProvider` abstract base class
- Create: `app/services/llm/openai_provider.py` — OpenAI implementation with tenacity retry on RateLimitError and APITimeoutError (3 attempts, exponential backoff)
- Create: `app/services/llm/factory.py` — reads `settings.LLM_PROVIDER`, returns the right provider instance; raises `ValueError` for unknown providers

**Steps:**
1. Create `base.py` with `LLMResponse` (content, input_tokens, output_tokens, model, latency_ms) and abstract `complete()` method
2. Create `openai_provider.py` implementing `complete()` — wraps `AsyncOpenAI`, measures latency, maps response to `LLMResponse`
3. Create `factory.py` with `create_llm_provider(settings)` function
4. Commit: `feat: add LLM provider abstraction (base, OpenAI, factory)`

---

## Task 4: Extraction Service

**Files:**
- Create: `app/services/extraction_service.py`

**Steps:**
1. Create `ExtractionResult` dataclass with `raw_text: str` and `page_count: int`
2. Create `ExtractionService` with a `extract(file_path, content_type)` method that dispatches to `_extract_pdf` or `_extract_docx`
3. PDF: use `pymupdf.open()`, join pages with `\n\n`
4. DOCX: use `python-docx`, join non-empty paragraphs with `\n\n`, set `page_count=1`
5. Raise `ValueError` for unsupported content types
6. Commit: `feat: add ExtractionService for PDF and DOCX text extraction`

---

## Task 5: Chunking Service

**Files:**
- Create: `app/services/chunking_service.py`

**Steps:**
1. Create `Chunk` dataclass with `index`, `content`, `token_count`
2. Create `ChunkingService.__init__` accepting `chunk_size`, `overlap`, `encoding_name="cl100k_base"`
3. Implement `chunk(text) -> list[Chunk]` using `tiktoken` — encode to tokens, slide window by `chunk_size - overlap` each iteration, decode back to text for each chunk
4. Return empty list for blank input
5. Commit: `feat: add ChunkingService with token-based overlap chunking`

---

## Task 6: Clause Schemas, Prompts, and ClauseService

**Files:**
- Create: `app/schemas/clause.py` — `ClauseType` Literal, `ExtractedClause` Pydantic model, `ClauseExtractionResult` Pydantic model
- Create: `app/services/llm/prompts/__init__.py`
- Create: `app/services/llm/prompts/clause_extraction.py` — system prompt + user prompt template with `{contract_text}` placeholder
- Create: `app/services/clause_service.py`

**Steps:**
1. Define `ClauseType` as a `Literal` of: termination, liability, indemnity, payment, confidentiality, intellectual_property, dispute_resolution, governing_law, force_majeure, warranty, limitation_of_liability, non_compete, assignment, other
2. Define `ExtractedClause` with: `clause_type`, `title`, `content`, `summary`, `section_reference: str | None`
3. Define `ClauseExtractionResult` with `clauses: list[ExtractedClause]`
4. Write system + user prompt templates in `prompts/clause_extraction.py` — instruct LLM to return JSON only, grounded in provided text
5. Implement `ClauseService.extract_clauses(contract_id, raw_text)` — truncate text at 400k chars, build messages, call `llm.complete()` with `temperature=0`, `max_tokens=4000`, `response_format={"type": "json_object"}`, parse JSON, validate through Pydantic, return `(ClauseExtractionResult, usage_dict)`
6. Commit: `feat: add clause schemas, extraction prompts, and ClauseService`

---

## Task 7: Chunk, Clause, and LLMUsageLog Repositories

**Files:**
- Create: `app/repositories/chunk_repo.py`
- Create: `app/repositories/clause_repo.py`
- Create: `app/repositories/llm_usage_log_repo.py`

**Steps:**
1. `ChunkRepository.bulk_create(contract_id, chunks: list[dict])` — constructs `ContractChunk` objects, adds all, flushes
2. `ClauseRepository.bulk_create(contract_id, clauses: list[dict])` — same pattern for `Clause` objects
3. `LLMUsageLogRepository.create(**kwargs)` — constructs and flushes a single `LLMUsageLog`
4. Commit: `feat: add ChunkRepository, ClauseRepository, LLMUsageLogRepository`

---

## Task 8: Wire up the Celery task and dispatch on upload

**Files:**
- Modify: `app/workers/contract_tasks.py`
- Modify: `app/services/contract_service.py`

**Steps:**
1. Replace the placeholder in `contract_tasks.py` with the full pipeline inside `_process_contract_async(contract_id)` (called via `asyncio.run`):
   - Transaction 1: set `status=processing`, commit immediately
   - Transaction 2: get contract, extract text, chunk, call LLM, log usage, save chunks + clauses, set `status=completed`, commit
   - On any exception: update `status=failed` with `error_message`, commit in a separate transaction
   - Always dispose the engine in `finally`
   - Include `_calculate_cost(input_tokens, output_tokens, model)` helper using gpt-4o-mini pricing
2. In `contract_service.py`, replace the TODO comment with the actual `process_contract.delay(str(contract.id))` call
3. Commit: `feat: implement contract processing pipeline in Celery task`

---

## Task 9: Smoke test end-to-end in Docker

**Steps:**
1. `docker compose down && docker compose up --build -d`
2. `docker compose exec app alembic upgrade head`
3. Upload a real PDF via `curl -X POST http://localhost:8000/api/v1/contracts -F "file=@/path/to/contract.pdf"`
4. Poll `GET /api/v1/contracts/<id>` until `status=completed`
5. Verify in psql: contract has `page_count` and `token_count`, `contract_chunks` has rows, `clauses` has rows, `llm_usage_logs` has a row with `cost_usd`
6. Check worker logs for no tracebacks: `docker compose logs worker --tail=50`

---

## Phase 2 Done

At this point: uploaded contracts are fully processed in background — raw text extracted, chunks saved, clauses extracted and validated, every LLM call logged with cost.

**Phase 3** will add embeddings for chunks and clauses in pgvector, enabling similarity search for RAG queries.
