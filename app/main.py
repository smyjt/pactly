from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.config import Settings
from app.database import create_engine, create_session_factory


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator:
    """Manage application lifecycle: set up DB engine on startup, dispose on shutdown."""
    # Startup
    settings: Settings = application.state.settings
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    application.state.engine = engine
    application.state.session_factory = session_factory

    yield

    # Shutdown
    await application.state.engine.dispose()


def create_app() -> FastAPI:
    """Application factory — creates and configures the FastAPI app."""
    settings = Settings()

    application = FastAPI(
        title="Pactly",
        description="AI Contract Intelligence Engine",
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    application.state.settings = settings

    @application.get("/health", tags=["system"])
    async def health_check():
        """Liveness probe — returns 200 if the app is running."""
        return {"status": "healthy", "version": "0.1.0"}

    return application


app = create_app()
