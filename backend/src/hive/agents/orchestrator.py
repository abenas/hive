"""Agente orquestrador: interpreta o pedido, planeja o DAG de tarefas e valida o DoR."""

import re

from hive.core.models import Brief, Plan, PlannedTask, Story

CARD = {
    "role": "orchestrator",
    "name": "Atlas",
    "title": "Orquestrador",
    "description": (
        "Interpreta a missão, monta o briefing, quebra o trabalho em histórias com "
        "Definition of Ready, delega aos especialistas e coordena retrabalho."
    ),
    "skills": ["interpretação de pedidos", "planejamento", "delegação", "governança"],
    "produces": ["brief", "plan"],
}

SYSTEM = (
    "Você é Atlas, o agente orquestrador de uma agência digital operada por agentes de IA. "
    "Você não executa o trabalho: você entende o pedido, estrutura um briefing claro e "
    "delega histórias bem descritas aos especialistas. Escreva em português do Brasil."
)

DEFAULT_SECTIONS = ["Sobre", "Serviços", "Diferenciais", "Depoimentos", "Contato"]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .,;:\"'")


def heuristic_brief(request: str) -> Brief:
    """Extração por regras usada no modo mock (sem LLM)."""
    text = request.replace("\n", " ")
    company = re.search(
        # Palavras capitalizadas, admitindo conectores ("Sabor da Vila", "Silva & Filhos").
        r"(?:empresa|marca|cliente|negócio)\s+(?:chamada\s+)?[\"“]?"
        r"([A-ZÀ-Ú0-9][\w&.\-À-ú]*(?:\s+(?:(?:da|de|do|das|dos|e|&)\s+)?[A-ZÀ-Ú0-9][\w&.\-À-ú]*)*)",
        text,
    )
    segment = re.search(
        r"(?:segmento|ramo|setor|área)\s+(?:de\s+|do\s+|da\s+|dos\s+|das\s+)?"
        r"([\w\-À-ú ]{2,40}?)(?=,|\.|;|$|\s+(?:e|apresente|com|que|para)\b)",
        text,
        re.IGNORECASE,
    )
    sections: list[str] = []
    if m := re.search(r"(?:apresente|apresentando|com as seções|contendo|mostre)\s+(.+?)(?:\.|$)", text, re.I):
        sections = [_clean(s).capitalize() for s in re.split(r",|\se\s", m.group(1)) if _clean(s)]
    contact = ", ".join(re.findall(r"(whatsapp|instagram|e-?mail|telefone|endereço)", text, re.I))
    assumptions = []
    if not company:
        assumptions.append("Nome da empresa não informado; usado 'Empresa Exemplo'.")
    if not segment:
        assumptions.append("Segmento não informado; tratado como serviços em geral.")
    if not sections:
        assumptions.append("Seções não informadas; adotado conjunto padrão de site institucional.")
    return Brief(
        company_name=_clean(company.group(1)) if company else "Empresa Exemplo",
        segment=_clean(segment.group(1)).lower() if segment else "serviços",
        audience="Clientes potenciais da região buscando o serviço online",
        goals=["Apresentar a empresa com credibilidade", "Gerar contatos qualificados"],
        sections=sections[:8] or DEFAULT_SECTIONS,
        tone="Profissional, próximo e confiante",
        style="Moderno, limpo, com boa hierarquia visual",
        contact=contact,
        assumptions=assumptions + ["Site institucional de página única (one-page), responsivo."],
    )


def interpret_prompt(request: str) -> str:
    return (
        "Transforme o pedido abaixo em um briefing estruturado para um site institucional. "
        "Preencha lacunas com premissas razoáveis e registre-as em `assumptions`.\n\n"
        f"Pedido:\n{request}"
    )


def template_plan(brief: Brief) -> Plan:
    """Fluxo padrão do pacote 'Agência Digital'. Também é o fallback do planejador."""
    sections = ", ".join(brief.sections)
    t = PlannedTask
    tasks = [
        t(key="backlog", agent="product_owner", depends_on=[], story=Story(
            title="Backlog e mapa do site",
            user_story=f"Como dono da {brief.company_name}, quero um backlog priorizado e o mapa "
            "do site, para que o time saiba exatamente o que construir.",
            acceptance_criteria=[
                f"Mapa do site cobre as seções: {sections}",
                "Cada história tem critérios de aceite verificáveis",
                "KPIs de sucesso definidos",
            ],
            inputs_required=[], outputs_expected=["backlog.md", "sitemap.json"])),
        t(key="architecture", agent="architect", depends_on=["backlog"], story=Story(
            title="Arquitetura da solução",
            user_story="Como time de engenharia, queremos uma arquitetura simples, segura e "
            "barata para hospedar o site, para entregar rápido e com baixo custo.",
            acceptance_criteria=["Componentes e serviços AWS definidos", "ADRs registrados",
                                 "Requisitos não funcionais explícitos"],
            inputs_required=["sitemap.json"], outputs_expected=["architecture.md"])),
        t(key="design", agent="designer", depends_on=["backlog"], story=Story(
            title="Identidade visual e design system",
            user_story=f"Como visitante, quero um visual coerente com o segmento de "
            f"{brief.segment}, para confiar na empresa.",
            acceptance_criteria=["Paleta com contraste WCAG AA (≥ 4.5:1) para texto",
                                 "Tipografia e espaçamentos definidos", "Wireframe por seção"],
            inputs_required=["sitemap.json"], outputs_expected=["design-system.json", "wireframe.md"])),
        t(key="content", agent="copywriter", depends_on=["backlog"], story=Story(
            title="Conteúdo e SEO",
            user_story="Como visitante, quero textos claros e persuasivos, para entender a "
            "proposta de valor e entrar em contato.",
            acceptance_criteria=["Texto para todas as seções do mapa do site",
                                 "Título SEO ≤ 60 caracteres e descrição ≤ 160", "CTA claro"],
            inputs_required=["sitemap.json", "backlog.md"], outputs_expected=["content.json"])),
        t(key="factcheck", agent="fact_checker", depends_on=["content"], story=Story(
            title="Verificação de fatos do conteúdo",
            user_story=f"Como dono da {brief.company_name}, quero que o site só afirme o que é verdade sobre a "
            "empresa, para não expor o negócio a informações inventadas.",
            acceptance_criteria=["Toda afirmação factual tem fonte no pedido ou no briefing",
                                 "Anos, fundadores, números e prêmios sem fonte são removidos ou reescritos",
                                 "Pendências remanescentes sinalizadas para decisão humana"],
            inputs_required=["content.json"], outputs_expected=["fact-check.md"])),
        t(key="illustrations", agent="illustrator", depends_on=["design", "factcheck"], story=Story(
            title="Ilustrações do site",
            user_story="Como visitante, quero imagens que representem cada parte do conteúdo, para "
            "entender a proposta de forma visual e memorável.",
            acceptance_criteria=["Uma ilustração para o destaque e para cada seção principal",
                                 "Cores e estilo coerentes com o design system",
                                 "SVG seguro (sem scripts/recursos externos) e com texto alternativo"],
            inputs_required=["design-system.json", "content.json", "sitemap.json"],
            outputs_expected=["images.json"])),
        t(key="build", agent="developer", depends_on=["architecture", "design", "factcheck"], story=Story(
            title="Implementação do site",
            user_story="Como visitante, quero um site rápido e responsivo, para navegar bem no "
            "celular e no computador.",
            acceptance_criteria=["HTML semântico com uma única <h1>", "Meta tags de SEO e viewport",
                                 "Imagens com texto alternativo", "Todas as seções do mapa presentes"],
            inputs_required=["architecture.md", "design-system.json", "content.json", "sitemap.json"],
            outputs_expected=["index.html", "styles.css", "logo.svg"])),
        t(key="qa", agent="qa", depends_on=["build", "illustrations"], story=Story(
            title="Verificação de qualidade",
            user_story="Como cliente, quero garantia de que o site atende aos critérios de aceite "
            "antes de ir ao ar.",
            acceptance_criteria=["Checklist de acessibilidade, SEO e performance executado",
                                 "Rastreabilidade seção↔critério de aceite", "Parecer aprovado/reprovado"],
            inputs_required=["index.html", "styles.css", "content.json", "sitemap.json", "design-system.json",
                             "images.json"],
            outputs_expected=["qa-report.md"])),
        t(key="deploy", agent="cloud_engineer", depends_on=["qa"], story=Story(
            title="Implantação",
            user_story="Como cliente, quero o site publicado com HTTPS e CDN, para que esteja "
            "disponível ao público.",
            acceptance_criteria=["Site publicado e acessível", "IaC versionada (Terraform)",
                                 "Plano de rollback e estimativa de custo de hospedagem"],
            inputs_required=["index.html", "styles.css", "logo.svg", "images.json", "architecture.md", "qa-report.md"],
            outputs_expected=["main.tf", "deployment.md", "hosting-cost.json"])),
        t(key="finops", agent="finops", depends_on=["deploy"], story=Story(
            title="Relatório FinOps",
            user_story="Como dono do produto, quero saber quanto custou produzir e quanto custará "
            "manter a solução, para decidir com dados.",
            acceptance_criteria=["Custo por agente e por modelo", "Consumo do orçamento da missão",
                                 "Custo mensal projetado e recomendações"],
            inputs_required=["deployment.md", "hosting-cost.json"], outputs_expected=["finops-report.md"])),
    ]
    return Plan(
        summary=f"Site institucional one-page para {brief.company_name} ({brief.segment}) em "
        f"{len(tasks)} etapas, do backlog à implantação com relatório FinOps.",
        tasks=tasks,
    )


def plan_prompt(brief: Brief, cards: list[dict], reference: Plan) -> str:
    roster = "\n".join(f"- {c['role']}: {c['description']} Produz: {', '.join(c['produces'])}" for c in cards)
    return (
        "Monte o plano de execução (DAG) para o briefing abaixo. Use apenas os agentes listados, "
        "com os mesmos nomes de artefatos. Cada tarefa precisa de uma história no padrão DoR: "
        "`inputs_required` só pode citar artefatos produzidos por tarefas das quais ela depende "
        "(direta ou indiretamente). Adapte títulos, histórias e critérios de aceite ao cliente.\n\n"
        f"## Agentes disponíveis\n{roster}\n\n"
        f"## Briefing\n{brief.model_dump_json(indent=2)}\n\n"
        f"## Plano de referência (adapte; mantenha a estrutura)\n{reference.model_dump_json(indent=2)}"
    )


def validate_plan(plan: Plan, roles: set[str]) -> list[str]:
    """Valida papéis, dependências, ciclos e DoR (insumos alcançáveis). Retorna problemas."""
    problems: list[str] = []
    by_key = {t.key: t for t in plan.tasks}
    if len(by_key) != len(plan.tasks):
        problems.append("Há chaves de tarefa duplicadas.")
    for t in plan.tasks:
        if t.agent not in roles:
            problems.append(f"Tarefa '{t.key}' usa agente desconhecido '{t.agent}'.")
        for d in t.depends_on:
            if d not in by_key:
                problems.append(f"Tarefa '{t.key}' depende de '{d}', que não existe.")

    if problems:
        return problems

    # Ordenação topológica (Kahn): se sobrar tarefa, há ciclo.
    indegree = {k: len(t.depends_on) for k, t in by_key.items()}
    order = [k for k, n in indegree.items() if n == 0]
    for k in order:
        for t in plan.tasks:
            if k in t.depends_on:
                indegree[t.key] -= 1
                if indegree[t.key] == 0:
                    order.append(t.key)
    if len(order) != len(by_key):
        return problems + ["O plano contém ciclo de dependências."]

    ancestors: dict[str, set[str]] = {}
    for k in order:
        deps = by_key[k].depends_on
        ancestors[k] = set(deps).union(*(ancestors[d] for d in deps))

    for t in plan.tasks:
        available = {o for a in ancestors[t.key] for o in by_key[a].story.outputs_expected}
        missing = [i for i in t.story.inputs_required if i not in available]
        if missing:
            problems.append(f"DoR de '{t.key}': insumos sem produtor upstream: {', '.join(missing)}.")
    return problems
