# Phase 3 — Chunk Embeddings

**Goal:** Generate and store vector embeddings for all contract chunks so Phase 4 RAG retrieval can do semantic similarity search.

**Scope:** Chunks only. Clause embeddings deferred to Phase 5.

---

## What gets built

1. `EmbeddingService` — thin abstraction over OpenAI's embedding API
2. `ChunkRepository` additions — fetch chunks by contract, bulk update embeddings
3. `task_generate_embeddings` — new Celery task appended to the existing chain
4. Chain updated: `extract_and_chunk → extract_clauses → generate_embeddings`

---

## Key design decisions

**Separate abstraction from LLM**
Embeddings are not the same API as chat completions. `LLMProvider` does text generation. Embeddings go through a separate `EmbeddingService` with its own method signature. Same strategy pattern — easy to swap providers later.

**OpenAI only for now**
Groq does not support embeddings. `EMBEDDING_MODEL` and `EMBEDDING_DIMENSION` are already in `Settings`. We always use OpenAI for embeddings regardless of `LLM_PROVIDER`.

**Batching**
OpenAI's embedding API accepts up to 2048 texts per request. We batch in groups of 100 to avoid hitting limits on large contracts. Each batch = one API call.

**Data flows through DB**
`task_generate_embeddings` receives `{"contract_id": ...}` from the chain, loads chunks from DB, saves embeddings back. Nothing large passes through Redis.

**No new Alembic migration needed**
`contract_chunks.embedding` column (Vector(1536)) already exists from Phase 1.

---

## New files

| File | Purpose |
|---|---|
| `app/services/embedding_service.py` | `EmbeddingService` — calls OpenAI embeddings API, returns `list[list[float]]` |

## Modified files

| File | Change |
|---|---|
| `app/repositories/chunk_repo.py` | Add `get_by_contract_id()` and `bulk_update_embeddings()` |
| `app/workers/contract_tasks.py` | Add `task_generate_embeddings`, append to `build_processing_chain` |

---

## Task breakdown

### 1. EmbeddingService
- `app/services/embedding_service.py`
- Constructor: `__init__(api_key, model, dimensions)`
- Method: `async embed(texts: list[str]) -> list[list[float]]`
- Batches internally (batch size 100)
- Uses `openai.AsyncOpenAI`
- Logs total tokens used (OpenAI returns usage on embedding calls)

### 2. ChunkRepository additions
- `get_by_contract_id(contract_id) -> list[ContractChunk]`
- `bulk_update_embeddings(chunks: list[ContractChunk], embeddings: list[list[float]]) -> None`
  — zips chunks with embeddings, sets `chunk.embedding`, flushes

### 3. task_generate_embeddings
- Receives `prev_result: dict` from chain (has `contract_id`)
- Loads all chunks for the contract
- Calls `EmbeddingService.embed()` on `[chunk.content for chunk in chunks]`
- Saves embeddings back via `bulk_update_embeddings`
- Returns `{"contract_id": contract_id, "embedded_chunks": N}`
- Error handling same pattern as existing tasks

### 4. Wire into chain
```python
# contract_tasks.py — build_processing_chain
return celery_chain(
    task_extract_and_chunk.s(contract_id),
    task_extract_clauses.s(),
    task_generate_embeddings.s(),   # ← add this
)
```

---

## Verify when done

```sql
-- should return non-null embeddings
SELECT chunk_index, token_count, embedding IS NOT NULL AS has_embedding
FROM contract_chunks
WHERE contract_id = '<id>'
ORDER BY chunk_index;
```
