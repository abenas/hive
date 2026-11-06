"""Pacote de domínio "Agência Digital": agentes especializados."""

import dataclasses
import datetime
import hashlib
import json
import re
import unicodedata

from hive.agents import site_builder
from hive.agents.base import Agent, TaskContext
from hive.agents import playbooks as pb
from hive.agents.illustration import neon_art, sanitize_svg
from hive.config import get_settings
from hive.media.comfyui import ImageError, placeholder_webp
from hive.agents.qa_checks import Check, contrast_ratio, run_checks
from hive.agents.schemas import (
    ADR,
    Architecture,
    Backlog,
    BacklogStory,
    Component,
    Contact,
    ContentSection,
    DeployPlan,
    DesignSystem,
    Epic,
    FactReport,
    FinOpsAdvice,
    Hero,
    Illustration,
    Illustrations,
    ImagePrompt,
    ImagePrompts,
    Item,
    PageSection,
    Palette,
    SectionLayout,
    SEO,
    SiteContent,
    SiteMarkup,
    SiteStyles,
)
from hive.core.models import AgentResult, Evidence


GENERIC_IDS = re.compile(r"(secao|section|sec|item|pagina|page|bloco|block)?-?\d*")


def section_ids(sections) -> None:
    """Ids de âncora significativos e únicos: id genérico ("secao", "section-2") vira o slug do título."""
    seen: set[str] = set()
    for s in sections:
        sid = slug(s.id)
        if GENERIC_IDS.fullmatch(sid):
            sid = slug(s.title)
        base, n = sid, 2
        while sid in seen:
            sid, n = f"{base}-{n}", n + 1
        seen.add(sid)
        s.id = sid


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "secao"


def sha(content: str | bytes) -> str:
    return hashlib.sha256(content if isinstance(content, bytes) else content.encode()).hexdigest()


def js(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- PO
class ProductOwner(Agent):
    role = "product_owner"
    name = "Paula"
    title = "Product Owner"
    description = "Traduz o briefing em épicos, histórias priorizadas, mapa do site e KPIs."
    skills = ["descoberta", "priorização MoSCoW", "critérios de aceite", "KPIs"]
    produces = ["backlog.md", "sitemap.json"]

    def mock(self, ctx: TaskContext) -> Backlog:
        b = ctx.brief
        sections = [s for s in b.sections if slug(s) not in ("contato", "contatos", "fale-conosco")]
        sitemap = [PageSection(id=slug(s), title=s, purpose=f"Apresentar {s.lower()} da {b.company_name}")
                   for s in sections]
        return Backlog(
            epics=[
                Epic(title="Presença digital", stories=[
                    BacklogStory(title=f"Seção {s.title}",
                                 user_story=f"Como visitante, quero ver {s.title.lower()}, para conhecer a "
                                 f"{b.company_name}.",
                                 acceptance_criteria=[f"Seção '{s.title}' visível no menu e acessível por âncora",
                                                      "Texto revisado e coerente com o tom de voz"],
                                 priority="MUST") for s in sitemap]),
                Epic(title="Conversão", stories=[
                    BacklogStory(title="Chamada para contato",
                                 user_story="Como visitante interessado, quero um caminho claro para "
                                 "entrar em contato, para solicitar atendimento.",
                                 acceptance_criteria=["CTA no topo e no rodapé", "Canais de contato visíveis"],
                                 priority="MUST")]),
                Epic(title="Qualidade e operação", stories=[
                    BacklogStory(title="Site acessível e rápido",
                                 user_story="Como visitante, quero um site rápido e acessível em qualquer "
                                 "dispositivo.",
                                 acceptance_criteria=["Contraste WCAG AA", "Peso total ≤ 100 KB"],
                                 priority="SHOULD")]),
            ],
            sitemap=sitemap,
            kpis=["Taxa de cliques no CTA ≥ 3%", "Tempo de carregamento < 2 s em 4G",
                  "Contatos gerados por mês"],
        )

    async def run(self, ctx: TaskContext) -> AgentResult:
        out = await ctx.think(Backlog, self.system_prompt(ctx), self.task_prompt(ctx), lambda: self.mock(ctx))
        section_ids(out.sitemap)
        md = [f"# Backlog — {ctx.brief.company_name}\n"]
        for e in out.epics:
            md.append(f"## Épico: {e.title}")
            for st in e.stories:
                md.append(f"### [{st.priority}] {st.title}\n{st.user_story}\n")
                md += [f"- [ ] {c}" for c in st.acceptance_criteria]
                md.append("")
        md.append("## KPIs\n" + "\n".join(f"- {k}" for k in out.kpis))
        stories = sum(len(e.stories) for e in out.epics)
        return AgentResult(
            summary=f"{len(out.epics)} épicos, {stories} histórias e {len(out.sitemap)} seções no mapa do site.",
            artifacts={"backlog.md": "\n".join(md),
                       "sitemap.json": js([s.model_dump() for s in out.sitemap])},
            evidence=[
                Evidence(kind="metric", title="Histórias escritas", detail=str(stories)),
                Evidence(kind="check", title="Todas as histórias têm critérios de aceite",
                         passed=all(st.acceptance_criteria for e in out.epics for st in e.stories)),
                Evidence(kind="note", title="KPIs", detail="; ".join(out.kpis)),
            ],
        )


# --------------------------------------------------------------------- Arquiteto
class Architect(Agent):
    role = "architect"
    name = "Arthur"
    title = "Arquiteto de Soluções"
    description = "Define a arquitetura, os serviços AWS, os requisitos não funcionais e registra ADRs."
    skills = ["arquitetura AWS", "ADRs", "segurança", "custo-eficiência"]
    produces = ["architecture.md"]

    def mock(self, ctx: TaskContext) -> Architecture:
        return Architecture(
            overview="Site estático servido por CDN com origem privada em S3; deploy via pipeline "
            "com IaC. Sem servidores para manter: custo e superfície de ataque mínimos.",
            components=[
                Component(name="Origem", aws_service="Amazon S3", purpose="Armazenar os arquivos do site (privado)"),
                Component(name="CDN", aws_service="Amazon CloudFront", purpose="Entrega global com HTTPS e cache"),
                Component(name="Certificado", aws_service="AWS Certificate Manager", purpose="TLS gratuito"),
                Component(name="DNS", aws_service="Amazon Route 53", purpose="Domínio próprio"),
                Component(name="Observabilidade", aws_service="CloudFront standard logs + CloudWatch",
                          purpose="Acessos, erros e alarmes"),
            ],
            adrs=[
                ADR(title="ADR-001: Site estático em vez de CMS",
                    decision="Gerar HTML/CSS estático",
                    rationale="Conteúdo muda pouco; elimina servidor, banco e patching.",
                    alternatives=["WordPress em EC2/Lightsail", "Framework SSR em container"]),
                ADR(title="ADR-002: CloudFront com Origin Access Control",
                    decision="Bucket S3 privado acessível só pela distribuição",
                    rationale="Evita exposição pública do bucket e habilita HTTPS/HTTP2/compressão.",
                    alternatives=["S3 static website hosting público", "Amplify Hosting"]),
            ],
            nfrs=["Disponibilidade ≥ 99,9% (SLA CloudFront)", "TTFB < 200 ms nas capitais",
                  "Custo mensal < US$ 5 para até 50 mil visitas", "HTTPS obrigatório e cabeçalhos de segurança"],
        )

    async def run(self, ctx: TaskContext) -> AgentResult:
        out = await ctx.think(Architecture, self.system_prompt(ctx), self.task_prompt(ctx), lambda: self.mock(ctx))
        md = [f"# Arquitetura — {ctx.brief.company_name}\n", out.overview, "\n## Componentes",
              "| Componente | Serviço AWS | Propósito |", "|---|---|---|"]
        md += [f"| {c.name} | {c.aws_service} | {c.purpose} |" for c in out.components]
        md.append("\n## Decisões (ADRs)")
        for a in out.adrs:
            md.append(f"### {a.title}\n**Decisão:** {a.decision}\n\n**Motivo:** {a.rationale}\n\n"
                      f"**Alternativas:** {', '.join(a.alternatives)}\n")
        md.append("## Requisitos não funcionais\n" + "\n".join(f"- {n}" for n in out.nfrs))
        return AgentResult(
            summary=f"{len(out.components)} componentes, {len(out.adrs)} ADRs, {len(out.nfrs)} RNFs.",
            artifacts={"architecture.md": "\n".join(md)},
            evidence=[Evidence(kind="note", title=a.title, detail=a.decision) for a in out.adrs]
            + [Evidence(kind="metric", title="Serviços AWS", detail=", ".join(c.aws_service for c in out.components))],
        )


# ----------------------------------------------------------------------- Designer
PALETTES = {
    ("saude", "clinica", "odonto", "medic", "bem-estar", "estetica"):
        ("#0F766E", "#FFFFFF", "#115E59", "#FCD34D", "#FFFFFF", "#F0FDFA", "#0F172A", "#475569"),
    ("tecnolog", "software", "ti", "digital", "startup"):
        ("#4338CA", "#FFFFFF", "#6D28D9", "#FDE047", "#FFFFFF", "#EEF2FF", "#111827", "#4B5563"),
    ("aliment", "restaurante", "padaria", "cafe", "gastronom", "pizzaria"):
        ("#B91C1C", "#FFFFFF", "#9A3412", "#FBBF24", "#FFFBF5", "#FEF3E2", "#1C1917", "#57534E"),
    ("advoca", "juridic", "contab", "consultor", "financ"):
        ("#1E3A5F", "#FFFFFF", "#0F2741", "#D4A73C", "#FFFFFF", "#F4F6F9", "#0B1320", "#4A5568"),
    ("constru", "engenharia", "arquitet", "imobili", "reforma"):
        ("#92400E", "#FFFFFF", "#78350F", "#FCD34D", "#FFFFFF", "#FEF7ED", "#1C1917", "#57534E"),
    ("educa", "escola", "curso", "ensino"):
        ("#1D4ED8", "#FFFFFF", "#0E7490", "#FDE047", "#FFFFFF", "#EFF6FF", "#0F172A", "#475569"),
}
DEFAULT_PALETTE = ("#7C3AED", "#FFFFFF", "#5B21B6", "#FCD34D", "#FFFFFF", "#F5F3FF", "#111827", "#4B5563")


class Designer(Agent):
    role = "designer"
    name = "Diana"
    title = "Designer UX/UI"
    description = "Cria identidade visual, design system (paleta, tipografia, espaçamento) e wireframes acessíveis."
    skills = ["UX", "UI", "acessibilidade WCAG", "design systems"]
    produces = ["design-system.json", "wireframe.md"]

    def mock(self, ctx: TaskContext) -> DesignSystem:
        seg = slug(ctx.brief.segment)
        colors = next((c for keys, c in PALETTES.items() if any(k in seg for k in keys)), DEFAULT_PALETTE)
        names = ["primary", "on_primary", "secondary", "accent", "background", "surface", "text", "muted"]
        sitemap = json.loads(ctx.inputs.get("sitemap.json", "[]"))
        return DesignSystem(
            palette=Palette(**dict(zip(names, colors))),
            font_heading="Poppins", font_body="Inter", radius_px=12,
            style_notes=f"Visual {ctx.brief.style.lower()}; cores derivadas do segmento '{ctx.brief.segment}'. "
            "Hero com gradiente da cor primária para a secundária e CTA em cor de destaque.",
            layouts=[SectionLayout(section_id=s["id"], layout="Título + parágrafo + grade de cartões (3 colunas, "
                                   "1 no celular)") for s in sitemap],
        )

    async def run(self, ctx: TaskContext) -> AgentResult:
        out = await ctx.think(DesignSystem, self.system_prompt(ctx), self.task_prompt(ctx), lambda: self.mock(ctx))
        p = out.palette
        text_ratio = contrast_ratio(p.text, p.background)
        hero_ratio = contrast_ratio(p.on_primary, p.primary)
        wire = [f"# Wireframe — {ctx.brief.company_name}\n", "```",
                "┌──────────────────────────────────────────┐",
                "│ [logo] Marca            menu · menu · CTA │",
                "├──────────────────────────────────────────┤",
                "│ HERO: título forte, subtítulo, [CTA]      │"]
        for lay in out.layouts:
            wire.append(f"│ #{lay.section_id:<40} │")
        wire += ["│ #contato: canais + [CTA]                  │",
                 "└──────────────────────────────────────────┘", "```", "", out.style_notes]
        return AgentResult(
            summary=f"Design system com paleta de 8 cores, {out.font_heading}/{out.font_body}; "
            f"contraste do texto {text_ratio}:1.",
            artifacts={"design-system.json": out.model_dump_json(indent=2), "wireframe.md": "\n".join(wire)},
            evidence=[
                Evidence(kind="check", title="Contraste texto/fundo (WCAG AA ≥ 4.5)",
                         detail=f"{text_ratio}:1", passed=text_ratio >= 4.5),
                Evidence(kind="check", title="Contraste no hero (≥ 3:1 texto grande)",
                         detail=f"{hero_ratio}:1", passed=hero_ratio >= 3),
                Evidence(kind="note", title="Paleta", detail=", ".join(f"{k} {v}" for k, v in p.model_dump().items())),
            ],
        )


# ---------------------------------------------------------------------- Redator
class Copywriter(Agent):
    role = "copywriter"
    name = "Caio"
    title = "Redator & SEO"
    description = "Escreve os textos do site com tom de voz da marca e otimiza para buscadores (SEO)."
    skills = ["copywriting", "SEO on-page", "tom de voz"]
    produces = ["content.json"]

    def mock(self, ctx: TaskContext) -> SiteContent:
        b = ctx.brief
        sitemap = json.loads(ctx.inputs.get("sitemap.json", "[]"))
        seg = b.segment
        sections = []
        for s in sitemap:
            sections.append(ContentSection(
                id=s["id"], title=s["title"],
                body=f"{s['title']} da {b.company_name}: atendimento de {seg} feito com cuidado, "
                "transparência e foco no resultado de cada cliente.",
                items=[Item(title=f"{s['title']} {i}", text=f"Destaque {i} sobre {s['title'].lower()} "
                            f"pensado para {b.audience.lower()}.") for i in (1, 2, 3)],
            ))
        title = f"{b.company_name} | {seg.capitalize()}"[:60]
        return SiteContent(
            seo=SEO(title=title,
                    description=f"{b.company_name}: referência em {seg}. Conheça nossos serviços, "
                    "diferenciais e fale com a gente hoje mesmo."[:160],
                    keywords=[seg, b.company_name.lower(), f"{seg} perto de mim"]),
            hero=Hero(headline=f"{b.company_name}: {seg} com excelência",
                      subheadline=f"Soluções de {seg} para quem busca qualidade, confiança e atendimento próximo.",
                      cta="Fale com a gente"),
            sections=sections,
            contact=Contact(headline="Vamos conversar?", text="Responda em minutos pelos nossos canais.",
                            channels=[c.strip().capitalize() for c in b.contact.split(",") if c.strip()]
                            or ["WhatsApp", "E-mail"]),
            footer=f"© {b.company_name}. Todos os direitos reservados.",
        )

    @staticmethod
    def seo_issues(out: SiteContent) -> list[str]:
        issues = []
        if not 10 <= len(out.seo.title) <= 60:
            issues.append(f"O título SEO tem {len(out.seo.title)} caracteres; precisa ter entre 10 e 60.")
        if not 50 <= len(out.seo.description) <= 160:
            issues.append(f"A meta description tem {len(out.seo.description)} caracteres; precisa ter entre 50 e 160.")
        return issues

    async def run(self, ctx: TaskContext) -> AgentResult:
        out = await ctx.think(SiteContent, self.system_prompt(ctx), self.task_prompt(ctx), lambda: self.mock(ctx))
        notes: list[Evidence] = []
        if issues := self.seo_issues(out):
            # Autorrevisão só do bloco de SEO (~60 tokens), em vez de reescrever o conteúdo inteiro (~1.600).
            await ctx.emit("agent.self_review", "Autorrevisão de SEO: " + " ".join(issues), {"issues": issues})
            current = out.seo
            out.seo = await ctx.think(
                SEO, self.system_prompt(ctx),
                f"## Empresa\n{ctx.brief.company_name} ({ctx.brief.segment})\n\n## Destaque do site\n"
                f"{out.hero.headline}. {out.hero.subheadline}\n\n## SEO atual\n{current.model_dump_json(indent=2)}\n\n"
                "## Corrija\n" + "\n".join(f"- {i}" for i in issues)
                + "\nConte os caracteres antes de responder. Mantenha o sentido e as palavras-chave.",
                lambda: current, effort="low",
            )
            notes.append(Evidence(kind="note", title="Autorrevisão de SEO executada", detail=" ".join(issues)))
        if len(out.seo.description) > 160:  # último recurso determinístico: corta em limite de palavra
            out.seo.description = out.seo.description[:157].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
            notes.append(Evidence(kind="note", title="Meta description encurtada automaticamente",
                                  detail=f"{len(out.seo.description)} caracteres"))
        if len(out.seo.title) > 60:
            out.seo.title = out.seo.title[:60].rsplit(" ", 1)[0].rstrip(" |-–")
            notes.append(Evidence(kind="note", title="Título SEO encurtado automaticamente",
                                  detail=f"{len(out.seo.title)} caracteres"))
        # "© 2025" é ano de copyright, não fato sobre o cliente: vale sempre o ano corrente.
        year = str(datetime.date.today().year)
        footer = re.sub(r"(©|\(c\)|copyright)\s*(\d{4})", lambda m: f"{m.group(1)} {year}", out.footer, flags=re.I)
        if footer != out.footer:
            out.footer = footer
            notes.append(Evidence(kind="note", title=f"Ano de copyright ajustado para {year}"))
        for s in out.sections:
            s.id = slug(s.id)
        words = sum(len(s.body.split()) + sum(len(i.text.split()) for i in s.items) for s in out.sections)
        return AgentResult(
            summary=f"Textos para {len(out.sections)} seções (~{words} palavras) e metadados de SEO.",
            artifacts={"content.json": out.model_dump_json(indent=2)},
            evidence=[
                Evidence(kind="check", title="Título SEO ≤ 60 caracteres", detail=f"{len(out.seo.title)}",
                         passed=len(out.seo.title) <= 60),
                Evidence(kind="check", title="Meta description ≤ 160 caracteres",
                         detail=f"{len(out.seo.description)}", passed=len(out.seo.description) <= 160),
                Evidence(kind="metric", title="Palavras escritas", detail=str(words)),
                *notes,
            ],
        )


# ------------------------------------------------------------- Verificadora de fatos
YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def copy_text(content: SiteContent) -> str:
    """Todo o texto que vai ao ar, numa string só (o que precisa ser verdadeiro)."""
    parts = [content.seo.title, content.seo.description, content.hero.headline, content.hero.subheadline,
             content.contact.headline, content.contact.text, content.footer]
    for sec in content.sections:
        parts += [sec.title, sec.body] + [f"{i.title}: {i.text}" for i in sec.items]
    return "\n".join(parts)


class FactChecker(Agent):
    role = "fact_checker"
    name = "Vera"
    title = "Verificadora de Fatos"
    description = ("Confere se o conteúdo afirma sobre o cliente algo que não está no pedido nem no briefing "
                   "(datas, origem, pessoas, números, prêmios, preços) e devolve ao redator o que for inventado.")
    skills = ["checagem de fatos", "rastreabilidade de fontes", "compliance de conteúdo"]
    produces = ["fact-check.md"]

    async def run(self, ctx: TaskContext) -> AgentResult:
        content = SiteContent.model_validate_json(ctx.inputs["content.json"])
        text = copy_text(content)
        source = f"{ctx.request}\n{ctx.brief.model_dump_json()}"
        allowed_years = set(YEAR.findall(source)) | {str(datetime.date.today().year)}
        invented_years = sorted(set(YEAR.findall(text)) - allowed_years)

        testimonials_requested = bool(re.search(r"depoiment|avalia", ctx.request, re.I))
        report = await ctx.think(
            FactReport, self.system_prompt(ctx),
            f"## Fonte da verdade: pedido do cliente\n{ctx.request}\n\n## Fonte da verdade: briefing\n"
            f"{ctx.brief.model_dump_json(indent=2)}\n\n## Conteúdo a verificar\n{text}\n\n## Tarefa\n"
            "Liste SOMENTE as afirmações factuais concretas sobre a empresa que o pedido e o briefing NÃO sustentam: "
            "ano de fundação, fundadores ou pessoas, quantidades, prêmios, preços, endereços, certificações, "
            "clientes atendidos, eventos já realizados. Não liste o que está correto. Não são fatos (não liste): "
            "adjetivos e promessas de marketing, missão, visão, valores, slogans"
            + (", nem os depoimentos, que o pedido solicitou e são exemplos ilustrativos" if testimonials_requested
               else "") + ". Se não houver nada, devolva a lista vazia.",
            lambda: FactReport(claims=[]), effort="medium",
        )
        # Rede de segurança caso o modelo liste o que foi pedido para não listar.
        ignored = r"miss[aã]o|mission|vis[aã]o|vision|valor|slogan|marketing" + (
            r"|depoiment|testimonial|review" if testimonials_requested else "")
        unsupported = [c for c in report.claims if not c.supported and not re.search(ignored, c.kind, re.I)]
        issues = [f"Ano {y} citado no conteúdo, mas ausente do pedido" for y in invented_years]
        issues += [f"\"{c.text}\" ({c.kind}): {c.reason}" for c in unsupported]
        issues = list(dict.fromkeys(issues))  # o modelo às vezes repete a mesma afirmação
        # Na última tentativa não trava a missão: as pendências seguem para a decisão humana no go-live.
        final = ctx.attempt >= ctx.settings.max_rework_attempts
        passed = not issues or final
        md = [f"# Verificação de fatos — tentativa {ctx.attempt}\n",
              f"**Parecer:** {'sem pendências' if not issues else 'pendências para revisão humana' if final else 'devolvido ao redator'}\n",
              "| Afirmação | Tipo | Sustentada? | Motivo |", "|---|---|---|---|"]
        md += [f"| {c.text} | {c.kind} | {'sim' if c.supported else 'não'} | {c.reason} |" for c in report.claims]
        if invented_years:
            md.append(f"\nAnos sem fonte (verificação determinística): {', '.join(invented_years)}")
        evidence = [Evidence(kind="check", title=i, passed=False) for i in issues]
        evidence.append(Evidence(kind="metric", title="Afirmações factuais encontradas",
                                 detail=f"{len(report.claims)} ({len(report.claims) - len(unsupported)} sustentadas)"))
        if final and issues:
            evidence.append(Evidence(kind="note", title="Pendências encaminhadas para sua decisão no go-live",
                                     detail="Limite de retrabalho atingido; revise antes de publicar."))
        return AgentResult(
            summary=("Nenhuma afirmação sem fonte." if not issues
                     else f"{len(issues)} afirmação(ões) sem fonte" + (": aguardam sua decisão." if final else ": devolvido ao redator.")),
            artifacts={"fact-check.md": "\n".join(md)},
            evidence=evidence,
            passed=passed,
            data={"failed": issues, "rework_artifacts": ["content.json"]} if not passed else {"warnings": issues},
        )


# -------------------------------------------------------------------- Ilustradora
MAX_IMAGES = 5


def image_ext(settings) -> str:
    return "webp" if settings.image_provider == "comfyui" else "svg"


def image_plan(sitemap: list[dict], company: str, ext: str = "svg") -> list[tuple[str, str, str]]:
    """(section_id, título, arquivo) de cada ilustração, decidido só pelo mapa do site.

    Ilustradora e desenvolvedor usam o mesmo plano: o HTML já sai apontando para os arquivos certos
    enquanto as imagens ainda estão sendo desenhadas, e as duas tarefas rodam em paralelo.
    """
    targets = [("hero", company)] + [(s["id"], s["title"]) for s in sitemap][: MAX_IMAGES - 1]
    return [(sid, title, f"img-{slug(sid)}.{ext}") for sid, title in targets]


class Illustrator(Agent):
    role = "illustrator"
    name = "Íris"
    title = "Ilustradora Digital"
    description = ("Cria ilustrações vetoriais (SVG) que representam o conteúdo de cada seção, na paleta e "
                   "na direção visual do design system.")
    skills = ["ilustração vetorial", "SVG", "direção de arte", "acessibilidade de imagens"]
    produces = ["images.json"]
    effort = "high"

    def playbooks(self) -> list[pb.Playbook]:
        # Só o guia do modo ativo: regras de SVG não servem para prompts de imagem e vice-versa.
        wanted = "art-direction" if get_settings().image_provider == "comfyui" else "svg-illustration"
        return [p for p in super().playbooks() if p.name == wanted]

    def targets(self, ctx: TaskContext) -> list[tuple[str, str]]:
        plan = image_plan(json.loads(ctx.inputs.get("sitemap.json", "[]")), ctx.brief.company_name)
        return [(sid, title) for sid, title, _ in plan]

    async def run_raster(self, ctx: TaskContext, palette: dict, targets: list[tuple[str, str]]) -> AgentResult:
        """Modo diretora de arte: o LLM escreve os prompts e o ComfyUI (SDXL local) desenha."""
        s = ctx.settings
        spec = "\n".join(f"- section_id `{sid}`: {title}" for sid, title in targets)
        negative = "text, letters, watermark, logo, signature, blurry, low quality, deformed hands, extra fingers"
        prompts = await ctx.think(
            ImagePrompts, self.system_prompt(ctx),
            self.task_prompt(ctx, f"## Imagens a criar (uma por item)\n{spec}\n\n"
                             f"Paleta do design system: {js(palette)}\nDireção visual: {ctx.brief.style}"),
            lambda: ImagePrompts(images=[ImagePrompt(
                section_id=sid, alt=f"Ilustração representando {title}",
                prompt=f"{title}, {ctx.brief.segment}, {ctx.brief.style}, professional photography", negative=negative)
                for sid, title in targets]),
            effort=self.effort,
        )
        by_section = {p.section_id: p for p in prompts.images}
        jobs, chosen = [], []
        for sid, title in targets:
            p = by_section.get(sid) or ImagePrompt(section_id=sid, alt=f"Ilustração representando {title}",
                                                   prompt=f"{title}, {ctx.brief.style}", negative=negative)
            seed = int(sha(f"{ctx.mission_id}:{sid}")[:8], 16)
            jobs.append((f"{p.prompt}, high quality, sharp focus", p.negative or negative, seed))
            chosen.append((sid, title, p))
        try:
            rendered = await ctx.services.render_images(ctx.mission_id, ctx.task_id, self.role, jobs)
        except ImageError as e:
            rendered = [e] * len(jobs)  # ComfyUI fora do ar: tudo cai no plano B
        manifest, evidence, artifacts = [], [], {}
        for (sid, title, p), result in zip(chosen, rendered):
            file = f"img-{slug(sid)}.webp"
            ok = not isinstance(result, ImageError)
            data = result.data if ok else placeholder_webp(palette, f"{ctx.mission_id}:{sid}", s.comfyui_width,
                                                           s.comfyui_height, s.image_max_width, s.image_quality)
            artifacts[file] = data
            manifest.append({"file": file, "section_id": sid, "alt": p.alt.strip() or f"Ilustração: {title}",
                             "concept": p.prompt, "source": "comfyui" if ok else "procedural",
                             "bytes": len(data)})
            evidence.append(Evidence(
                kind="check", passed=ok,
                title=f"{file} — {'gerada no ComfyUI' if ok else 'plano B (gradiente)'}",
                detail=(f"{result.width}×{result.height} WebP, {len(data) // 1024} KB em {result.seconds:.0f} s"
                        if ok else str(result))))
        made = sum(1 for m in manifest if m["source"] == "comfyui")
        return AgentResult(
            summary=f"{len(manifest)} imagens ({made} geradas no ComfyUI, {len(manifest) - made} no plano B).",
            artifacts={"images.json": js(manifest), **artifacts},
            evidence=evidence,
        )

    def mock(self, ctx: TaskContext, palette: dict) -> Illustrations:
        return Illustrations(images=[
            Illustration(section_id=sid, alt=f"Ilustração neon representando {title}",
                         concept=f"Horizonte synthwave com cidade neon para '{title}'",
                         svg=neon_art(f"{ctx.mission_id}:{sid}", palette, title))
            for sid, title in self.targets(ctx)])

    async def run(self, ctx: TaskContext) -> AgentResult:
        palette = json.loads(ctx.inputs["design-system.json"])["palette"]
        targets = self.targets(ctx)
        if ctx.settings.image_provider == "comfyui":
            return await self.run_raster(ctx, palette, targets)
        spec = "\n".join(f"- section_id `{sid}`: {title}" for sid, title in targets)
        out = await ctx.think(
            Illustrations, self.system_prompt(ctx),
            self.task_prompt(ctx, f"## Imagens a criar (uma por item)\n{spec}\n\n## Regras do SVG\n"
                             "- Documento completo com xmlns e viewBox=\"0 0 800 500\"; máximo ~60 elementos.\n"
                             "- Use somente as cores da paleta; efeitos de brilho com <filter> (feGaussianBlur).\n"
                             "- Proibido: <script>, <image>, <foreignObject>, eventos on*, links ou fontes externas.\n"
                             "- Represente o tema da seção com formas (não escreva textos longos na imagem)."),
            lambda: self.mock(ctx, palette), effort=self.effort,
        )
        by_section = {i.section_id: i for i in out.images}
        manifest, evidence, artifacts = [], [], {}
        for sid, title in targets:
            item = by_section.get(sid)
            svg, why = sanitize_svg(item.svg) if item else (None, "não entregue pelo modelo")
            fallback = svg is None
            if fallback:
                svg = neon_art(f"{ctx.mission_id}:{sid}", palette, title)
            file = f"img-{slug(sid)}.svg"
            alt = (item.alt if item and item.alt.strip() else f"Ilustração representando {title}")
            manifest.append({"file": file, "section_id": sid, "alt": alt,
                             "concept": item.concept if item else "arte procedural", "svg": svg,
                             "source": "procedural" if fallback else "llm"})
            artifacts[file] = svg
            evidence.append(Evidence(kind="check", title=f"{file} — {'fallback procedural' if fallback else 'SVG do modelo validado'}",
                                     detail=why, passed=not fallback))
        made = sum(1 for m in manifest if m["source"] == "llm")
        return AgentResult(
            summary=f"{len(manifest)} ilustrações SVG ({made} do modelo, {len(manifest) - made} procedurais).",
            artifacts={"images.json": js(manifest), **artifacts},
            evidence=evidence,
        )


# ------------------------------------------------------------------ Desenvolvedor
class Developer(Agent):
    role = "developer"
    name = "Diego"
    title = "Desenvolvedor Front-end"
    description = "Implementa o site em HTML semântico e CSS responsivo a partir do design system e do conteúdo."
    skills = ["HTML semântico", "CSS responsivo", "performance", "acessibilidade"]
    produces = ["index.html", "styles.css", "logo.svg"]
    effort = "high"

    async def run(self, ctx: TaskContext) -> AgentResult:
        content = SiteContent.model_validate_json(ctx.inputs["content.json"])
        design = DesignSystem.model_validate_json(ctx.inputs["design-system.json"])
        company = ctx.brief.company_name
        defect = ctx.is_mock and ctx.settings.mock_inject_defect and ctx.attempt == 1
        # As ilustrações são desenhadas em paralelo; o HTML usa o plano de imagens (mesmos nomes de arquivo).
        plan = image_plan(json.loads(ctx.inputs["sitemap.json"]), company, image_ext(ctx.settings))
        images = {sid: (file, f"Ilustração: {title}") for sid, title, file in plan}
        ctx = dataclasses.replace(ctx, inputs={**ctx.inputs, "images.json": js(
            [{"file": file, "section_id": sid, "alt": alt} for sid, (file, alt) in images.items()])})

        # Duas chamadas menores (HTML, depois CSS) em vez de uma gigante: cabe no contexto de modelos
        # locais e reduz a chance de o modelo degenerar em repetição no fim de respostas longas.
        system = self.system_prompt(ctx)
        reference = site_builder.render_html(content, company, images=images)
        rules = ("## Regras do HTML\n- Entregue só o index.html; o CSS será escrito na próxima etapa.\n"
                 "- Use classes descritivas e os ids do sitemap; nada de estilos inline.\n"
                 "- Use cada imagem de images.json com <img src=\"<file>\" alt=\"<alt>\"> na seção indicada "
                 "(section_id 'hero' vai no destaque principal).\n- Não use JavaScript nem recursos externos.\n")
        markup = await ctx.think(
            SiteMarkup, system,
            self.task_prompt(ctx, rules + "## Estrutura de referência (pode melhorar, mantenha ids, alt e metas)\n"
                             + reference[:6000]),
            lambda: SiteMarkup(html=site_builder.render_html(content, company, defect=defect, images=images),
                               notes="Template one-page: header fixo, hero em destaque, seções em grade e contato."),
            effort=self.effort,
        )
        hooks = site_builder.css_hooks(markup.html)
        style_ctx = dataclasses.replace(ctx, inputs={"design-system.json": ctx.inputs["design-system.json"]})
        styles = await ctx.think(
            SiteStyles, system,
            self.task_prompt(style_ctx, f"## Seletores usados no HTML\n{js(hooks)}\n\n## Regras do CSS\n"
                             "- Entregue só o styles.css, cobrindo esses seletores; mobile first.\n"
                             "- Declare as cores do design system em variáveis no :root e use-as.\n"
                             "- Cada seletor aparece uma única vez. Seja conciso: no máximo ~250 linhas.\n"),
            lambda: SiteStyles(css=site_builder.render_css(design)),
            effort=self.effort,
        )
        css, repeated = site_builder.dedupe_css(styles.css)
        html, css, fixes = site_builder.autofix(markup.html, css, content.seo.description,
                                                {file: alt for file, alt in images.values()})
        logo = site_builder.logo_svg(company, design)
        files = {"index.html": html, "styles.css": css, "logo.svg": logo}
        cleanup = ([Evidence(kind="check", title="CSS com blocos repetidos removidos",
                             detail=f"{repeated} bloco(s) idêntico(s) descartado(s)", passed=False)] if repeated else [])
        cleanup += [Evidence(kind="note", title=f"Correção automática: {f}") for f in fixes]
        return AgentResult(
            summary=f"Site implementado (tentativa {ctx.attempt}): "
            f"{round(sum(len(v) for v in files.values()) / 1024, 1)} KB em {len(files)} arquivos.",
            artifacts=files,
            evidence=[Evidence(kind="file", title=n, detail=f"sha256 {sha(v)[:16]}… · {len(v)} bytes")
                      for n, v in files.items()] + cleanup
            + [Evidence(kind="note", title="Notas", detail=markup.notes)],
        )


# --------------------------------------------------------------------------- QA
BLAME = {
    "seo-title": ["content.json", "index.html"],
    "seo-description": ["content.json", "index.html"],
    "contrast-text": ["design-system.json", "styles.css"],
    "contrast-hero": ["design-system.json", "styles.css"],
    "stylesheet": ["index.html"],
    "nav-style": ["styles.css"],
}


class QA(Agent):
    role = "qa"
    name = "Quésia"
    title = "Analista de Qualidade"
    description = "Executa checklist automatizado de acessibilidade, SEO e performance e emite parecer."
    skills = ["testes automatizados", "WCAG", "SEO técnico", "rastreabilidade"]
    produces = ["qa-report.md"]

    async def run(self, ctx: TaskContext) -> AgentResult:
        sitemap = json.loads(ctx.inputs["sitemap.json"])
        palette = json.loads(ctx.inputs["design-system.json"])["palette"]
        checks = run_checks(ctx.inputs["index.html"], ctx.inputs["styles.css"], [s["id"] for s in sitemap], palette)
        if "images.json" in ctx.inputs:
            files = {i["file"] for i in json.loads(ctx.inputs["images.json"])}
            srcs = set(re.findall(r'<img[^>]*\ssrc="([^"]+)"', ctx.inputs["index.html"]))
            missing = sorted(src for src in srcs - files - {"logo.svg"})
            unused = sorted(files - srcs)
            checks += [
                Check("images-exist", "Imagens referenciadas existem", not missing,
                      "inexistentes: " + ", ".join(missing) if missing else f"{len(srcs)} imagens"),
                Check("images-used", "Ilustrações produzidas foram usadas no site", not unused,
                      "não usadas: " + ", ".join(unused) if unused else f"{len(files)} de {len(files)}", critical=False),
            ]
        failed = [c for c in checks if not c.passed and c.critical]
        passed = not failed
        lines = [f"# Relatório de QA — tentativa {ctx.attempt}\n",
                 f"**Parecer:** {'APROVADO' if passed else 'REPROVADO'}\n",
                 "| Verificação | Resultado | Detalhe |", "|---|---|---|"]
        lines += [f"| {c.title} | {'✅' if c.passed else ('❌' if c.critical else '⚠️')} | {c.detail} |" for c in checks]
        lines.append("\n## Rastreabilidade (seção ↔ critério de aceite)")
        lines += [f"- `#{s['id']}` — Seção '{s['title']}' visível e acessível por âncora" for s in sitemap]
        return AgentResult(
            summary=(f"Aprovado: {len(checks)} verificações executadas." if passed
                     else f"Reprovado: {len(failed)} verificação(ões) crítica(s) falharam."),
            artifacts={"qa-report.md": "\n".join(lines)},
            evidence=[Evidence(kind="check", title=c.title, detail=c.detail, passed=c.passed) for c in checks],
            passed=passed,
            data={"failed": [f"{c.title}: {c.detail}" for c in failed],
                  # Artefatos de origem de cada falha: o orquestrador devolve o trabalho a quem os produziu.
                  "rework_artifacts": sorted({a for c in failed for a in BLAME.get(c.id, ["index.html"])})},
        )


# ------------------------------------------------------------- Engenheiro de Cloud
TERRAFORM = """terraform {{
  required_providers {{ aws = {{ source = "hashicorp/aws", version = "~> 6.0" }} }}
}}

variable "site_name" {{ default = "{name}" }}

resource "aws_s3_bucket" "site" {{
  bucket = "hive-site-${{var.site_name}}"
  tags   = {{ Project = "hive", Mission = "{mission}", CostCenter = "sites" }}
}}

resource "aws_s3_bucket_public_access_block" "site" {{
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}}

resource "aws_cloudfront_origin_access_control" "site" {{
  name                              = "oac-${{var.site_name}}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}}

resource "aws_cloudfront_distribution" "site" {{
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  origin {{
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }}
  default_cache_behavior {{
    target_origin_id       = "s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
  }}
  restrictions {{ geo_restriction {{ restriction_type = "none" }} }}
  viewer_certificate {{ cloudfront_default_certificate = true }}
  tags = {{ Project = "hive", Mission = "{mission}", CostCenter = "sites" }}
}}

output "url" {{ value = "https://${{aws_cloudfront_distribution.site.domain_name}}" }}
"""


def hosting_estimate(page_bytes: int, visits: int = 10_000, pages_per_visit: float = 1.5) -> dict:
    """Estimativa simplificada (us-east-1, preços públicos de referência; conferir na AWS Pricing Calculator)."""
    views = visits * pages_per_visit
    gb_out = views * page_bytes / 1e9
    requests = views * 3  # html + css + logo
    s3_storage = 0.023 * page_bytes / 1e9
    cf_transfer = 0.085 * gb_out
    cf_requests = 0.01 * requests / 10_000
    route53 = 0.50
    list_price = s3_storage + cf_transfer + cf_requests + route53
    return {
        "assumptions": {"visits_per_month": visits, "pages_per_visit": pages_per_visit,
                        "page_weight_kb": round(page_bytes / 1024, 1), "region": "us-east-1"},
        "items": [
            {"service": "S3 (armazenamento)", "usd": round(s3_storage, 4)},
            {"service": "CloudFront (transferência)", "usd": round(cf_transfer, 4), "usage": f"{gb_out:.3f} GB"},
            {"service": "CloudFront (requisições HTTPS)", "usd": round(cf_requests, 4), "usage": f"{int(requests)}"},
            {"service": "Route 53 (zona hospedada)", "usd": route53},
            {"service": "ACM (certificado TLS)", "usd": 0.0},
        ],
        "monthly_usd_list_price": round(list_price, 2),
        # O free tier perpétuo do CloudFront (1 TB + 10 mi requisições/mês) cobre este volume.
        "monthly_usd_with_free_tier": round(s3_storage + route53, 2),
    }


class CloudEngineer(Agent):
    role = "cloud_engineer"
    name = "Nuvem"
    title = "Engenheiro de Cloud/DevOps"
    description = "Provisiona a infraestrutura como código, publica a solução e define rollback e monitoramento."
    skills = ["Terraform", "AWS", "CI/CD", "observabilidade"]
    produces = ["main.tf", "deployment.md", "hosting-cost.json"]

    def mock(self, ctx: TaskContext) -> DeployPlan:
        return DeployPlan(
            strategy="Blue/green por versão de objeto: sobe arquivos novos no S3 e invalida o cache do CloudFront.",
            steps=["terraform init && terraform apply", "aws s3 sync ./site s3://<bucket> --delete",
                   "aws cloudfront create-invalidation --paths '/*'", "Smoke test: HTTP 200 em / e /styles.css"],
            rollback=["Reverter para a versão anterior dos objetos (S3 versioning)", "Invalidar o cache novamente"],
            monitoring=["Alarme CloudWatch para taxa de 5xx > 1%", "Relatório mensal de custo por tag CostCenter=sites"],
        )

    async def run(self, ctx: TaskContext) -> AgentResult:
        plan = await ctx.think(DeployPlan, self.system_prompt(ctx), self.task_prompt(ctx), lambda: self.mock(ctx))
        site: dict[str, bytes] = {n: ctx.inputs[n].encode() for n in ("index.html", "styles.css", "logo.svg")}
        for image in json.loads(ctx.inputs.get("images.json", "[]")):
            site[image["file"]] = (image["svg"].encode() if "svg" in image
                                   else await ctx.services.artifact_bytes(ctx.mission_id, image["file"]))
        target = ctx.services.site_dir(ctx.mission_id)
        target.mkdir(parents=True, exist_ok=True)
        for name, body in site.items():
            (target / name).write_bytes(body)
        url = ctx.services.site_url(ctx.mission_id)
        deployed_ok = all((target / n).read_bytes() == b for n, b in site.items())
        estimate = hosting_estimate(sum(len(b) for b in site.values()))
        md = [f"# Implantação — {ctx.brief.company_name}\n",
              f"**Ambiente local:** {url}\n", f"**Estratégia:** {plan.strategy}\n", "## Passos (AWS)"]
        md += [f"{i}. `{s}`" if s.startswith(("terraform", "aws")) else f"{i}. {s}" for i, s in enumerate(plan.steps, 1)]
        md += ["\n## Rollback"] + [f"- {r}" for r in plan.rollback]
        md += ["\n## Monitoramento"] + [f"- {m}" for m in plan.monitoring]
        md += ["\n## Integridade dos arquivos publicados"] + [f"- `{n}` sha256 `{sha(b)}`" for n, b in site.items()]
        return AgentResult(
            summary=f"Publicado em {url}. Hospedagem estimada: US$ {estimate['monthly_usd_with_free_tier']}/mês "
            f"(US$ {estimate['monthly_usd_list_price']} sem free tier).",
            artifacts={"main.tf": TERRAFORM.format(name=re.sub(r"[^a-z0-9-]", "", slug(ctx.brief.company_name))[:40],
                                                   mission=ctx.mission_id),
                       "deployment.md": "\n".join(md), "hosting-cost.json": js(estimate)},
            evidence=[
                Evidence(kind="link", title="Site publicado", detail=url),
                Evidence(kind="check", title="Arquivos publicados conferem com os artefatos aprovados no QA",
                         passed=deployed_ok),
                Evidence(kind="cost", title="Hospedagem estimada/mês",
                         detail=f"US$ {estimate['monthly_usd_with_free_tier']} (free tier) · "
                         f"US$ {estimate['monthly_usd_list_price']} (preço de tabela)"),
            ],
            data={"url": url, "hosting": estimate},
        )


# ------------------------------------------------------------------------ FinOps
class FinOps(Agent):
    role = "finops"
    name = "Fábio"
    title = "Analista FinOps"
    description = "Apura o custo de produção da missão por agente e modelo e projeta o custo de operação."
    skills = ["FinOps", "showback", "otimização de custos", "AWS Pricing"]
    produces = ["finops-report.md"]
    effort = "low"

    def mock(self, ctx: TaskContext, breakdown: dict) -> FinOpsAdvice:
        top = max(breakdown["by_agent"], key=lambda a: a["cost_usd"], default=None)
        recs = ["Manter QA determinístico (custo zero de LLM) e usar LLM só para julgamento subjetivo.",
                "Habilitar prompt caching no system prompt dos agentes para reduzir tokens de entrada.",
                "Rotear tarefas simples (briefing, FinOps) para modelo menor ou LLM local."]
        if top:
            recs.insert(0, f"Maior custo: {top['agent']} ({top['share']}%). Avaliar esforço/modelo dessa etapa.")
        return FinOpsAdvice(summary="Custo de produção dentro do orçamento; hospedagem coberta pelo free tier.",
                            recommendations=recs)

    async def run(self, ctx: TaskContext) -> AgentResult:
        b = await ctx.services.cost_breakdown(ctx.mission_id)
        hosting = json.loads(ctx.inputs["hosting-cost.json"])
        advice = await ctx.think(
            FinOpsAdvice, self.system_prompt(ctx),
            self.task_prompt(ctx, f"## Custos apurados\n{js(b)}"), lambda: self.mock(ctx, b), effort=self.effort,
        )
        sim = " (simulado: custo-sombra do modelo de referência)" if b["simulated"] else ""
        md = [f"# Relatório FinOps — {ctx.brief.company_name}\n", advice.summary, "",
              f"**Custo de produção da missão:** US$ {b['total_usd']:.4f}{sim}",
              f"**Orçamento:** US$ {b['budget_usd']:.2f} — consumido {b['budget_used_pct']}%",
              f"**Tokens:** {b['input_tokens']:,} entrada · {b['output_tokens']:,} saída · {b['calls']} chamadas\n",
              "## Por agente", "| Agente | Chamadas | Tokens (in/out) | Custo US$ | % |", "|---|---|---|---|---|"]
        md += [f"| {a['agent']} | {a['calls']} | {a['input_tokens']:,}/{a['output_tokens']:,} | "
               f"{a['cost_usd']:.4f} | {a['share']}% |" for a in b["by_agent"]]
        md += ["\n## Por modelo", "| Provedor | Modelo | Chamadas | Custo US$ |", "|---|---|---|---|"]
        md += [f"| {m['provider']} | {m['model']} | {m['calls']} | {m['cost_usd']:.4f} |" for m in b["by_model"]]
        md += ["\n## Operação mensal projetada (hospedagem)", "| Serviço | US$/mês |", "|---|---|"]
        md += [f"| {i['service']} | {i['usd']:.4f} |" for i in hosting["items"]]
        md += [f"\n**Total:** US$ {hosting['monthly_usd_list_price']}/mês (tabela) · "
               f"US$ {hosting['monthly_usd_with_free_tier']}/mês (com free tier CloudFront)",
               f"Premissas: {js(hosting['assumptions'])}", "\n## Recomendações"]
        md += [f"- {r}" for r in advice.recommendations]
        return AgentResult(
            summary=f"Produção: US$ {b['total_usd']:.4f}{' (simulado)' if b['simulated'] else ''} · "
            f"Operação: ~US$ {hosting['monthly_usd_list_price']}/mês.",
            artifacts={"finops-report.md": "\n".join(md)},
            evidence=[
                Evidence(kind="cost", title="Custo de produção", detail=f"US$ {b['total_usd']:.4f}{sim}"),
                Evidence(kind="check", title="Dentro do orçamento", detail=f"{b['budget_used_pct']}% usado",
                         passed=b["total_usd"] <= b["budget_usd"]),
                Evidence(kind="cost", title="Operação mensal", detail=f"US$ {hosting['monthly_usd_list_price']}"),
            ],
            data={"production_usd": b["total_usd"], "monthly_usd": hosting["monthly_usd_list_price"]},
        )


SPECIALISTS: list[Agent] = [ProductOwner(), Architect(), Designer(), Copywriter(), FactChecker(), Illustrator(), Developer(), QA(),
                            CloudEngineer(), FinOps()]
