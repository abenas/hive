import asyncio

import pytest
from sqlalchemy import select, update

from hive.agents import orchestrator as orch
from hive.config import Settings
from hive.core.db import EventRow, MissionRow, TaskRow
from hive.core.engine import MissionError
from hive.core.models import Gate, MissionStatus
from hive.llm.providers import LLMError
from hive.platform import Platform

REQUEST = (
    "Crie um site para a empresa Sabor da Vila, do segmento de padaria artesanal, "
    "apresente produtos, nossa história e depoimentos. Contato por WhatsApp e Instagram."
)


def settings(tmp_path, **overrides) -> Settings:
    # Testes herméticos: ignoram o .env local (que pode apontar para Ollama/Claude).
    return Settings(_env_file=None, data_dir=tmp_path, mock_latency_s=0, llm_provider="mock", **overrides)


@pytest.fixture
async def platform(tmp_path):
    p = await Platform.create(settings(tmp_path))
    yield p
    await p.engine.drain()
    await p.close()


async def wait_status(p: Platform, mission_id: str, status: MissionStatus, timeout: float = 10) -> MissionRow:
    async def poll():
        while True:
            async with p.sessions() as s:
                m = await s.get(MissionRow, mission_id)
            if m.status == status:
                return m
            assert m.status not in (MissionStatus.FAILED, MissionStatus.REJECTED), m.error
            await asyncio.sleep(0.02)

    return await asyncio.wait_for(poll(), timeout)


def test_heuristic_brief_extracts_company_segment_sections():
    b = orch.heuristic_brief(REQUEST)
    assert b.company_name == "Sabor da Vila"
    assert b.segment == "padaria artesanal"
    assert b.sections == ["Produtos", "Nossa história", "Depoimentos"]
    assert "WhatsApp" in b.contact


def test_validate_plan_detects_dor_violation_and_cycles():
    plan = orch.template_plan(orch.heuristic_brief(REQUEST))
    assert orch.validate_plan(plan, {t.agent for t in plan.tasks}) == []

    broken = plan.model_copy(deep=True)
    next(t for t in broken.tasks if t.key == "build").depends_on = ["design"]  # dev sem conteúdo/arquitetura
    assert any("DoR de 'build'" in p for p in orch.validate_plan(broken, {t.agent for t in plan.tasks}))

    cyclic = plan.model_copy(deep=True)
    cyclic.tasks[0].depends_on = ["finops"]
    assert any("ciclo" in p for p in orch.validate_plan(cyclic, {t.agent for t in plan.tasks}))


async def test_full_mission_with_gates_rework_deploy_and_audit(platform: Platform):
    engine = platform.engine
    m = await engine.submit(REQUEST, requester="tester")

    await wait_status(platform, m.id, MissionStatus.AWAITING_PLAN_APPROVAL)
    await engine.approve(m.id, Gate.PLAN, True, "tester")
    await wait_status(platform, m.id, MissionStatus.AWAITING_DEPLOY_APPROVAL)
    await engine.approve(m.id, Gate.DEPLOY, True, "tester")
    done = await wait_status(platform, m.id, MissionStatus.COMPLETED)

    async with platform.sessions() as s:
        tasks = {t.key: t for t in (await s.scalars(select(TaskRow).where(TaskRow.mission_id == m.id))).all()}
        types = [e.type for e in (await s.scalars(select(EventRow).where(EventRow.mission_id == m.id))).all()]

    # O defeito injetado na 1ª versão gera um ciclo QA → retrabalho → aprovação.
    assert tasks["build"].attempt == 2 and tasks["qa"].attempt == 2
    assert "task.rework" in types
    # Retrabalho direcionado: o título SEO longo demais aponta para content.json (redator) e index.html (dev).
    async with platform.sessions() as s:
        rework = await s.scalar(select(EventRow).where(EventRow.mission_id == m.id, EventRow.type == "task.rework"))
    assert set(rework.data["to"]) == {"content", "build"}
    assert tasks["content"].attempt == 2 and tasks["design"].attempt == 1
    # Cascata: o que dependia do conteúdo refeito também foi refeito (verificação de fatos, ilustrações).
    assert set(rework.data["cascade"]) == {"factcheck", "illustrations"}
    assert tasks["factcheck"].attempt == 2 and tasks["illustrations"].attempt == 2

    # Playbooks usados ficam registrados (nome@versão#hash) em cada delegação.
    async with platform.sessions() as s:
        delegated = (await s.scalars(select(EventRow).where(EventRow.mission_id == m.id,
                                                            EventRow.type == "task.delegated",
                                                            EventRow.task_id == tasks["build"].id))).first()
    assert any(ref.startswith("web-quality@") for ref in delegated.data["playbooks"])
    assert all(t.status == "done" for t in tasks.values())

    # Site publicado e acessível no diretório local.
    index = engine.site_dir(m.id) / "index.html"
    assert index.exists() and 'name="description"' in index.read_text()
    assert done.deployment_url.endswith(f"/sites/{m.id}/")

    # Ilustrações: publicadas junto com o site e referenciadas no HTML.
    images = sorted(p.name for p in engine.site_dir(m.id).glob("img-*.svg"))
    assert "img-hero.svg" in images and len(images) == 4  # hero + 3 seções
    assert all(f'src="{name}"' in index.read_text() for name in images)

    # FinOps apurou custo (simulado) por agente.
    costs = await engine.cost_breakdown(m.id)
    assert costs["simulated"] and costs["total_usd"] > 0
    assert {"orchestrator", "developer", "finops"} <= {a["agent"] for a in costs["by_agent"]}

    # Trilha de auditoria íntegra e sensível a adulteração.
    assert (await platform.bus.verify(m.id))["valid"]
    async with platform.sessions() as s:
        await s.execute(update(EventRow).where(EventRow.mission_id == m.id, EventRow.type == "task.rework")
                        .values(message="adulterado"))
        await s.commit()
    assert not (await platform.bus.verify(m.id))["valid"]


async def test_rejected_plan_stops_mission(platform: Platform):
    m = await platform.engine.submit(REQUEST)
    await wait_status(platform, m.id, MissionStatus.AWAITING_PLAN_APPROVAL)
    await platform.engine.approve(m.id, Gate.PLAN, False, "tester", "fora do escopo")
    await platform.engine.drain()
    async with platform.sessions() as s:
        assert (await s.get(MissionRow, m.id)).status == MissionStatus.REJECTED


async def test_budget_exhausted_fails_mission(tmp_path):
    p = await Platform.create(settings(tmp_path, mission_budget_usd=0.0001, auto_approve=True))
    m = await p.engine.submit(REQUEST)
    await p.engine.drain()
    async with p.sessions() as s:
        row = await s.get(MissionRow, m.id)
    await p.close()
    assert row.status == MissionStatus.FAILED and "Orçamento" in row.error


async def test_retry_resumes_failed_mission_without_redoing_finished_work(platform: Platform):
    engine = platform.engine
    developer = engine.agents["developer"]
    original_run = developer.run
    calls = {"n": 0}

    async def flaky_run(ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("O modelo local qwen3:14b não respondeu em 600 s")
        return await original_run(ctx)

    developer.run = flaky_run
    try:
        m = await engine.submit(REQUEST)
        await wait_status(platform, m.id, MissionStatus.AWAITING_PLAN_APPROVAL)
        await engine.approve(m.id, Gate.PLAN, True, "tester")
        await engine.drain()
        async with platform.sessions() as s:
            failed = await s.get(MissionRow, m.id)
            before = {t.key: t.attempt for t in (await s.scalars(select(TaskRow).where(TaskRow.mission_id == m.id))).all()}
        assert failed.status == MissionStatus.FAILED and "600 s" in failed.error

        with pytest.raises(MissionError):
            await engine.retry(m.id, "tester", budget_usd=0.0000001)  # orçamento menor que o já gasto
        await engine.retry(m.id, "tester")
        await wait_status(platform, m.id, MissionStatus.AWAITING_DEPLOY_APPROVAL)
        await engine.approve(m.id, Gate.DEPLOY, True, "tester")
        await wait_status(platform, m.id, MissionStatus.COMPLETED)
    finally:
        developer.run = original_run

    async with platform.sessions() as s:
        after = {t.key: t.attempt for t in (await s.scalars(select(TaskRow).where(TaskRow.mission_id == m.id))).all()}
        retried = await s.scalar(select(EventRow).where(EventRow.mission_id == m.id, EventRow.type == "mission.retried"))
    # O que já estava pronto antes da falha não foi refeito.
    assert after["backlog"] == before["backlog"] == 1 and after["design"] == before["design"]
    assert retried.data["reopened"] == ["build"] and retried.actor == "user:tester"
    assert (await platform.bus.verify(m.id))["valid"]
