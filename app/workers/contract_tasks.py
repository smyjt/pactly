import asyncio
import logging
import uuid

from celery import chain as celery_chain
from celery.exceptions import MaxRetriesExceededError

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def build_processing_chain(contract_id: str) -> celery_chain:
    """Return a Celery chain that fully processes a contract.

    To add a new processing phase, append its task here with .s().
    Each task receives the previous task's return value as its first argument.
    """
    return celery_chain(
        task_extract_and_chunk.s(contract_id),
        task_extract_clauses.s(),
        task_generate_embeddings.s(),
    )


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, acks_late=True)
def task_extract_and_chunk(self, contract_id: str) -> dict:
    """Extract raw text from the uploaded file, chunk it, and save to DB."""
    logger.info(f"[extract_and_chunk] Starting for contract {contract_id}")
    return asyncio.run(_extract_and_chunk_async(self, contract_id))


async def _extract_and_chunk_async(task, contract_id: str) -> dict:
    from app.config import Settings
    from app.database import create_engine, create_session_factory
    from app.repositories.chunk_repo import ChunkRepository
    from app.repositories.contract_repo import ContractRepository
    from app.services.chunking_service import ChunkingService
    from app.services.extraction_service import ExtractionService

    settings = Settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    cid = uuid.UUID(contract_id)

    try:
        async with factory() as session:
            repo = ContractRepository(session)
            await repo.update(cid, status="processing")
            await session.commit()

        async with factory() as session:
            contract_repo = ContractRepository(session)
            contract = await contract_repo.get_by_id(cid)
            if not contract:
                logger.error(f"[extract_and_chunk] Contract {contract_id} not found")
                return {"contract_id": contract_id, "status": "failed"}

            extraction = ExtractionService().extract(contract.file_path, contract.content_type)

            chunking_svc = ChunkingService(
                chunk_size=settings.CHUNK_SIZE,
                overlap=settings.CHUNK_OVERLAP,
            )
            chunks = chunking_svc.chunk(extraction.raw_text)
            total_tokens = sum(c.token_count for c in chunks)

            chunk_repo = ChunkRepository(session)
            await chunk_repo.bulk_create(
                cid,
                [
                    {"chunk_index": c.index, "content": c.content, "token_count": c.token_count}
                    for c in chunks
                ],
            )

            # Save raw_text so the next task can read it without re-parsing the file
            await contract_repo.update(
                cid,
                raw_text=extraction.raw_text,
                page_count=extraction.page_count,
                token_count=total_tokens,
            )
            await session.commit()

        logger.info(
            f"[extract_and_chunk] Done for contract {contract_id}: "
            f"{len(chunks)} chunks, {extraction.page_count} pages"
        )
        return {"contract_id": contract_id}

    except MaxRetriesExceededError:
        await _mark_failed(factory, cid, "Max retries exceeded during text extraction")
        raise

    except Exception as exc:
        logger.exception(f"[extract_and_chunk] Failed for contract {contract_id}: {exc}")
        try:
            raise task.retry(exc=exc)
        except MaxRetriesExceededError:
            await _mark_failed(factory, cid, str(exc))
            raise

    finally:
        await engine.dispose()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, acks_late=True)
def task_extract_clauses(self, prev_result: dict) -> dict:
    """Extract structured clauses from the contract via LLM and save to DB."""
    contract_id = prev_result["contract_id"]
    logger.info(f"[extract_clauses] Starting for contract {contract_id}")
    return asyncio.run(_extract_clauses_async(self, contract_id))


async def _extract_clauses_async(task, contract_id: str) -> dict:
    from app.config import Settings
    from app.database import create_engine, create_session_factory
    from app.repositories.clause_repo import ClauseRepository
    from app.repositories.contract_repo import ContractRepository
    from app.repositories.llm_usage_log_repo import LLMUsageLogRepository
    from app.services.clause_service import ClauseService
    from app.services.llm.factory import create_llm_provider

    settings = Settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    cid = uuid.UUID(contract_id)

    try:
        async with factory() as session:
            contract_repo = ContractRepository(session)
            contract = await contract_repo.get_by_id(cid)
            if not contract:
                logger.error(f"[extract_clauses] Contract {contract_id} not found")
                return {"contract_id": contract_id, "status": "failed"}

            llm = create_llm_provider(settings)
            clause_svc = ClauseService(llm, max_chars=settings.LLM_MAX_CHARS, max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS)
            clause_result, usage = await clause_svc.extract_clauses(cid, contract.raw_text)

            log_repo = LLMUsageLogRepository(session)
            await log_repo.create(
                contract_id=cid,
                provider=settings.LLM_PROVIDER,
                model=usage["model"],
                operation="clause_extraction",
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cost_usd=_calculate_cost(usage["input_tokens"], usage["output_tokens"], usage["model"]),
                latency_ms=usage["latency_ms"],
                success=True,
            )

            clause_repo = ClauseRepository(session)
            await clause_repo.bulk_create(
                cid,
                [
                    {
                        "clause_type": c.clause_type,
                        "title": c.title,
                        "content": c.content,
                        "summary": c.summary,
                        "section_reference": c.section_reference,
                    }
                    for c in clause_result.clauses
                ],
            )

            await session.commit()

        clause_count = len(clause_result.clauses)
        logger.info(f"[extract_clauses] Done for contract {contract_id}: {clause_count} clauses")
        return {"contract_id": contract_id, "clause_count": clause_count}

    except MaxRetriesExceededError:
        await _mark_failed(factory, cid, "Max retries exceeded during clause extraction")
        raise

    except Exception as exc:
        logger.exception(f"[extract_clauses] Failed for contract {contract_id}: {exc}")
        try:
            raise task.retry(exc=exc)
        except MaxRetriesExceededError:
            await _mark_failed(factory, cid, str(exc))
            raise

    finally:
        await engine.dispose()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, acks_late=True)
def task_generate_embeddings(self, prev_result: dict) -> dict:
    """Generate and store vector embeddings for all chunks of a contract."""
    contract_id = prev_result["contract_id"]
    logger.info(f"[generate_embeddings] Starting for contract {contract_id}")
    return asyncio.run(_generate_embeddings_async(self, contract_id))


async def _generate_embeddings_async(task, contract_id: str) -> dict:
    from app.config import Settings
    from app.database import create_engine, create_session_factory
    from app.repositories.chunk_repo import ChunkRepository
    from app.repositories.contract_repo import ContractRepository
    from app.services.embedding_service import EmbeddingService

    settings = Settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    cid = uuid.UUID(contract_id)

    try:
        async with factory() as session:
            chunk_repo = ChunkRepository(session)
            chunks = await chunk_repo.get_by_contract_id(cid)

            if not chunks:
                logger.warning(f"[generate_embeddings] No chunks found for contract {contract_id}")
                return {"contract_id": contract_id, "embedded_chunks": 0}

            embedding_svc = EmbeddingService(
                api_key=settings.OPENAI_API_KEY,
                model=settings.EMBEDDING_MODEL,
                dimensions=settings.EMBEDDING_DIMENSION,
            )
            embeddings = await embedding_svc.embed([chunk.content for chunk in chunks])
            await chunk_repo.bulk_update_embeddings(chunks, embeddings)

            contract_repo = ContractRepository(session)
            await contract_repo.update(cid, status="completed")
            await session.commit()

        logger.info(f"[generate_embeddings] Done for contract {contract_id}: {len(chunks)} chunks embedded")
        return {"contract_id": contract_id, "embedded_chunks": len(chunks)}

    except MaxRetriesExceededError:
        await _mark_failed(factory, cid, "Max retries exceeded during embedding generation")
        raise

    except Exception as exc:
        logger.exception(f"[generate_embeddings] Failed for contract {contract_id}: {exc}")
        try:
            raise task.retry(exc=exc)
        except MaxRetriesExceededError:
            await _mark_failed(factory, cid, str(exc))
            raise

    finally:
        await engine.dispose()


async def _mark_failed(factory, contract_id: uuid.UUID, error_message: str) -> None:
    """Best-effort status update to failed. Swallows its own errors."""
    try:
        from app.repositories.contract_repo import ContractRepository
        async with factory() as session:
            repo = ContractRepository(session)
            await repo.update(contract_id, status="failed", error_message=error_message)
            await session.commit()
    except Exception as inner:
        logger.error(f"Could not mark contract {contract_id} as failed: {inner}")


def _calculate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Estimate cost in USD based on OpenAI pricing (per 1M tokens)."""
    PRICING: dict[str, dict[str, float]] = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
    }
    rates = PRICING.get(model, PRICING["gpt-4o-mini"])
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
