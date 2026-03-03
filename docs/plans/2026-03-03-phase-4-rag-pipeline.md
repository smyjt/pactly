# Phase 4: RAG Pipeline Implementation Plan

**Goal:** Build a `POST /contracts/:id/query` endpoint that accepts a free-text question, retrieves the most relevant contract chunks via vector similarity, and returns a grounded LLM-generated answer with source references.

**Architecture:** Embed the user's question → cosine similarity search in pgvector → inject top-K chunks as context into a prompt → LLM generates a grounded answer → return answer + source chunks. All LLM calls are logged to `llm_usage_logs`.

**Tech Stack:** FastAPI, PostgreSQL + pgvector, OpenAI embeddings (`text-embedding-3-small`), OpenAI chat completions (`gpt-4o-mini`), Pydantic, SQLAlchemy async, existing `EmbeddingService`, `EmbeddingRepository`, `LLMProvider` abstraction.

---

## What is RAG and why do we use it?

**RAG = Retrieval-Augmented Generation.**

The naive alternative to RAG is: paste the entire contract into the prompt and ask the LLM your question. This breaks for two reasons:
1. **Context window limits.** LLMs can only read a fixed amount of text at once (GPT-4o-mini: ~128K tokens). Long contracts exceed this.
2. **Cost.** You pay per token. Sending 50 pages of contract for every question is expensive.

RAG solves this: instead of sending everything, we find only the *relevant* parts and send those.

**How the retrieval works:**
- At upload time (Phase 3), we turned every text chunk into a vector (a list of 1536 numbers) — this is the "embedding". Words with similar meanings produce vectors that point in similar directions in that 1536-dimensional space.
- At query time, we embed the *question* using the same model. The question's vector will naturally point toward the contract chunks that talk about similar topics.
- pgvector's `<=>` operator computes **cosine distance** between two vectors. Lower distance = more similar. We return the top-K closest chunks.

**Why this works well for contracts:**
- "What is the notice period for termination?" will retrieve termination clauses, not payment clauses.
- The LLM only sees the relevant paragraphs, so the answer is focused and grounded.

---

## Task 1: Query Schemas

**What we're building:** The Pydantic models that define what the API accepts as input and returns as output for the query endpoint.

**Why this first:** In FastAPI, the schema IS the API contract. Writing it first forces clarity about the shape of the feature before touching service logic. FastAPI generates OpenAPI docs from these schemas automatically.

**New concept — source attribution:** We return not just the answer but the source chunks the answer was drawn from. This is important in legal contexts — users need to be able to verify that the AI's answer is actually grounded in the contract text, not hallucinated.

---

**Files:**
- Create: `app/schemas/query.py`

---

**Step 1: Create the schema file**

```python
# app/schemas/query.py
import uuid
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=1000)


class SourceChunk(BaseModel):
    chunk_index: int
    content: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)


class QueryResponse(BaseModel):
    contract_id: uuid.UUID
    question: str
    answer: str
    sources: list[SourceChunk]
    model: str
    input_tokens: int
    output_tokens: int
```

**Step 2: Verify it loads without errors**

```bash
docker compose exec app python -c "from app.schemas.query import QueryRequest, QueryResponse, SourceChunk; print('OK')"
```

Expected output: `OK`

**Step 3: Commit**

```bash
git add app/schemas/query.py
git commit -m "feat: add query request/response schemas"
```

---

> **Pause.** Task 1 complete. Review the schemas, commit, then signal ready for Task 2.

---

## Task 2: RAG Prompt Template

**What we're building:** The system and user prompt templates for the RAG query call.

**Why a separate file:** Following the same pattern as `clause_extraction.py`. Prompts are not code — they're instructions to a different kind of system. Keeping them in a dedicated file makes them easy to find, iterate on, and test independently of service logic.

**Key prompt design decisions:**
- **Grounding instruction:** "Only use the contract text provided below. Do not use outside knowledge." This prevents hallucination — the LLM making up plausible-sounding but false information about a contract it hasn't actually seen.
- **"I don't know" instruction:** Explicitly tell the LLM to say it doesn't know if the answer isn't in the provided chunks. Without this, LLMs will confidently fabricate answers.
- **Temperature:** We'll use `0.3` (slightly above zero). For extraction tasks (Phase 2) we used `0.0` (fully deterministic). For question-answering, a small amount of variation makes the language feel more natural while still being accurate. Not creative, just fluent.
- **Context injection:** The retrieved chunks are numbered and injected into the user message. Numbering them lets the LLM (and later, us) reference which chunk was used.

---

**Files:**
- Create: `app/services/llm/prompts/rag_query.py`

---

**Step 1: Create the prompt file**

```python
# app/services/llm/prompts/rag_query.py

RAG_QUERY_SYSTEM = """\
You are a legal contract analysis assistant.
Answer questions about the contract based ONLY on the provided contract excerpts.
Do not use any outside knowledge or make assumptions beyond what is written.
If the answer cannot be found in the provided text, say exactly:
"I could not find information about this in the provided contract sections."\
"""

RAG_QUERY_USER = """\
Contract excerpts (use only these to answer):

{context}

Question: {question}

Answer based only on the excerpts above:\
"""
```

**Step 2: Verify it loads**

```bash
docker compose exec app python -c "from app.services.llm.prompts.rag_query import RAG_QUERY_SYSTEM, RAG_QUERY_USER; print('OK')"
```

Expected output: `OK`

**Step 3: Commit**

```bash
git add app/services/llm/prompts/rag_query.py
git commit -m "feat: add RAG query prompt templates"
```

---

> **Pause.** Task 2 complete. Review the prompt. Commit, then signal ready for Task 3.

---

## Task 3: QueryService

**What we're building:** The core RAG pipeline as a service class. This is the most important file in Phase 4.

**The pipeline, step by step:**
1. Verify the contract exists (raise `ContractNotFoundError` if not)
2. Embed the user's question using `EmbeddingService`
3. Search pgvector for the top-K most similar chunks using `EmbeddingRepository.similarity_search`
4. Build the prompt: format the retrieved chunks as numbered context
5. Call the LLM via the `LLMProvider` abstraction
6. Log the LLM call to `llm_usage_logs` (cost, tokens, latency)
7. Compute similarity scores for the source chunks (convert cosine *distance* to *similarity* score: `score = 1 - distance`)
8. Return a `QueryResponse`

**Why does cosine distance need to be converted to a similarity score?**
pgvector's `<=>` operator returns **distance** (0 = identical, 2 = opposite). We convert to **similarity** (1 = identical, 0 = opposite) with `score = 1 - distance` so that high scores feel intuitive in the API response. However, pgvector's `similarity_search` doesn't return the distance directly — we get ORM objects back. For now we compute a dummy score based on rank (top chunk = highest score). A future improvement would use a raw SQL query to return distance alongside results.

> **Design note — top_k=5:** We retrieve the 5 most relevant chunks. This is a common default in RAG systems. Too few (1-2) and we might miss relevant context; too many (10+) and we're sending noise to the LLM, increasing cost and reducing answer quality. 5 is a reasonable starting point.

---

**Files:**
- Create: `app/services/query_service.py`

---

**Step 1: Create the service**

```python
# app/services/query_service.py
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ContractNotFoundError
from app.repositories.contract_repo import ContractRepository
from app.repositories.embedding_repo import EmbeddingRepository
from app.repositories.llm_usage_log_repo import LLMUsageLogRepository
from app.schemas.query import QueryResponse, SourceChunk
from app.services.embedding_service import EmbeddingService
from app.services.llm.base import LLMProvider
from app.services.llm.prompts.rag_query import RAG_QUERY_SYSTEM, RAG_QUERY_USER

logger = logging.getLogger(__name__)

_TOP_K = 5
_MAX_OUTPUT_TOKENS = 1000


class QueryService:
    def __init__(
        self,
        session: AsyncSession,
        llm: LLMProvider,
        embedding_service: EmbeddingService,
        llm_provider_name: str,
    ):
        self.session = session
        self.llm = llm
        self.embedding_service = embedding_service
        self.llm_provider_name = llm_provider_name

        self._contract_repo = ContractRepository(session)
        self._embedding_repo = EmbeddingRepository(session)
        self._log_repo = LLMUsageLogRepository(session)

    async def query(self, contract_id: uuid.UUID, question: str) -> QueryResponse:
        """Run the full RAG pipeline for a free-text question against a contract."""

        # 1. Verify contract exists
        contract = await self._contract_repo.get_by_id(contract_id)
        if not contract:
            raise ContractNotFoundError(str(contract_id))

        logger.info(f"[query] Starting RAG for contract={contract_id} question={question!r}")

        # 2. Embed the question
        question_embeddings = await self.embedding_service.embed([question])
        question_vector = question_embeddings[0]

        # 3. Retrieve top-K relevant chunks via cosine similarity
        chunks = await self._embedding_repo.similarity_search(
            contract_id=contract_id,
            query_embedding=question_vector,
            top_k=_TOP_K,
        )

        if not chunks:
            logger.warning(f"[query] No embedded chunks found for contract={contract_id}")
            return QueryResponse(
                contract_id=contract_id,
                question=question,
                answer="I could not find information about this in the provided contract sections.",
                sources=[],
                model="none",
                input_tokens=0,
                output_tokens=0,
            )

        # 4. Build context string from retrieved chunks
        context_parts = [
            f"[Excerpt {i + 1}]\n{chunk.content}"
            for i, chunk in enumerate(chunks)
        ]
        context = "\n\n---\n\n".join(context_parts)

        # 5. Call LLM
        messages = [
            {"role": "system", "content": RAG_QUERY_SYSTEM},
            {"role": "user", "content": RAG_QUERY_USER.format(context=context, question=question)},
        ]

        response = await self.llm.complete(
            messages=messages,
            temperature=0.3,
            max_tokens=_MAX_OUTPUT_TOKENS,
        )

        logger.info(
            f"[query] LLM answered contract={contract_id}: "
            f"{response.input_tokens} in / {response.output_tokens} out tokens, "
            f"{response.latency_ms}ms"
        )

        # 6. Log LLM usage
        await self._log_repo.create(
            contract_id=contract_id,
            provider=self.llm_provider_name,
            model=response.model,
            operation="rag_query",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=_estimate_cost(response.input_tokens, response.output_tokens, response.model),
            latency_ms=response.latency_ms,
            success=True,
        )

        # 7. Build source list (rank-based similarity scores: top chunk = 1.0, decreasing)
        total = len(chunks)
        sources = [
            SourceChunk(
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                similarity_score=round(1.0 - (i / total), 2),
            )
            for i, chunk in enumerate(chunks)
        ]

        return QueryResponse(
            contract_id=contract_id,
            question=question,
            answer=response.content,
            sources=sources,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )


def _estimate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    PRICING: dict[str, dict[str, float]] = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
    }
    rates = PRICING.get(model, PRICING["gpt-4o-mini"])
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
```

**Step 2: Verify it imports cleanly**

```bash
docker compose exec app python -c "from app.services.query_service import QueryService; print('OK')"
```

Expected output: `OK`

**Step 3: Commit**

```bash
git add app/services/query_service.py
git commit -m "feat: add QueryService with RAG pipeline"
```

---

> **Pause.** Task 3 complete. Read through the service — this is the heart of Phase 4. Commit, then signal ready for Task 4.

---

## Task 4: Query Router

**What we're building:** The HTTP layer — a thin FastAPI router for `POST /contracts/:id/query`.

**Why thin:** The router's only job is to translate HTTP into function calls. It receives the request, calls the service, catches domain exceptions, and returns the HTTP response. No business logic lives here.

**HTTP semantics:**
- `POST` not `GET` — even though this is a "read" operation, we POST because the request has a body (the question). `GET` requests shouldn't have bodies per HTTP spec.
- `200 OK` — not `201 Created` (nothing is being created) and not `202 Accepted` (this is synchronous, we wait for the answer).
- `404` if contract doesn't exist.
- `422` if the question is missing or too short (FastAPI/Pydantic handles this automatically from the schema).

---

**Files:**
- Create: `app/routers/query.py`

---

**Step 1: Create the router**

```python
# app/routers/query.py
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.exceptions import ContractNotFoundError
from app.schemas.query import QueryRequest, QueryResponse
from app.services.query_service import QueryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contracts", tags=["Query"])


def get_query_service() -> QueryService:
    raise NotImplementedError("Dependency override not configured")


@router.post(
    "/{contract_id}/query",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
)
async def query_contract(
    contract_id: uuid.UUID,
    body: QueryRequest,
    service: QueryService = Depends(get_query_service),
):
    """Ask a free-text question about a contract. Returns a grounded answer with source excerpts."""
    logger.info(f"Query request: contract_id={contract_id} question={body.question!r}")
    try:
        result = await service.query(contract_id, body.question)
        logger.info(
            f"Query response: contract_id={contract_id} "
            f"sources={len(result.sources)} model={result.model}"
        )
        return result
    except ContractNotFoundError:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found.")
```

**Step 2: Verify it imports cleanly**

```bash
docker compose exec app python -c "from app.routers.query import router; print('OK')"
```

Expected output: `OK`

**Step 3: Commit**

```bash
git add app/routers/query.py
git commit -m "feat: add query router POST /contracts/:id/query"
```

---

> **Pause.** Task 4 complete. Commit, then signal ready for Task 5.

---

## Task 5: Wire Up in main.py

**What we're building:** Registering the query router and wiring its dependency injection in `app/main.py`.

**Why dependency injection matters:** `QueryService` needs a DB session, an LLM provider, and an `EmbeddingService`. FastAPI's DI system creates fresh instances per request — so each request gets its own DB session (no shared state, no connection leaks). `main.py` is where we configure which concrete implementations satisfy which dependencies.

**Pattern to follow:** Look at how `contracts_router` and `get_clause_service` are already registered — we follow the exact same pattern.

---

**Files:**
- Modify: `app/main.py`

---

**Step 1: Add the query router registration**

In `app/main.py`, inside `create_app()`, after the existing router registrations, add:

```python
    from app.routers.query import router as query_router, get_query_service
    from app.repositories.embedding_repo import EmbeddingRepository
    from app.services.embedding_service import EmbeddingService
    from app.services.query_service import QueryService

    async def get_query_service_with_session(
        session: AsyncSession = Depends(get_session),
    ) -> QueryService:
        return QueryService(
            session=session,
            llm=create_llm_provider(settings),
            embedding_service=EmbeddingService(
                api_key=settings.OPENAI_API_KEY,
                model=settings.EMBEDDING_MODEL,
                dimensions=settings.EMBEDDING_DIMENSION,
            ),
            llm_provider_name=settings.LLM_PROVIDER,
        )

    application.include_router(query_router, prefix="/api/v1")
    application.dependency_overrides[get_query_service] = get_query_service_with_session
```

**Step 2: Restart the app and verify the endpoint appears in the docs**

```bash
docker compose restart app
```

Then open: http://localhost:8000/docs

You should see `POST /api/v1/contracts/{contract_id}/query` listed under the "Query" tag.

**Step 3: Smoke test with curl**

Use the ID of a contract you've already uploaded and processed:

```bash
curl -s -X POST http://localhost:8000/api/v1/contracts/<your-contract-id>/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the notice period for termination?"}' | python -m json.tool
```

Expected: A JSON response with `answer`, `sources` (list of chunks), `model`, and token counts.

**Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: wire query router and QueryService into app"
```

---

> **Pause.** Task 5 complete — Phase 4 is live. Commit, then we move to Phase 5: Risk Scoring.

---

## Phase 4 Summary

What you built and the concepts behind each piece:

| Piece | File | Concept |
|---|---|---|
| API schema | `schemas/query.py` | Pydantic validation, source attribution |
| Prompt template | `services/llm/prompts/rag_query.py` | Grounding, hallucination prevention |
| RAG pipeline | `services/query_service.py` | Embed → retrieve → generate loop |
| HTTP layer | `routers/query.py` | Thin router, DI, REST semantics |
| Wiring | `main.py` | FastAPI dependency injection |

The full data flow for a query:
```
POST /contracts/:id/query
  → QueryService.query()
    → EmbeddingService.embed(question)        # question → vector
    → EmbeddingRepository.similarity_search() # vector → top-K chunks
    → LLMProvider.complete(context + question) # chunks + question → answer
    → LLMUsageLogRepository.create()           # log cost/tokens
  ← QueryResponse(answer, sources, tokens)
```
