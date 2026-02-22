import logging

from app.events.contract_events import ContractUploaded

logger = logging.getLogger(__name__)


def on_contract_uploaded(event: ContractUploaded) -> None:
    # Lazy import avoids loading Celery worker code into the FastAPI process at module level
    from app.workers.contract_tasks import build_processing_chain

    logger.info(f"ContractUploaded event received for {event.contract_id}, dispatching chain")
    build_processing_chain(str(event.contract_id)).delay()
