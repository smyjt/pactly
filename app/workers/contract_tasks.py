import asyncio
import logging
import uuid

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, acks_late=True)
def process_contract(self, contract_id: str) -> dict:
    """Background task: extract text, chunk, extract clauses via LLM, save to DB."""
    logger.info(f"Starting processing for contract {contract_id}")
    return asyncio.run(_process_contract_async(contract_id))


async def _process_contract_async(contract_id: str) -> dict:
    # Lazy imports — avoids loading all app code on every Celery worker boot
    from app.config import Settings
    from app.database import create_engine, create_session_factory
    from app.repositories.chunk_repo import ChunkRepository
    from app.repositories.clause_repo import ClauseRepository
    from app.repositories.contract_repo import ContractRepository
    from app.repositories.llm_usage_log_repo import LLMUsageLogRepository
    from app.services.chunking_service import ChunkingService
    from app.services.clause_service import ClauseService
    from app.services.extraction_service import ExtractionService
    from app.services.llm.factory import create_llm_provider

    settings = Settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    cid = uuid.UUID(contract_id)

    try:
        # Transaction 1: mark as processing so the status is visible immediately
        async with factory() as session:
            repo = ContractRepository(session)
            await repo.update(cid, status="processing")
            await session.commit()

        # Transaction 2: full pipeline
        async with factory() as session:
            contract_repo = ContractRepository(session)
            contract = await contract_repo.get_by_id(cid)
            if not contract:
                logger.error(f"Contract {contract_id} not found — cannot process")
                return {"contract_id": contract_id, "status": "failed"}

            # Step 1: Extract raw text from file
            extraction = ExtractionService().extract(contract.file_path, contract.content_type)

            # Step 2: Chunk the text
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

            # Step 3: LLM clause extraction
            llm = create_llm_provider(settings)
            clause_svc = ClauseService(llm)
            clause_result, usage = await clause_svc.extract_clauses(cid, extraction.raw_text)

            # Log LLM usage
            log_repo = LLMUsageLogRepository(session)
            await log_repo.create(
                contract_id=cid,
                provider=settings.LLM_PROVIDER,
                model=usage["model"],
                operation="clause_extraction",
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cost_usd=_calculate_cost(
                    usage["input_tokens"], usage["output_tokens"], usage["model"]
                ),
                latency_ms=usage["latency_ms"],
                success=True,
            )

            # Save clauses
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

            # Update contract with extracted metadata and mark completed
            await contract_repo.update(
                cid,
                raw_text=extraction.raw_text,
                page_count=extraction.page_count,
                token_count=total_tokens,
                status="completed",
            )

            await session.commit()

        clause_count = len(clause_result.clauses)
        logger.info(
            f"Contract {contract_id} processed: {clause_count} clauses, "
            f"{len(chunks)} chunks, {extraction.page_count} pages"
        )
        return {
            "contract_id": contract_id,
            "status": "completed",
            "clauses_count": clause_count,
            "chunks_count": len(chunks),
        }

    except Exception as exc:
        logger.exception(f"Failed to process contract {contract_id}: {exc}")
        try:
            async with factory() as session:
                repo = ContractRepository(session)
                await repo.update(cid, status="failed", error_message=str(exc))
                await session.commit()
        except Exception as inner_exc:
            logger.error(f"Could not update failed status for {contract_id}: {inner_exc}")
        return {"contract_id": contract_id, "status": "failed", "error": str(exc)}

    finally:
        await engine.dispose()


def _calculate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Estimate cost in USD based on OpenAI pricing (per 1M tokens)."""
    PRICING: dict[str, dict[str, float]] = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
    }
    rates = PRICING.get(model, PRICING["gpt-4o-mini"])
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
