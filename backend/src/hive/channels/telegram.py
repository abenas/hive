"""Canal Telegram via long polling (sem webhook público — ideal para rodar local).

Na AWS, troque o polling por webhook (API Gateway + Lambda) mantendo o mesmo `notify`.
"""

import asyncio
import logging

import httpx

from hive.channels.base import Channel
from hive.core.db import MissionRow
from hive.core.engine import MissionError
from hive.core.models import Gate

log = logging.getLogger("hive.telegram")

HELP = (
    "Olá! Eu sou o Atlas, orquestrador da Hive 🐝\n\n"
    "Envie uma missão em texto livre, por exemplo:\n"
    "“Crie um site para a empresa Sabor da Vila, do segmento de padaria artesanal, "
    "apresente produtos, história e depoimentos.”\n\n"
    "Comandos: /status <id> · /ajuda"
)


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, settings, platform):
        super().__init__(settings, platform)
        self.api = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{settings.telegram_bot_token}/", timeout=40
        )

    async def stop(self) -> None:
        await super().stop()
        await self.api.aclose()

    async def send(self, chat_id: str, text: str, buttons: list[list[dict]] | None = None) -> None:
        payload: dict = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        r = await self.api.post("sendMessage", json=payload)
        if r.status_code != 200:
            log.warning("Telegram sendMessage %s: %s", r.status_code, r.text[:200])

    async def _receive_loop(self) -> None:
        offset = 0
        while True:
            try:
                r = await self.api.get("getUpdates", params={"timeout": 30, "offset": offset})
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    await self._handle(upd)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Erro no polling do Telegram")
                await asyncio.sleep(5)

    async def _handle(self, upd: dict) -> None:
        engine = self.platform.engine
        if cb := upd.get("callback_query"):
            action, mission_id, gate = cb["data"].split(":")
            chat_id = str(cb["message"]["chat"]["id"])
            user = cb["from"].get("username") or str(cb["from"]["id"])
            try:
                await engine.approve(mission_id, Gate(gate), action == "ok", f"telegram:{user}")
            except MissionError as e:
                await self.send(chat_id, f"⚠️ {e}")
            await self.api.post("answerCallbackQuery", json={"callback_query_id": cb["id"]})
            return
        msg = upd.get("message") or {}
        text = (msg.get("text") or "").strip()
        if not text:
            return
        chat_id = str(msg["chat"]["id"])
        user = msg["from"].get("username") or str(msg["from"]["id"])
        if text.startswith(("/start", "/ajuda", "/help")):
            await self.send(chat_id, HELP)
        elif text.startswith("/status"):
            mission_id = text.removeprefix("/status").strip()
            async with self.platform.sessions() as s:
                m = await s.get(MissionRow, mission_id)
            await self.send(chat_id, f"{m.title}: {m.status} · US$ {m.cost_usd:.4f}\n{self.console_url(m.id)}"
                            if m else "Missão não encontrada.")
        elif len(text) < 15:
            await self.send(chat_id, "Descreva a missão com um pouco mais de detalhe 🙂")
        else:
            m = await engine.submit(text, channel=self.name, requester=f"telegram:{user}", reply_to=chat_id)
            await self.send(chat_id, f"🐝 Missão {m.id} recebida! Acompanhe em tempo real:\n{self.console_url(m.id)}")

    async def notify(self, m: MissionRow, e: dict) -> None:
        data, chat = e.get("data") or {}, m.reply_to
        match e["type"]:
            case "mission.brief":
                await self.send(chat, f"🧭 Atlas entendeu: site para {data['company_name']} ({data['segment']}).\n"
                                f"Seções: {', '.join(data['sections'])}")
            case "gate.awaiting":
                gate = data["gate"]
                if gate == Gate.PLAN:
                    tasks = (m.plan or {}).get("tasks", [])
                    lines = "\n".join(f"• {t['story']['title']} → {t['agent']}" for t in tasks)
                    text = f"📋 Plano pronto ({len(tasks)} tarefas):\n{lines}\n\nAprova?"
                else:
                    text = "🚀 QA aprovado. Posso publicar o site?"
                await self.send(chat, text, [[{"text": "✅ Aprovar", "callback_data": f"ok:{m.id}:{gate}"},
                                              {"text": "❌ Rejeitar", "callback_data": f"no:{m.id}:{gate}"}]])
            case "task.completed":
                ok = "✅" if data.get("passed", True) else "❌"
                await self.send(chat, f"{ok} [{e['actor']}] {e['message']}")
            case "task.rework":
                await self.send(chat, f"🔁 {e['message']}")
            case "mission.completed":
                await self.send(chat, f"🎉 {e['message']}\n🌐 {data.get('url')}\n🔎 Auditoria: {self.console_url(m.id)}")
            case "mission.failed":
                await self.send(chat, f"⛔ Missão falhou: {e['message']}")
