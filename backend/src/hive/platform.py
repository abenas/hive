"""Composition root: monta as dependências da plataforma a partir das configurações."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from hive.agents.specialists import SPECIALISTS
from hive.config import Settings
from hive.core.db import init_db, make_engine, make_sessionmaker
from hive.core.engine import Engine
from hive.core.events import EventBus
from hive.core.storage import LocalArtifactStore
from hive.llm.providers import ProviderRegistry


@dataclass
class Platform:
    settings: Settings
    db: AsyncEngine
    sessions: async_sessionmaker
    bus: EventBus
    engine: Engine

    @classmethod
    async def create(cls, settings: Settings) -> "Platform":
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db = make_engine(settings.db_url)
        await init_db(db)
        sessions = make_sessionmaker(db)
        bus = EventBus(sessions)
        engine = Engine(settings, sessions, bus, ProviderRegistry(settings), SPECIALISTS,
                        LocalArtifactStore(settings.data_dir / "artifacts"))
        return cls(settings, db, sessions, bus, engine)

    async def close(self) -> None:
        await self.db.dispose()
