import asyncio
import io
import json

from PIL import Image

from hive.agents.base import TaskContext
from hive.agents.orchestrator import heuristic_brief
from hive.agents.schemas import ImagePrompt, ImagePrompts
from hive.agents.specialists import Developer, Illustrator, image_ext, image_plan
from hive.config import Settings
from hive.core.models import Story
from hive.llm.gpu import GpuArbiter
from hive.media.comfyui import ImageError, RenderedImage, sdxl_workflow, to_webp

REQUEST = "Crie um site para a empresa Sabor da Vila, do segmento de padaria artesanal, apresente produtos."
SITEMAP = [{"id": "produtos", "title": "Produtos", "purpose": ""}, {"id": "historia", "title": "História", "purpose": ""}]
PALETTE = {"primary": "#ff2bd6", "secondary": "#00e5ff", "background": "#0a0a12", "text": "#ffffff"}


def png(width=1216, height=832) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 160)).save(out, "PNG")
    return out.getvalue()


async def test_gpu_arbiter_gives_exclusive_priority_over_new_shared_users():
    gpu, log = GpuArbiter(), []

    async def llm(name, hold):
        async with gpu.shared():
            log.append(f"{name}+")
            await asyncio.sleep(hold)
            log.append(f"{name}-")

    async def images():
        async with gpu.exclusive():
            log.append("img+")
            await asyncio.sleep(0.05)
            log.append("img-")

    first = asyncio.create_task(llm("a", 0.1))
    await asyncio.sleep(0.01)
    excl = asyncio.create_task(images())
    await asyncio.sleep(0.01)
    late = asyncio.create_task(llm("b", 0.01))  # chega depois do pedido exclusivo: espera
    await asyncio.gather(first, excl, late)
    assert log == ["a+", "a-", "img+", "img-", "b+", "b-"]


def test_sdxl_workflow_and_webp_conversion():
    s = Settings(_env_file=None, comfyui_checkpoint="sd_xl_base_1.0.safetensors")
    wf = sdxl_workflow(s, "sourdough bread, neon", "text, watermark", 42)
    assert wf["3"]["inputs"]["seed"] == 42 and wf["4"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"
    assert wf["6"]["inputs"]["text"] == "sourdough bread, neon"
    data, width, height = to_webp(png(), max_width=1200, quality=80)
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP" and (width, height) == (1200, 821)


def ctx(settings: Settings, services) -> TaskContext:
    async def think(schema, system, prompt, mock, effort="medium"):
        assert schema is ImagePrompts
        return ImagePrompts(images=[
            ImagePrompt(section_id="hero", alt="Pães sob luz neon", prompt="bread under neon light", negative="text"),
            ImagePrompt(section_id="produtos", alt="Vitrine de doces", prompt="pastry display", negative="text")])

    return TaskContext(
        mission_id="m1", task_id="t1", request=REQUEST, brief=heuristic_brief(REQUEST),
        story=Story(title="x", user_story="x", acceptance_criteria=[], inputs_required=[], outputs_expected=[]),
        inputs={"sitemap.json": json.dumps(SITEMAP), "design-system.json": json.dumps({"palette": PALETTE})},
        attempt=1, feedback=None, settings=settings, services=services, think=think, emit=None,
    )


async def test_illustrator_art_director_mode_renders_webp_and_falls_back_per_image():
    jobs_seen = []

    class FakeServices:
        async def render_images(self, mission_id, task_id, role, jobs):
            jobs_seen.extend(jobs)
            ok = RenderedImage(data=to_webp(png(), 1200, 80)[0], width=1200, height=821, seconds=12.5)
            return [ok, ImageError("CUDA/HIP out of memory"), ok]

    s = Settings(_env_file=None, image_provider="comfyui")
    result = await Illustrator().run(ctx(s, FakeServices()))
    manifest = json.loads(result.artifacts["images.json"])
    assert [m["file"] for m in manifest] == ["img-hero.webp", "img-produtos.webp", "img-historia.webp"]
    assert [m["source"] for m in manifest] == ["comfyui", "procedural", "comfyui"]
    assert all(result.artifacts[m["file"]][8:12] == b"WEBP" for m in manifest)
    assert manifest[0]["alt"] == "Pães sob luz neon" and "high quality" in jobs_seen[0][0]
    assert [e.passed for e in result.evidence] == [True, False, True]
    # O HTML do desenvolvedor aponta para os mesmos arquivos, decididos só pelo mapa do site.
    assert [f for _, _, f in image_plan(SITEMAP, "Sabor da Vila", image_ext(s))] == [m["file"] for m in manifest]


async def test_illustrator_uses_placeholders_when_comfyui_is_down():
    class DownServices:
        async def render_images(self, *args):
            raise ImageError("ComfyUI indisponível em http://localhost:8188")

    result = await Illustrator().run(ctx(Settings(_env_file=None, image_provider="comfyui"), DownServices()))
    manifest = json.loads(result.artifacts["images.json"])
    assert {m["source"] for m in manifest} == {"procedural"} and not any(e.passed for e in result.evidence)


def test_illustrator_playbook_follows_active_image_mode(monkeypatch):
    from hive.agents import specialists

    monkeypatch.setattr(specialists, "get_settings", lambda: Settings(_env_file=None, image_provider="comfyui"))
    assert [p.name for p in Illustrator().playbooks()] == ["art-direction"]
    monkeypatch.setattr(specialists, "get_settings", lambda: Settings(_env_file=None, image_provider="svg"))
    assert [p.name for p in Illustrator().playbooks()] == ["svg-illustration"]
    assert Developer().playbooks()  # outros agentes não são afetados


async def test_engine_renders_batch_with_exclusive_gpu_and_records_energy_cost(tmp_path):
    from sqlalchemy import select

    from hive.core.db import EventRow, LLMCallRow, MissionRow
    from hive.platform import Platform

    p = await Platform.create(Settings(_env_file=None, data_dir=tmp_path, mock_latency_s=0, image_provider="comfyui"))

    class FakeComfy:
        freed = False

        async def available(self):
            return True

        async def render(self, prompt, negative, seed):
            if "fail" in prompt:
                raise ImageError("falhou")
            return RenderedImage(data=b"RIFFxxxxWEBP", width=1200, height=821, seconds=20.0)

        async def free(self):
            FakeComfy.freed = True

    p.engine._comfy = FakeComfy()
    m = await p.engine.submit(REQUEST)
    await p.engine.drain()
    results = await p.engine.render_images(m.id, None, "illustrator", [("bread", "text", 1), ("fail", "text", 2)])
    assert isinstance(results[0], RenderedImage) and isinstance(results[1], ImageError) and FakeComfy.freed

    async with p.sessions() as s:
        calls = (await s.scalars(select(LLMCallRow).where(LLMCallRow.mission_id == m.id,
                                                          LLMCallRow.provider == "comfyui"))).all()
        types = [e.type for e in (await s.scalars(select(EventRow).where(EventRow.mission_id == m.id))).all()]
        mission = await s.get(MissionRow, m.id)
    assert len(calls) == 1 and calls[0].model == "sd_xl_base_1.0" and calls[0].cost_usd > 0  # 20 s × 304 W
    assert types.index("gpu.exclusive") < types.index("gpu.released")
    assert mission.cost_usd >= calls[0].cost_usd
    await p.close()
