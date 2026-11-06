"""Contrato dos canais (Telegram, WhatsApp, Slack, Teams...).

Um canal faz duas coisas: (1) converte mensagens recebidas em `engine.submit/approve`
e (2) assina o barramento de eventos para notificar o solicitante dos marcos da missão.
"""

import asyncio
import logging
from abc import ABC, abstractmethod

from hive.core.db import MissionRow

log = logging.getLogger("hive.channels")

# Eventos que viram notificação para o solicitante (o restante fica só no console/auditoria).
NOTIFY = {"mission.brief", "gate.awaiting", "task.completed", "task.rework", "mission.completed", "mission.failed"}


class Channel(ABC):
    name: str

    def __init__(self, settings, platform):
        self.settings = settings
        self.platform = platform
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._receive_loop()), asyncio.create_task(self._notify_loop())]
        log.info("Canal %s iniciado", self.name)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    @abstractmethod
    async def _receive_loop(self) -> None: ...

    @abstractmethod
    async def notify(self, mission: MissionRow, event: dict) -> None: ...

    async def _notify_loop(self) -> None:
        q = self.platform.bus.subscribe()
        try:
            while True:
                event = await q.get()
                if event["type"] not in NOTIFY:
                    continue
                async with self.platform.sessions() as s:
                    m = await s.get(MissionRow, event["mission_id"])
                if m and m.channel == self.name and m.reply_to:
                    try:
                        await self.notify(m, event)
                    except Exception:  # noqa: BLE001 — falha de notificação não derruba o canal
                        log.exception("Falha ao notificar via %s", self.name)
        finally:
            self.platform.bus.unsubscribe(q)

    def console_url(self, mission_id: str) -> str:
        return f"{self.settings.public_base_url}/#/missions/{mission_id}"
