from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine = None
_async_session = None


async def init_db(database_url: str) -> None:
    global _engine, _async_session
    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    _async_session = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )


async def close_db() -> None:
    global _engine
    if _engine:
        await _engine.dispose()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _async_session is None:
        raise RuntimeError("Database not initialized — call init_db first")
    return _async_session


async def get_session() -> AsyncSession:
    if _async_session is None:
        raise RuntimeError("Database not initialized — call init_db first")
    async with _async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
