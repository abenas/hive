"""Schemas de saída estruturada dos especialistas (usados como contrato com o LLM)."""

from pydantic import BaseModel, Field


class BacklogStory(BaseModel):
    title: str
    user_story: str
    acceptance_criteria: list[str]
    priority: str = Field(description="MUST, SHOULD ou COULD")


class Epic(BaseModel):
    title: str
    stories: list[BacklogStory]


class PageSection(BaseModel):
    id: str = Field(description="Âncora em minúsculas, sem acento, ex.: 'servicos'")
    title: str
    purpose: str


class Backlog(BaseModel):
    epics: list[Epic]
    sitemap: list[PageSection] = Field(description="Seções da página, sem incluir hero e contato")
    kpis: list[str]


class Component(BaseModel):
    name: str
    aws_service: str
    purpose: str


class ADR(BaseModel):
    title: str
    decision: str
    rationale: str
    alternatives: list[str]


class Architecture(BaseModel):
    overview: str
    components: list[Component]
    adrs: list[ADR]
    nfrs: list[str]


class Palette(BaseModel):
    primary: str = Field(description="Hex #RRGGBB")
    on_primary: str = Field(description="Cor de texto sobre primary, hex")
    secondary: str
    accent: str
    background: str
    surface: str
    text: str
    muted: str


class SectionLayout(BaseModel):
    section_id: str
    layout: str


class DesignSystem(BaseModel):
    palette: Palette
    font_heading: str
    font_body: str
    radius_px: int
    style_notes: str
    layouts: list[SectionLayout]


class SEO(BaseModel):
    title: str = Field(description="Até 60 caracteres")
    description: str = Field(description="Até 160 caracteres")
    keywords: list[str]


class Hero(BaseModel):
    headline: str
    subheadline: str
    cta: str


class Item(BaseModel):
    title: str
    text: str


class ContentSection(BaseModel):
    id: str = Field(description="Mesmo id do sitemap")
    title: str
    body: str
    items: list[Item]


class Contact(BaseModel):
    headline: str
    text: str
    channels: list[str]


class SiteContent(BaseModel):
    seo: SEO
    hero: Hero
    sections: list[ContentSection]
    contact: Contact
    footer: str


class SiteMarkup(BaseModel):
    html: str = Field(description="Documento index.html completo; referencia styles.css e logo.svg")
    notes: str = Field(description="Decisões de implementação")


class SiteStyles(BaseModel):
    css: str = Field(description="Conteúdo completo de styles.css, conciso e sem regras repetidas")


class DeployPlan(BaseModel):
    strategy: str
    steps: list[str]
    rollback: list[str]
    monitoring: list[str]


class FinOpsAdvice(BaseModel):
    summary: str
    recommendations: list[str]


class Illustration(BaseModel):
    section_id: str = Field(description="'hero' ou o id da seção do sitemap que a imagem representa")
    alt: str = Field(description="Texto alternativo descritivo, em português")
    concept: str = Field(description="Ideia visual da imagem em uma frase")
    svg: str = Field(description="Documento SVG completo e autocontido (viewBox 0 0 800 500)")


class Illustrations(BaseModel):
    images: list[Illustration]


class Claim(BaseModel):
    text: str = Field(description="Trecho exato do conteúdo que faz a afirmação")
    kind: str = Field(description="data, origem, pessoa, número, prêmio, preço, local, certificação ou outro")
    supported: bool = Field(description="true somente se o pedido ou o briefing sustentam a afirmação")
    reason: str = Field(description="Por que está ou não sustentada, em uma frase")


class FactReport(BaseModel):
    claims: list[Claim]


class ImagePrompt(BaseModel):
    section_id: str = Field(description="'hero' ou o id da seção do sitemap")
    alt: str = Field(description="Texto alternativo em português descrevendo o que a imagem mostra")
    prompt: str = Field(description="Prompt em inglês para SDXL: assunto, composição, luz, estilo, paleta")
    negative: str = Field(description="Prompt negativo em inglês: o que evitar")


class ImagePrompts(BaseModel):
    images: list[ImagePrompt]
