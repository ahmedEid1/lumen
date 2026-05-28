"""SQLAlchemy declarative base + async engine."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.ids import new_id

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IdMixin:
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            echo=s.database_echo,
            pool_pre_ping=True,
            pool_size=s.database_pool_size,
            max_overflow=s.database_max_overflow,
            future=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def make_worker_engine() -> AsyncEngine:
    """A fresh ``NullPool`` engine scoped to a single Celery prefork task.

    Worker task bodies run under a new ``asyncio.run()`` event loop on
    every invocation (ADR-0017). The module-level pooled engine
    (:func:`get_engine`) caches asyncpg connections bound to whichever
    loop first opened them, so reusing it on a later task's loop raised
    ``RuntimeError: ... got Future ... attached to a different loop`` /
    ``Event loop is closed`` — observed crashing every tutor turn + the
    sweep beat in prod once ``feature_tutor_streaming`` was enabled. A
    ``NullPool`` engine created and disposed inside the task's own loop
    holds no connection across the loop boundary, so each task is
    self-contained. Disposal is the caller's job — prefer
    :func:`worker_session_scope`, which does it for you.
    """
    s = get_settings()
    return create_async_engine(
        s.database_url,
        echo=s.database_echo,
        poolclass=NullPool,
        future=True,
    )


@asynccontextmanager
async def worker_session_scope() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Per-task async sessionmaker bound to a fresh :func:`make_worker_engine`.

    Yields a sessionmaker (so a task can open several sequential
    sessions on its own loop) and disposes the engine on exit. This is
    the worker-side analogue of :func:`get_sessionmaker`; see
    :func:`make_worker_engine` for why workers can't share the pooled
    engine across ``asyncio.run()`` loops.
    """
    engine = make_worker_engine()
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()
