from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings


def create_engine(settings: Settings):
    """Create async SQLAlchemy engine from settings."""
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_size=5,
        max_overflow=10,
    )


def create_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    """Create async session factory bound to the engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
