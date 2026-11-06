"""Contratos de domínio: missão, briefing, plano, histórias (DoR) e resultado de agente."""

from enum import StrEnum

from pydantic import BaseModel, Field


class MissionStatus(StrEnum):
    RECEIVED = "received"
    INTERPRETING = "interpreting"
    PLANNING = "planning"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    EXECUTING = "executing"
    AWAITING_DEPLOY_APPROVAL = "awaiting_deploy_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Gate(StrEnum):
    PLAN = "plan"
    DEPLOY = "deploy"


class Brief(BaseModel):
    """Interpretação estruturada do pedido do usuário, feita pelo orquestrador."""

    company_name: str = Field(description="Nome da empresa/cliente")
    segment: str = Field(description="Segmento de mercado da empresa")
    audience: str = Field(description="Público-alvo principal")
    goals: list[str] = Field(description="Objetivos de negócio do site")
    sections: list[str] = Field(description="Seções/conteúdos que o site deve apresentar")
    tone: str = Field(description="Tom de voz da comunicação")
    style: str = Field(description="Direção visual desejada")
    contact: str = Field(description="Canais de contato mencionados, ou vazio")
    assumptions: list[str] = Field(description="Premissas assumidas onde o pedido foi omisso")


class Story(BaseModel):
    """História no padrão Definition of Ready: só entra em execução se os insumos existirem."""

    title: str
    user_story: str = Field(description="Como <persona>, quero <ação>, para <valor>")
    acceptance_criteria: list[str]
    inputs_required: list[str] = Field(description="Artefatos que precisam existir antes de iniciar")
    outputs_expected: list[str] = Field(description="Artefatos que a tarefa deve entregar")


class PlannedTask(BaseModel):
    key: str = Field(description="Identificador curto e único, ex.: 'design'")
    agent: str = Field(description="Papel do agente especializado responsável")
    depends_on: list[str]
    story: Story


class Plan(BaseModel):
    summary: str
    tasks: list[PlannedTask]


class Evidence(BaseModel):
    kind: str  # check | metric | file | cost | link | note
    title: str
    detail: str = ""
    passed: bool | None = None


class AgentResult(BaseModel):
    summary: str
    artifacts: dict[str, str | bytes] = Field(default_factory=dict)  # nome -> conteúdo (texto ou binário)
    evidence: list[Evidence] = Field(default_factory=list)
    passed: bool = True  # agentes de verificação (QA) podem reprovar
    data: dict = Field(default_factory=dict)  # métricas estruturadas (ex.: custos estimados)
