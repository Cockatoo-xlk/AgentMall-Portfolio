from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agentmall.infra.config import Settings


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def database(settings: Settings):
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        connect_args={
            "application_name": f"agentmall:{settings.db_schema}",
            "options": (
                f"-csearch_path={settings.db_schema},extensions "
                "-clock_timeout=3000 -cstatement_timeout=10000"
            ),
        },
        pool_pre_ping=True,
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)
