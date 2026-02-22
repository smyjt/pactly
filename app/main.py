import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import create_engine, create_session_factory
from app.middleware import RequestIDLogFilter, RequestIDMiddleware


def configure_logging(log_level: str) -> None:
    """Set up logging with request ID injected into every log line."""
    log_filter = RequestIDLogFilter()
    formatter = logging.Formatter(
        "%(asctime)s [%(request_id)s] %(levelname)s %(name)s: %(message)s"
    )

    # Replace existing handlers on the root logger rather than using basicConfig
    # (basicConfig is a no-op if handlers are already set, which uvicorn does at startup)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(log_filter)
    root_logger.addHandler(handler)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator:
    """Manage application lifecycle: set up DB engine on startup, dispose on shutdown."""
    settings: Settings = application.state.settings
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    application.state.engine = engine
    application.state.session_factory = session_factory

    from app.events.bus import event_bus
    from app.events.contract_events import ContractUploaded
    from app.events.handlers.contract_handlers import on_contract_uploaded
    event_bus.register(ContractUploaded, on_contract_uploaded)

    yield

    await application.state.engine.dispose()


def create_app() -> FastAPI:
    """Application factory."""
    settings = Settings()

    application = FastAPI(
        title="Pactly",
        description="AI Contract Intelligence Engine",
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    application.state.settings = settings

    configure_logging(settings.LOG_LEVEL)
    application.add_middleware(RequestIDMiddleware)

    # Database session dependency — injected into every route that needs DB access
    async def get_session() -> AsyncGenerator[AsyncSession, None]:
        async with application.state.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Register routers
    from app.routers.contracts import router as contracts_router, get_contract_service
    from app.repositories.contract_repo import ContractRepository
    from app.services.contract_service import ContractService
    from fastapi import Depends

    # Override the session dependency so the router gets a real DB session
    async def get_contract_service_with_session(
        session: AsyncSession = Depends(get_session),
    ) -> ContractService:
        return ContractService(ContractRepository(session))

    application.include_router(contracts_router, prefix="/api/v1")
    application.dependency_overrides[get_contract_service] = get_contract_service_with_session

    @application.get("/health", tags=["Health Check"])
    async def health_check():
        return {"status": "healthy", "version": "0.1.0"}

    return application


app = create_app()
