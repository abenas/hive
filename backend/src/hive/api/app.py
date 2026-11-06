"""API HTTP (FastAPI): canal web, consulta de missões, auditoria, FinOps e streaming SSE."""

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from hive.channels.telegram import TelegramChannel
from hive.config import get_settings
from hive.core.db import ArtifactRow, EventRow, LLMCallRow, MissionRow, TaskRow
from hive.core.engine import MissionError
from hive.core.events import serialize
from hive.core.models import Gate
from hive.platform import Platform

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    platform = await Platform.create(settings)
    app.state.platform = platform
    await platform.engine.recover()
    channels = []
    if settings.telegram_bot_token:
        channels.append(TelegramChannel(settings, platform))
    for ch in channels:
        await ch.start()
    yield
    for ch in channels:
        await ch.stop()
    await platform.close()


app = FastAPI(title="Hive — plataforma multi-agente", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"],
                   allow_headers=["*"])


def P(request: Request) -> Platform:
    return request.app.state.platform


def mission_dict(m: MissionRow) -> dict:
    return {
        "id": m.id, "title": m.title, "request": m.request, "channel": m.channel, "requester": m.requester,
        "status": m.status, "brief": m.brief, "plan": m.plan, "approvals": m.approvals,
        "budget_usd": m.budget_usd, "cost_usd": round(m.cost_usd, 6), "deployment_url": m.deployment_url,
        "error": m.error, "created_at": m.created_at.isoformat(), "updated_at": m.updated_at.isoformat(),
    }


def task_dict(t: TaskRow) -> dict:
    return {
        "id": t.id, "key": t.key, "agent": t.agent, "title": t.title, "story": t.story,
        "depends_on": t.depends_on, "status": t.status, "attempt": t.attempt, "result": t.result,
        "feedback": t.feedback, "cost_usd": round(t.cost_usd, 6), "tokens_in": t.tokens_in,
        "tokens_out": t.tokens_out, "models": t.models,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
    }


class MissionIn(BaseModel):
    request: str = Field(min_length=10, max_length=4000)
    requester: str = Field(default="web-user", max_length=120)


class ApprovalIn(BaseModel):
    gate: Gate
    approved: bool
    actor: str = Field(default="web-user", max_length=120)
    comment: str = Field(default="", max_length=1000)


@app.get("/api/health")
async def health(request: Request):
    s = P(request).settings
    return {"status": "ok", "env": s.env, "provider": s.llm_provider,
            "routing": {r: ":".join(s.route(r)) for r in ["orchestrator", *P(request).engine.agents]}}


@app.get("/api/agents")
async def agents(request: Request):
    s = P(request).settings
    return [{**c, "route": ":".join(s.route(c["role"]))} for c in P(request).engine.cards()]


@app.post("/api/missions", status_code=201)
async def create_mission(body: MissionIn, request: Request):
    m = await P(request).engine.submit(body.request, channel="web", requester=body.requester)
    return mission_dict(m)


@app.get("/api/missions")
async def list_missions(request: Request, limit: int = 50):
    async with P(request).sessions() as s:
        rows = (await s.scalars(select(MissionRow).order_by(MissionRow.created_at.desc()).limit(limit))).all()
    return [mission_dict(m) for m in rows]


@app.get("/api/missions/{mission_id}")
async def get_mission(mission_id: str, request: Request):
    async with P(request).sessions() as s:
        m = await s.get(MissionRow, mission_id)
        if m is None:
            raise HTTPException(404, "Missão não encontrada")
        tasks = (await s.scalars(select(TaskRow).where(TaskRow.mission_id == mission_id))).all()
        arts = (await s.scalars(select(ArtifactRow).where(ArtifactRow.mission_id == mission_id)
                                .order_by(ArtifactRow.created_at))).all()
    return {
        **mission_dict(m),
        "tasks": [task_dict(t) for t in tasks],
        "artifacts": [{"id": a.id, "task_id": a.task_id, "agent": a.agent, "name": a.name, "version": a.version,
                       "sha256": a.sha256, "size": a.size, "created_at": a.created_at.isoformat()} for a in arts],
    }


@app.get("/api/missions/{mission_id}/events")
async def mission_events(mission_id: str, request: Request):
    async with P(request).sessions() as s:
        rows = (await s.scalars(select(EventRow).where(EventRow.mission_id == mission_id)
                                .order_by(EventRow.seq))).all()
    return [serialize(r) for r in rows]


@app.get("/api/missions/{mission_id}/audit")
async def mission_audit(mission_id: str, request: Request):
    """Relatório de auditoria fim a fim: integridade da trilha e quem fez o quê."""
    p = P(request)
    chain = await p.bus.verify(mission_id)
    async with p.sessions() as s:
        m = await s.get(MissionRow, mission_id)
        if m is None:
            raise HTTPException(404, "Missão não encontrada")
        actors = (await s.execute(select(EventRow.actor, func.count()).where(EventRow.mission_id == mission_id)
                                  .group_by(EventRow.actor))).all()
        tasks = (await s.scalars(select(TaskRow).where(TaskRow.mission_id == mission_id))).all()
        arts = (await s.scalars(select(ArtifactRow).where(ArtifactRow.mission_id == mission_id))).all()
    return {
        "mission_id": mission_id, "status": m.status, "chain": chain,
        "actors": [{"actor": a, "events": n} for a, n in actors],
        "responsibility": [{"task": t.key, "title": t.title, "agent": t.agent, "attempts": t.attempt,
                            "status": t.status, "models": t.models, "cost_usd": round(t.cost_usd, 6),
                            "artifacts": [f"{a.name} v{a.version}" for a in arts if a.task_id == t.id]}
                           for t in tasks],
        "approvals": m.approvals,
        "costs": await p.engine.cost_breakdown(mission_id),
    }


@app.post("/api/missions/{mission_id}/approvals")
async def approve(mission_id: str, body: ApprovalIn, request: Request):
    try:
        m = await P(request).engine.approve(mission_id, body.gate, body.approved, body.actor, body.comment)
    except MissionError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "status": m.status}


PREVIEW_TYPES = {".html": "text/html", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json",
                 ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
# A prévia renderiza saída de LLM: sem scripts, sem rede externa, só recursos da própria missão.
PREVIEW_CSP = "default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; sandbox"


class RetryIn(BaseModel):
    actor: str = Field(default="web-user", max_length=120)
    budget_usd: float | None = Field(default=None, gt=0, le=1000)


@app.post("/api/missions/{mission_id}/retry")
async def retry(mission_id: str, body: RetryIn, request: Request):
    try:
        m = await P(request).engine.retry(mission_id, body.actor, body.budget_usd)
    except MissionError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "status": m.status}


@app.get("/api/missions/{mission_id}/preview/{name}")
async def preview(mission_id: str, name: str, request: Request):
    """Serve a versão mais recente de um artefato da missão para revisar o site antes da publicação."""
    suffix = Path(name).suffix
    if not re.fullmatch(r"[\w.-]+", name) or suffix not in PREVIEW_TYPES:
        raise HTTPException(404, "Arquivo não encontrado")
    p = P(request)
    async with p.sessions() as s:
        a = await s.scalar(select(ArtifactRow).where(ArtifactRow.mission_id == mission_id, ArtifactRow.name == name)
                           .order_by(ArtifactRow.version.desc()).limit(1))
    if a is None:
        raise HTTPException(404, "Arquivo não encontrado")
    return Response(p.engine.store.get_bytes(a.uri), media_type=PREVIEW_TYPES[suffix],
                    headers={"Content-Security-Policy": PREVIEW_CSP, "X-Content-Type-Options": "nosniff"})


@app.get("/api/artifacts/{artifact_id}", response_class=PlainTextResponse)
async def artifact(artifact_id: str, request: Request):
    p = P(request)
    async with p.sessions() as s:
        a = await s.get(ArtifactRow, artifact_id)
    if a is None:
        raise HTTPException(404, "Artefato não encontrado")
    suffix = Path(a.name).suffix
    if suffix in (".webp", ".png", ".jpg", ".jpeg"):
        return Response(p.engine.store.get_bytes(a.uri), media_type=PREVIEW_TYPES[suffix],
                        headers={"X-Content-Type-Options": "nosniff"})
    return p.engine.store.get(a.uri)


@app.get("/api/finops/summary")
async def finops_summary(request: Request):
    async with P(request).sessions() as s:
        rows = (await s.execute(select(LLMCallRow.agent, LLMCallRow.provider, LLMCallRow.model,
                                       func.count(), func.sum(LLMCallRow.input_tokens),
                                       func.sum(LLMCallRow.output_tokens), func.sum(LLMCallRow.cost_usd))
                                .group_by(LLMCallRow.agent, LLMCallRow.provider, LLMCallRow.model))).all()
        missions = (await s.execute(select(MissionRow.status, func.count(), func.sum(MissionRow.cost_usd))
                                    .group_by(MissionRow.status))).all()
    return {
        "by_agent_model": [{"agent": r[0], "provider": r[1], "model": r[2], "calls": r[3], "input_tokens": r[4],
                            "output_tokens": r[5], "cost_usd": round(r[6] or 0, 6)} for r in rows],
        "missions": [{"status": r[0], "count": r[1], "cost_usd": round(r[2] or 0, 6)} for r in missions],
        "total_usd": round(sum(r[6] or 0 for r in rows), 6),
    }


@app.get("/api/stream")
async def stream(request: Request, mission_id: str | None = None):
    bus = P(request).bus
    q = bus.subscribe()

    async def gen():
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                if mission_id is None or evt["mission_id"] == mission_id:
                    yield {"event": "hive", "data": json.dumps(evt, ensure_ascii=False, default=str)}
        finally:
            bus.unsubscribe(q)

    return EventSourceResponse(gen())


# Sites publicados localmente pelo agente de cloud (na AWS: S3 + CloudFront).
SITES_DIR = get_settings().data_dir / "sites"
SITES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/sites", StaticFiles(directory=SITES_DIR, html=True), name="sites")

# Console web (build do Vite) servido pela própria API quando existir.
WEB_DIST = Path(__file__).resolve().parents[4] / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
