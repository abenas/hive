from hive.agents.base import TaskContext
from hive.agents.orchestrator import heuristic_brief
from hive.agents.qa_checks import run_checks
from hive.agents.schemas import Claim, ContentSection, FactReport, PageSection, SiteContent
from hive.agents.specialists import FactChecker, section_ids
from hive.config import Settings
from hive.core.models import Story

REQUEST = "Crie um site para a empresa Sabor da Vila, do segmento de padaria artesanal, apresente produtos."


def content(body: str, footer: str = "© Sabor da Vila") -> str:
    return SiteContent(
        seo={"title": "Sabor da Vila | Padaria", "description": "Pães artesanais feitos todos os dias, com fermentação natural e carinho.", "keywords": ["padaria"]},
        hero={"headline": "Sabor da Vila", "subheadline": "Padaria artesanal", "cta": "Encomendar"},
        sections=[ContentSection(id="sobre", title="Sobre", body=body, items=[])],
        contact={"headline": "Fale conosco", "text": "WhatsApp", "channels": ["WhatsApp"]},
        footer=footer,
    ).model_dump_json()


def ctx_for(body: str, attempt: int, claims: list[Claim]) -> TaskContext:
    async def think(schema, system, prompt, mock, effort="medium"):
        assert schema is FactReport
        return FactReport(claims=claims)

    return TaskContext(
        mission_id="m", task_id="t", request=REQUEST, brief=heuristic_brief(REQUEST),
        story=Story(title="x", user_story="x", acceptance_criteria=[], inputs_required=["content.json"],
                    outputs_expected=["fact-check.md"]),
        inputs={"content.json": content(body)}, attempt=attempt, feedback=None,
        settings=Settings(_env_file=None, max_rework_attempts=2), services=None, think=think, emit=None,
    )


INVENTED = Claim(text="fundada por um grupo de amigos", kind="origem", supported=False,
                 reason="O pedido não fala da origem da empresa")


async def test_fact_checker_sends_invented_facts_back_to_copywriter():
    result = await FactChecker().run(ctx_for("Desde 1998, fundada por um grupo de amigos.", 1, [INVENTED]))
    assert not result.passed
    assert result.data["rework_artifacts"] == ["content.json"]
    assert any("1998" in f for f in result.data["failed"])
    assert any("grupo de amigos" in f for f in result.data["failed"])


async def test_fact_checker_lets_last_attempt_through_with_warnings_for_human_decision():
    result = await FactChecker().run(ctx_for("Fundada por um grupo de amigos.", 2, [INVENTED]))
    assert result.passed and result.data["warnings"]
    assert any("decisão no go-live" in e.title for e in result.evidence)


async def test_fact_checker_passes_clean_content():
    supported = Claim(text="padaria artesanal", kind="outro", supported=True, reason="Está no pedido")
    result = await FactChecker().run(ctx_for("Pães artesanais feitos todos os dias.", 1, [supported]))
    assert result.passed and not result.data["warnings"]


def test_generic_section_ids_become_meaningful_and_unique():
    sections = [PageSection(id="secao", title="Café da Manhã", purpose=""),
                PageSection(id="section-2", title="Produtos", purpose=""),
                PageSection(id="produtos", title="Produtos", purpose="")]
    section_ids(sections)
    assert [s.id for s in sections] == ["cafe-da-manha", "produtos", "produtos-2"]


def test_qa_fails_unstyled_navigation_list():
    html = ('<html lang="pt-BR"><head><title>Sabor da Vila</title></head><body>'
            '<nav><ul><li><a href="#a">A</a></li></ul></nav><h1>x</h1><section id="a"></section></body></html>')
    palette = {"text": "#ffffff", "background": "#000000", "on_primary": "#000000", "primary": "#ffffff"}
    by_id = lambda css: {c.id: c for c in run_checks(html, css, ["a"], palette)}  # noqa: E731
    assert not by_id("body { color: red; }")["nav-style"].passed
    assert by_id("nav ul { list-style: none; }")["nav-style"].passed


async def test_copywriter_normalizes_copyright_year_instead_of_triggering_fact_rework():
    import datetime

    from hive.agents.specialists import Copywriter

    async def think(schema, system, prompt, mock, effort="medium"):
        return SiteContent.model_validate_json(content("Pães artesanais.", footer="© 2025 Sabor da Vila"))

    ctx = ctx_for("x", 1, [])
    ctx.think = think
    ctx.inputs = {"sitemap.json": "[]"}
    result = await Copywriter().run(ctx)
    footer = SiteContent.model_validate_json(result.artifacts["content.json"]).footer
    assert footer == f"© {datetime.date.today().year} Sabor da Vila"
