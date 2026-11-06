"""Motor de missões: máquina de estados retomável que conduz o orquestrador e os especialistas.

Cada passo lê o estado do banco e avança; por isso o processo pode reiniciar a qualquer
momento (recover) e o mesmo desenho mapeia para Step Functions + SQS na AWS.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from hive.agents import orchestrator as orch
from hive.agents.base import Agent, TaskContext
from hive.config import Settings
from hive.core.db import ArtifactRow, LLMCallRow, MissionRow, TaskRow, new_id, now
from hive.core.events import EventBus
from hive.core.models import AgentResult, Brief, Gate, MissionStatus, Plan, Story, TaskStatus
from hive.core.storage import ArtifactStore
from hive.llm.providers import LLMError, LLMUsage, ProviderRegistry
from hive.llm.pricing import energy_cost
from hive.media.comfyui import ComfyUIClient, ImageError, RenderedImage

log = logging.getLogger("hive.engine")
T = TypeVar("T", bound=BaseModel)
ORCH = "orchestrator"
BINARY_SUFFIXES = (".webp", ".png", ".jpg", ".jpeg")
TERMINAL = {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.REJECTED}


class BudgetExceeded(RuntimeError):
    pass


class MissionError(RuntimeError):
    pass


class Engine:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker,
        bus: EventBus,
        providers: ProviderRegistry,
        agents: list[Agent],
        store: ArtifactStore,
    ):
        self.s = settings
        self.sessions = sessions
        self.bus = bus
        self.providers = providers
        self.agents = {a.role: a for a in agents}
        self.store = store
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._running: set[asyncio.Task] = set()
        self._comfy: ComfyUIClient | None = None

    # ------------------------------------------------------------------ API pública
    def cards(self) -> list[dict[str, Any]]:
        return [orch.CARD] + [a.card() for a in self.agents.values()]

    async def submit(
        self, request: str, *, channel: str = "web", requester: str = "anonymous",
        reply_to: str | None = None, title: str | None = None,
    ) -> MissionRow:
        m = MissionRow(
            id=new_id("msn"), title=(title or request.strip().split("\n")[0])[:120], request=request,
            channel=channel, requester=requester, reply_to=reply_to, status=MissionStatus.RECEIVED,
            approvals={}, budget_usd=self.s.mission_budget_usd, cost_usd=0.0,
        )
        async with self.sessions() as s:
            s.add(m)
            await s.commit()
        await self.bus.emit(m.id, f"user:{requester}", "mission.received", f"Missão recebida via {channel}",
                            {"request": request, "channel": channel})
        self.spawn(m.id)
        return m

    async def approve(self, mission_id: str, gate: Gate, approved: bool, actor: str, comment: str = "") -> MissionRow:
        expected = {Gate.PLAN: MissionStatus.AWAITING_PLAN_APPROVAL, Gate.DEPLOY: MissionStatus.AWAITING_DEPLOY_APPROVAL}
        async with self.sessions() as s:
            m = await s.get(MissionRow, mission_id)
            if m is None:
                raise MissionError("Missão não encontrada")
            if m.status != expected[gate]:
                raise MissionError(f"A missão não aguarda aprovação de '{gate}' (status: {m.status})")
            m.approvals = {**m.approvals, gate: {"approved": approved, "by": actor, "comment": comment,
                                                 "at": now().isoformat()}}
            if not approved:
                m.status = MissionStatus.REJECTED
            await s.commit()
        label = "plano" if gate == Gate.PLAN else "implantação"
        await self.bus.emit(mission_id, f"user:{actor}", f"gate.{'approved' if approved else 'rejected'}",
                            f"{'Aprovou' if approved else 'Rejeitou'} {label}" + (f": {comment}" if comment else ""),
                            {"gate": gate, "comment": comment})
        self.spawn(mission_id)
        return m

    async def retry(self, mission_id: str, actor: str, budget_usd: float | None = None) -> MissionRow:
        """Retoma uma missão que falhou a partir do ponto em que parou.

        O que já foi entregue e aprovado é mantido. As tarefas que falharam (ou ficaram pela metade) voltam para a
        fila com um novo orçamento de tentativas; o histórico das tentativas anteriores continua na trilha.
        """
        async with self.sessions() as s:
            m = await s.get(MissionRow, mission_id)
            if m is None:
                raise MissionError("Missão não encontrada")
            if m.status != MissionStatus.FAILED:
                raise MissionError(f"Só é possível tentar de novo uma missão que falhou (status: {m.status})")
            if budget_usd is not None:
                if budget_usd <= m.cost_usd:
                    raise MissionError(f"O novo orçamento precisa ser maior que o já gasto (US$ {m.cost_usd:.4f})")
                m.budget_usd = budget_usd
            elif m.cost_usd >= m.budget_usd:
                raise MissionError("O orçamento da missão está esgotado; informe um orçamento maior para tentar de novo")
            tasks = (await s.scalars(select(TaskRow).where(TaskRow.mission_id == mission_id))).all()
            by_key = {t.key: t for t in tasks}
            reopened = []
            for t in tasks:
                if t.status in (TaskStatus.FAILED, TaskStatus.RUNNING):
                    t.status, t.attempt = TaskStatus.PENDING, 0
                    reopened.append(t.key)
                    # Retrabalho esgotado: as dependências também ganham um novo orçamento de tentativas.
                    for dep in (by_key[k] for k in t.depends_on if k in by_key):
                        if dep.attempt >= self.s.max_rework_attempts:
                            dep.attempt = 0
            plan_ok = (m.approvals.get(Gate.PLAN) or {}).get("approved")
            m.status = (MissionStatus.EXECUTING if plan_ok
                        else MissionStatus.AWAITING_PLAN_APPROVAL if tasks
                        else MissionStatus.PLANNING if m.brief else MissionStatus.RECEIVED)
            previous_error, m.error = m.error, None
            await s.commit()
        await self.bus.emit(mission_id, f"user:{actor}", "mission.retried",
                            f"Nova tentativa solicitada; {len(reopened)} tarefa(s) reabertas"
                            + (f", orçamento ajustado para US$ {budget_usd:.2f}" if budget_usd else ""),
                            {"reopened": reopened, "previous_error": previous_error, "budget_usd": m.budget_usd})
        self.spawn(mission_id)
        return m

    def spawn(self, mission_id: str) -> None:
        task = asyncio.create_task(self.advance(mission_id))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def recover(self) -> None:
        """Retoma missões interrompidas por reinício do processo."""
        async with self.sessions() as s:
            for t in (await s.scalars(select(TaskRow).where(TaskRow.status == TaskStatus.RUNNING))).all():
                t.status = TaskStatus.PENDING
            missions = (await s.scalars(select(MissionRow.id).where(MissionRow.status.not_in(list(TERMINAL))))).all()
            await s.commit()
        for mid in missions:
            self.spawn(mid)

    async def drain(self) -> None:
        while self._running:
            await asyncio.gather(*list(self._running), return_exceptions=True)

    # ------------------------------------------------------------- máquina de estados
    async def advance(self, mission_id: str) -> None:
        async with self._locks[mission_id]:
            try:
                while await self._step(mission_id):
                    pass
            except (BudgetExceeded, LLMError, MissionError) as e:
                await self._fail(mission_id, str(e))
            except Exception as e:  # noqa: BLE001 — falha inesperada também fica auditada
                log.exception("Falha na missão %s", mission_id)
                await self._fail(mission_id, f"Erro interno: {e}")

    async def _step(self, mission_id: str) -> bool:
        m = await self._mission(mission_id)
        match m.status:
            case MissionStatus.RECEIVED | MissionStatus.INTERPRETING:
                await self._interpret(m)
            case MissionStatus.PLANNING:
                await self._plan(m)
            case MissionStatus.AWAITING_PLAN_APPROVAL:
                return await self._gate(m, Gate.PLAN)
            case MissionStatus.AWAITING_DEPLOY_APPROVAL:
                return await self._gate(m, Gate.DEPLOY)
            case MissionStatus.EXECUTING:
                return await self._execute(m)
            case _:
                return False
        return True

    async def _gate(self, m: MissionRow, gate: Gate) -> bool:
        decision = m.approvals.get(gate)
        if decision is None and self.s.auto_approve:
            await self.approve(m.id, gate, True, "auto-approve", "HIVE_AUTO_APPROVE habilitado")
            return False  # approve() agenda o próximo avanço
        if decision and decision["approved"]:
            await self._set_status(m.id, MissionStatus.EXECUTING)
            return True
        return False

    async def _interpret(self, m: MissionRow) -> None:
        await self._set_status(m.id, MissionStatus.INTERPRETING)
        await self.bus.emit(m.id, ORCH, "orchestrator.interpreting", "Interpretando o pedido e montando o briefing")
        brief = await self._think(m.id, None, ORCH, Brief, orch.SYSTEM, orch.interpret_prompt(m.request),
                                  lambda: orch.heuristic_brief(m.request), "medium")
        async with self.sessions() as s:
            row = await s.get(MissionRow, m.id)
            row.brief = brief.model_dump()
            row.title = f"Site para {brief.company_name}"
            row.status = MissionStatus.PLANNING
            await s.commit()
        await self.bus.emit(m.id, ORCH, "mission.brief", f"Briefing: {brief.company_name} ({brief.segment})",
                            brief.model_dump())

    async def _plan(self, m: MissionRow) -> None:
        brief = Brief.model_validate(m.brief)
        reference = orch.template_plan(brief)
        roles = set(self.agents)
        await self.bus.emit(m.id, ORCH, "orchestrator.planning", "Planejando tarefas e histórias (DoR)")
        plan = await self._think(m.id, None, ORCH, Plan, orch.SYSTEM,
                                 orch.plan_prompt(brief, [a.card() for a in self.agents.values()], reference),
                                 lambda: reference, "high")
        if problems := orch.validate_plan(plan, roles):
            await self.bus.emit(m.id, ORCH, "plan.corrected",
                                "Plano gerado violou regras de DoR/DAG; usando plano de referência",
                                {"problems": problems})
            plan = reference
        async with self.sessions() as s:
            row = await s.get(MissionRow, m.id)
            row.plan = plan.model_dump()
            for pt in plan.tasks:
                s.add(TaskRow(id=new_id("tsk"), mission_id=m.id, key=pt.key, agent=pt.agent,
                              title=pt.story.title, story=pt.story.model_dump(), depends_on=pt.depends_on,
                              status=TaskStatus.PENDING, attempt=0, cost_usd=0.0, tokens_in=0, tokens_out=0,
                              models=[]))
            row.status = MissionStatus.AWAITING_PLAN_APPROVAL
            await s.commit()
        await self.bus.emit(m.id, ORCH, "plan.created", plan.summary,
                            {"tasks": [{"key": t.key, "agent": t.agent, "title": t.story.title,
                                        "depends_on": t.depends_on} for t in plan.tasks]})
        await self.bus.emit(m.id, ORCH, "plan.dor_validated",
                            "DoR validado: todo insumo exigido tem um produtor upstream", {"tasks": len(plan.tasks)})
        await self.bus.emit(m.id, "system", "gate.awaiting", "Aguardando aprovação do plano", {"gate": Gate.PLAN})

    async def _execute(self, m: MissionRow) -> bool:
        tasks = await self._tasks(m.id)
        if failed := [t for t in tasks if t.status == TaskStatus.FAILED]:
            raise MissionError(f"Tarefa '{failed[0].key}' falhou")
        if all(t.status == TaskStatus.DONE for t in tasks):
            await self._complete(m, tasks)
            return False
        done = {t.key for t in tasks if t.status == TaskStatus.DONE}
        ready = [t for t in tasks if t.status == TaskStatus.PENDING and set(t.depends_on) <= done]
        if not ready:
            raise MissionError("Nenhuma tarefa pronta e a missão não terminou (dependências inconsistentes)")
        deploy_ok = (m.approvals.get(Gate.DEPLOY) or {}).get("approved")
        gated = [t for t in ready if t.agent == "cloud_engineer" and not deploy_ok]
        runnable = [t for t in ready if t not in gated]
        if not runnable:
            await self._set_status(m.id, MissionStatus.AWAITING_DEPLOY_APPROVAL)
            await self.bus.emit(m.id, "system", "gate.awaiting", "QA aprovado. Aguardando autorização para implantar",
                                {"gate": Gate.DEPLOY})
            return True
        # Tarefas irmãs terminam mesmo se uma falhar: o trabalho delas fica salvo para uma nova tentativa
        # e nenhuma segue rodando órfã depois que a missão é marcada como falha.
        results = await asyncio.gather(*(self._run_task(m, t) for t in runnable), return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                raise r
        return True

    async def _run_task(self, m: MissionRow, t: TaskRow) -> None:
        agent = self.agents[t.agent]
        story = Story.model_validate(t.story)
        inputs = await self._latest_artifacts(m.id)
        if missing := [n for n in story.inputs_required if n not in inputs]:
            await self._finish_task(t.id, TaskStatus.FAILED, None)
            await self.bus.emit(m.id, ORCH, "task.dor_failed", f"DoR não atendido para '{t.title}'",
                                {"missing": missing}, task_id=t.id)
            return
        await self.bus.emit(m.id, ORCH, "task.delegated", f"Delegado a {agent.name} ({agent.title}): {t.title}",
                            {"agent": t.agent, "story": t.story, "inputs": story.inputs_required,
                             "playbooks": [p.ref for p in agent.playbooks()],
                             "attempt": t.attempt + 1, "feedback": t.feedback}, task_id=t.id)
        async with self.sessions() as s:
            row = await s.get(TaskRow, t.id)
            row.status, row.attempt, row.started_at = TaskStatus.RUNNING, row.attempt + 1, now()
            attempt, feedback = row.attempt, row.feedback
            await s.commit()
        await self.bus.emit(m.id, t.agent, "task.started", f"{agent.name} iniciou: {t.title}", task_id=t.id)

        async def think(schema, system, prompt, mock, effort: str = agent.effort):
            return await self._think(m.id, t.id, t.agent, schema, system, prompt, mock, effort)

        async def emit(type_: str, message: str, data: dict | None = None):
            await self.bus.emit(m.id, t.agent, type_, message, data, task_id=t.id)

        ctx = TaskContext(
            mission_id=m.id, task_id=t.id, request=m.request, brief=Brief.model_validate(m.brief), story=story,
            inputs={n: inputs[n] for n in story.inputs_required}, attempt=attempt, feedback=feedback,
            settings=self.s, services=self, think=think, emit=emit,
            extra={"provider": self.s.route(t.agent)[0]},
        )
        try:
            result = await agent.run(ctx)
        except (LLMError, BudgetExceeded) as e:
            await self._finish_task(t.id, TaskStatus.FAILED, None)
            await self.bus.emit(m.id, t.agent, "task.failed", f"{agent.name} falhou: {e}", task_id=t.id)
            raise
        await self._save_artifacts(m.id, t, result)
        await self._finish_task(t.id, TaskStatus.DONE, result)
        await self.bus.emit(m.id, t.agent, "task.completed", result.summary,
                            {"passed": result.passed, "evidence": [e.model_dump() for e in result.evidence],
                             "artifacts": list(result.artifacts)}, task_id=t.id)
        if not result.passed:
            await self._rework(m, t, result)

    async def _rework(self, m: MissionRow, verifier: TaskRow, result: AgentResult) -> None:
        """Verificação reprovada: o orquestrador devolve o trabalho a quem produziu os artefatos com
        defeito (ou, sem essa indicação, às dependências diretas do verificador)."""
        feedback = "\n".join(f"- {f}" for f in result.data.get("failed", [])) or result.summary
        blamed = result.data.get("rework_artifacts") or []
        async with self.sessions() as s:
            if blamed:
                producers = select(ArtifactRow.task_id).where(ArtifactRow.mission_id == m.id,
                                                              ArtifactRow.name.in_(blamed))
                deps = (await s.scalars(select(TaskRow).where(TaskRow.id.in_(producers)))).all()
            else:
                deps = (await s.scalars(select(TaskRow).where(TaskRow.mission_id == m.id,
                                                              TaskRow.key.in_(verifier.depends_on)))).all()
            if any(d.attempt >= self.s.max_rework_attempts for d in deps):
                v = await s.get(TaskRow, verifier.id)
                v.status = TaskStatus.FAILED
                await s.commit()
                await self.bus.emit(m.id, ORCH, "task.rework_exhausted",
                                    f"Limite de {self.s.max_rework_attempts} tentativas atingido", task_id=verifier.id)
                return
            for d in deps:
                d.status, d.feedback = TaskStatus.PENDING, feedback
            # Cascata: o que já foi feito em cima do trabalho reaberto ficou desatualizado e roda de novo
            # (ex.: conteúdo refeito invalida a verificação de fatos e as ilustrações feitas sobre ele).
            tasks = (await s.scalars(select(TaskRow).where(TaskRow.mission_id == m.id))).all()
            reopened = {d.key for d in deps} | {verifier.key}
            cascade: list[str] = []
            changed = True
            while changed:
                changed = False
                for t in tasks:
                    if t.key not in reopened and t.status == TaskStatus.DONE and reopened & set(t.depends_on):
                        t.status = TaskStatus.PENDING
                        reopened.add(t.key)
                        cascade.append(t.key)
                        changed = True
            v = await s.get(TaskRow, verifier.id)
            v.status = TaskStatus.PENDING
            await s.commit()
        names = ", ".join(self.agents[d.agent].name for d in deps)
        await self.bus.emit(m.id, ORCH, "task.rework",
                            f"{self.agents[verifier.agent].name} reprovou; devolvendo para {names} com "
                            f"{feedback.count(chr(10)) + 1} apontamento(s)"
                            + (f"; {len(cascade)} etapa(s) dependente(s) refeitas em seguida" if cascade else ""),
                            {"feedback": feedback, "to": [d.key for d in deps], "cascade": cascade,
                             "blamed_artifacts": blamed},
                            task_id=verifier.id)

    async def _complete(self, m: MissionRow, tasks: list[TaskRow]) -> None:
        deploy = next((t for t in tasks if t.agent == "cloud_engineer"), None)
        url = (deploy.result or {}).get("data", {}).get("url") if deploy else None
        async with self.sessions() as s:
            row = await s.get(MissionRow, m.id)
            row.status, row.deployment_url = MissionStatus.COMPLETED, url
            cost = row.cost_usd
            await s.commit()
        agents = sorted({t.agent for t in tasks})
        await self.bus.emit(m.id, ORCH, "mission.completed",
                            f"Missão concluída por {len(agents) + 1} agentes. Custo: US$ {cost:.4f}",
                            {"url": url, "agents": [ORCH, *agents], "cost_usd": cost})

    async def _fail(self, mission_id: str, reason: str) -> None:
        async with self.sessions() as s:
            row = await s.get(MissionRow, mission_id)
            if row.status in TERMINAL:
                return
            row.status, row.error = MissionStatus.FAILED, reason
            await s.commit()
        await self.bus.emit(mission_id, ORCH, "mission.failed", reason)

    # --------------------------------------------------------------------- LLM + FinOps
    async def _think(self, mission_id: str, task_id: str | None, role: str, schema: type[T], system: str,
                     prompt: str, mock: Callable[[], T], effort: str) -> T:
        async with self.sessions() as s:
            m = await s.get(MissionRow, mission_id)
            if m.cost_usd >= m.budget_usd:
                raise BudgetExceeded(f"Orçamento da missão esgotado (US$ {m.cost_usd:.4f} de US$ {m.budget_usd:.2f})")
        provider_name, model = self.s.route(role)
        out, u = await self.providers.get(provider_name).structured(
            model=model, system=system, prompt=prompt, schema=schema, effort=effort, mock=mock)
        await self._record_usage(mission_id, task_id, role, u, schema.__name__)
        return out

    async def _record_usage(self, mission_id: str, task_id: str | None, role: str, u: LLMUsage, label: str) -> None:
        """Contabiliza uma chamada de modelo (texto ou imagem) na missão, na tarefa e na trilha."""
        async with self.sessions() as s:
            s.add(LLMCallRow(id=new_id("llm"), mission_id=mission_id, task_id=task_id, agent=role,
                             provider=u.provider, model=u.model, input_tokens=u.input_tokens,
                             output_tokens=u.output_tokens, cache_read_tokens=u.cache_read_tokens,
                             cost_usd=u.cost_usd, simulated=u.simulated, latency_ms=u.latency_ms))
            m = await s.get(MissionRow, mission_id)
            m.cost_usd += u.cost_usd
            if task_id:
                t = await s.get(TaskRow, task_id)
                t.cost_usd += u.cost_usd
                t.tokens_in += u.input_tokens
                t.tokens_out += u.output_tokens
                t.models = sorted({*t.models, f"{u.provider}:{u.model}"})
            await s.commit()
        await self.bus.emit(mission_id, role, "llm.call",
                            f"{u.provider}:{u.model} · {u.input_tokens}→{u.output_tokens} tokens · "
                            f"US$ {u.cost_usd:.5f}{' (simulado)' if u.simulated else ''}",
                            {"provider": u.provider, "model": u.model, "input_tokens": u.input_tokens,
                             "output_tokens": u.output_tokens, "cost_usd": u.cost_usd, "latency_ms": u.latency_ms,
                             "simulated": u.simulated, "queue_ms": u.queue_ms, "schema": label},
                            task_id=task_id)

    async def render_images(self, mission_id: str, task_id: str, role: str,
                            jobs: list[tuple[str, str, int]]) -> list[RenderedImage | ImageError]:
        """Gera um lote de imagens no ComfyUI com uso exclusivo da GPU.

        Espera as chamadas de LLM em andamento terminarem, descarrega o LLM da VRAM, gera tudo e libera a
        memória do ComfyUI no fim. Cada imagem entra no FinOps (energia) e na trilha de auditoria.
        """
        comfy = self._comfy = self._comfy or ComfyUIClient(self.s)
        if not await comfy.available():
            raise ImageError(f"ComfyUI indisponível em {self.s.comfyui_url}")
        results: list[RenderedImage | ImageError] = []
        waited = datetime.now(UTC)
        async with self.providers.gpu.exclusive():
            wait_s = (datetime.now(UTC) - waited).total_seconds()
            unloaded: list[str] = []
            if self.s.gpu_shared and any(self.s.route(r)[0] == "ollama" for r in [ORCH, *self.agents]):
                unloaded = await self.providers.get("ollama").unload()  # type: ignore[union-attr]
            await self.bus.emit(mission_id, role, "gpu.exclusive",
                                f"GPU reservada para {len(jobs)} imagem(ns) após {wait_s:.0f} s de espera"
                                + (f"; LLM descarregado ({', '.join(unloaded)})" if unloaded else ""),
                                {"wait_s": wait_s, "unloaded": unloaded}, task_id=task_id)
            try:
                for prompt, negative, seed in jobs:
                    try:
                        img = await comfy.render(prompt, negative, seed)
                    except ImageError as e:
                        results.append(e)
                        continue
                    results.append(img)
                    cost = energy_cost(img.seconds, self.s.local_gpu_watts, self.s.energy_price_per_kwh_usd)
                    await self._record_usage(mission_id, task_id, role, LLMUsage(
                        provider="comfyui", model=self.s.comfyui_checkpoint.removesuffix(".safetensors"),
                        input_tokens=0, output_tokens=0, cache_read_tokens=0, cost_usd=cost,
                        latency_ms=int(img.seconds * 1000)), "Image")
            finally:
                await comfy.free()
                await self.bus.emit(mission_id, role, "gpu.released", "GPU liberada para o LLM", task_id=task_id)
        return results

    async def artifact_bytes(self, mission_id: str, name: str) -> bytes:
        async with self.sessions() as s:
            row = await s.scalar(select(ArtifactRow).where(ArtifactRow.mission_id == mission_id, ArtifactRow.name == name)
                                 .order_by(ArtifactRow.version.desc()).limit(1))
        if row is None:
            raise MissionError(f"Artefato {name} não encontrado")
        return self.store.get_bytes(row.uri)

    # ------------------------------------------------------- Services (expostos aos agentes)
    async def cost_breakdown(self, mission_id: str) -> dict[str, Any]:
        async with self.sessions() as s:
            m = await s.get(MissionRow, mission_id)
            cols = (func.count(), func.sum(LLMCallRow.input_tokens), func.sum(LLMCallRow.output_tokens),
                    func.sum(LLMCallRow.cost_usd))
            by_agent = (await s.execute(select(LLMCallRow.agent, *cols).where(LLMCallRow.mission_id == mission_id)
                                        .group_by(LLMCallRow.agent))).all()
            by_model = (await s.execute(select(LLMCallRow.provider, LLMCallRow.model, *cols)
                                        .where(LLMCallRow.mission_id == mission_id)
                                        .group_by(LLMCallRow.provider, LLMCallRow.model))).all()
            simulated = bool(await s.scalar(select(func.max(LLMCallRow.simulated))
                                            .where(LLMCallRow.mission_id == mission_id)))
        total = sum(r[4] or 0 for r in by_agent)
        return {
            "total_usd": round(total, 6), "budget_usd": m.budget_usd,
            "budget_used_pct": round(100 * total / m.budget_usd, 1) if m.budget_usd else 0,
            "calls": sum(r[1] for r in by_agent), "input_tokens": sum(r[2] or 0 for r in by_agent),
            "output_tokens": sum(r[3] or 0 for r in by_agent), "simulated": simulated,
            "by_agent": sorted(
                [{"agent": r[0], "calls": r[1], "input_tokens": r[2] or 0, "output_tokens": r[3] or 0,
                  "cost_usd": round(r[4] or 0, 6), "share": round(100 * (r[4] or 0) / total, 1) if total else 0}
                 for r in by_agent], key=lambda a: -a["cost_usd"]),
            "by_model": [{"provider": r[0], "model": r[1], "calls": r[2], "cost_usd": round(r[5] or 0, 6)}
                         for r in by_model],
        }

    def site_dir(self, mission_id: str) -> Path:
        return (self.s.data_dir / "sites" / mission_id).resolve()

    def site_url(self, mission_id: str) -> str:
        return f"{self.s.public_base_url}/sites/{mission_id}/"

    # ------------------------------------------------------------------- persistência
    async def _mission(self, mission_id: str) -> MissionRow:
        async with self.sessions() as s:
            m = await s.get(MissionRow, mission_id)
        if m is None:
            raise MissionError("Missão não encontrada")
        return m

    async def _tasks(self, mission_id: str) -> list[TaskRow]:
        async with self.sessions() as s:
            return list((await s.scalars(select(TaskRow).where(TaskRow.mission_id == mission_id))).all())

    async def _set_status(self, mission_id: str, status: MissionStatus) -> None:
        async with self.sessions() as s:
            (await s.get(MissionRow, mission_id)).status = status
            await s.commit()

    async def _finish_task(self, task_id: str, status: TaskStatus, result: AgentResult | None) -> None:
        async with self.sessions() as s:
            t = await s.get(TaskRow, task_id)
            t.status, t.finished_at = status, datetime.now(UTC)
            if result is not None:
                t.result = result.model_dump(exclude={"artifacts"})
            await s.commit()

    async def _latest_artifacts(self, mission_id: str) -> dict[str, str]:
        async with self.sessions() as s:
            rows = (await s.scalars(select(ArtifactRow).where(ArtifactRow.mission_id == mission_id)
                                    .order_by(ArtifactRow.version))).all()
        # Só artefatos de texto viram insumo de prompt; binários (imagens) são lidos sob demanda.
        return {r.name: self.store.get(r.uri) for r in rows if not r.name.endswith(BINARY_SUFFIXES)}

    async def _save_artifacts(self, mission_id: str, t: TaskRow, result: AgentResult) -> None:
        for name, content in result.artifacts.items():
            async with self.sessions() as s:
                version = 1 + (await s.scalar(select(func.count()).where(
                    ArtifactRow.mission_id == mission_id, ArtifactRow.name == name)) or 0)
                uri, digest, size = self.store.put(mission_id, name, version, content)
                art = ArtifactRow(id=new_id("art"), mission_id=mission_id, task_id=t.id, agent=t.agent,
                                  name=name, version=version, uri=uri, sha256=digest, size=size)
                s.add(art)
                await s.commit()
            await self.bus.emit(mission_id, t.agent, "artifact.created", f"{name} v{version} ({size} bytes)",
                                {"artifact_id": art.id, "name": name, "version": version, "sha256": digest,
                                 "size": size}, task_id=t.id)
