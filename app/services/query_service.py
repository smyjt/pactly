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
from app.services.llm.cost import estimate_llm_cost
from app.services.llm.prompts.rag_query import RAG_QUERY_SYSTEM, RAG_QUERY_USER

logger = logging.getLogger(__name__)

# How many chunks to retrieve and inject as context.
# 5 is a standard RAG default — enough to cover a topic without flooding the prompt.
_TOP_K = 5

# Cap the LLM's answer length. Q&A answers don't need to be long.
# Without this, a confused LLM could generate thousands of tokens and cost money.
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

        # All repos share the same session — they participate in the same DB transaction
        self._contract_repo = ContractRepository(session)
        self._embedding_repo = EmbeddingRepository(session)
        self._log_repo = LLMUsageLogRepository(session)

    async def query(self, contract_id: uuid.UUID, question: str) -> QueryResponse:
        """Run the full RAG pipeline for a free-text question against a contract."""

        # Step 1: Verify the contract exists before doing any expensive work
        contract = await self._contract_repo.get_by_id(contract_id)
        if not contract:
            raise ContractNotFoundError(str(contract_id))

        logger.info(f"[query] contract={contract_id} question={question!r}")

        # Step 2: Embed the question using the same model that embedded the chunks.
        # This is critical — if you embed the question with a different model than
        # the chunks, the vectors live in different spaces and similarity means nothing.
        question_embeddings = await self.embedding_service.embed([question])
        question_vector = question_embeddings[0]

        # Step 3: Find the most relevant chunks via cosine similarity.
        # Returns (ContractChunk, similarity_score) tuples, ordered best-first.
        results = await self._embedding_repo.similarity_search(
            contract_id=contract_id,
            query_embedding=question_vector,
            top_k=_TOP_K,
        )

        # Edge case: contract was uploaded but embeddings were never generated
        # (e.g. processing failed mid-way). Return a safe fallback instead of crashing.
        if not results:
            logger.warning(f"[query] No embedded chunks for contract={contract_id}")
            return QueryResponse(
                contract_id=contract_id,
                question=question,
                answer="I could not find information about this in the provided contract sections.",
                sources=[],
                model="none",
                input_tokens=0,
                output_tokens=0,
            )

        # Step 4: Format the retrieved chunks as numbered excerpts.
        # Numbering them lets the LLM (and the user reading the sources) reference
        # which excerpt was used. The separator makes boundaries visually clear.
        context = "\n\n---\n\n".join(
            f"[Excerpt {i + 1}]\n{chunk.content}"
            for i, (chunk, _) in enumerate(results)
        )

        # Step 5: Call the LLM with the context + question.
        # Temperature 0.3: slightly above zero so answers read naturally,
        # but low enough that the LLM stays grounded and doesn't get creative.
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
            f"[query] done contract={contract_id} "
            f"tokens={response.input_tokens}in/{response.output_tokens}out "
            f"latency={response.latency_ms}ms"
        )

        # Step 6: Log every LLM call — provider, model, tokens, cost, latency.
        # This is how we track spend. Every query costs money; logging makes it visible.
        await self._log_repo.create(
            contract_id=contract_id,
            provider=self.llm_provider_name,
            model=response.model,
            operation="rag_query",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=estimate_llm_cost(response.input_tokens, response.output_tokens, response.model),
            latency_ms=response.latency_ms,
            success=True,
        )

        # Step 7: Build the source list from the retrieved chunks.
        # We include the real cosine similarity score from pgvector so the caller
        # can see how confident the retrieval was. High score = very relevant chunk.
        sources = [
            SourceChunk(
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                similarity_score=score,
            )
            for chunk, score in results
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
