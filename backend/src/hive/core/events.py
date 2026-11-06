"""Barramento de eventos: persiste na trilha de auditoria e publica para assinantes (SSE, canais).

Local: pub/sub em memória. AWS: o mesmo contrato pode ser servido por EventBridge/SNS.
"""

import asyncio
import hashlib
import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from hive.core.db import EventRow, new_id, now

GENESIS = "0" * 64


def event_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{prev_hash}|{body}".encode()).hexdigest()


def hashable(row: EventRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "mission_id": row.mission_id,
        "task_id": row.task_id,
        "actor": row.actor,
        "type": row.type,
        "message": row.message,
        "data": row.data,
        "ts": row.ts,
    }


def serialize(row: EventRow) -> dict[str, Any]:
    return {**hashable(row), "seq": row.seq, "hash": row.hash, "prev_hash": row.prev_hash}


class EventBus:
    def __init__(self, sessions: async_sessionmaker):
        self._sessions = sessions
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._subscribers: set[asyncio.Queue] = set()

    async def emit(
        self,
        mission_id: str,
        actor: str,
        type: str,
        message: str,
        data: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        async with self._locks[mission_id], self._sessions() as s:
            last = await s.scalar(
                select(EventRow.hash)
                .where(EventRow.mission_id == mission_id)
                .order_by(EventRow.seq.desc())
                .limit(1)
            )
            row = EventRow(
                id=new_id("evt"),
                mission_id=mission_id,
                task_id=task_id,
                actor=actor,
                type=type,
                message=message,
                data=data or {},
                ts=now().isoformat(),
                prev_hash=last or GENESIS,
            )
            row.hash = event_hash(row.prev_hash, hashable(row))
            s.add(row)
            await s.commit()
            event = serialize(row)
        for q in list(self._subscribers):
            q.put_nowait(event)
        return event

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def verify(self, mission_id: str) -> dict[str, Any]:
        """Recalcula a cadeia de hashes; qualquer edição/remoção de evento é detectada."""
        async with self._sessions() as s:
            rows = (
                await s.scalars(
                    select(EventRow).where(EventRow.mission_id == mission_id).order_by(EventRow.seq)
                )
            ).all()
        prev = GENESIS
        for row in rows:
            if row.prev_hash != prev or event_hash(prev, hashable(row)) != row.hash:
                return {"valid": False, "events": len(rows), "broken_at": row.id}
            prev = row.hash
        return {"valid": True, "events": len(rows), "head": prev}
