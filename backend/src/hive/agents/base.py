"""Contrato dos agentes especializados.

Cada agente recebe um TaskContext (história DoR + insumos produzidos pelas dependências)
e devolve um AgentResult (artefatos + evidências). Toda chamada de LLM passa por
`ctx.think`, que mede tokens/custo, aplica orçamento e registra na trilha de auditoria.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from hive.agents import playbooks as pb
from hive.config import Settings
from hive.core.models import AgentResult, Brief, Story

T = TypeVar("T", bound=BaseModel)


class Think(Protocol):
    async def __call__(
        self, schema: type[T], system: str, prompt: str, mock: Callable[[], T], effort: str = ...
    ) -> T: ...


class Services(Protocol):
    """Capacidades da plataforma expostas aos agentes (sem acesso direto ao banco)."""

    async def cost_breakdown(self, mission_id: str) -> dict[str, Any]: ...

    def site_dir(self, mission_id: str): ...

    def site_url(self, mission_id: str) -> str: ...

    async def artifact_bytes(self, mission_id: str, name: str) -> bytes: ...

    async def render_images(self, mission_id: str, task_id: str, role: str,
                            jobs: list[tuple[str, str, int]]) -> list: ...


@dataclass
class TaskContext:
    mission_id: str
    task_id: str
    request: str
    brief: Brief
    story: Story
    inputs: dict[str, str]
    attempt: int
    feedback: str | None
    settings: Settings
    services: Services
    think: Think
    emit: Callable[[str, str, dict | None], Awaitable[None]]
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_mock(self) -> bool:
        return self.extra.get("provider") == "mock"


class Agent(ABC):
    role: str
    name: str
    title: str
    description: str
    skills: list[str]
    produces: list[str]
    effort: str = "medium"

    def card(self) -> dict[str, Any]:
        """Cartão do agente (inspirado no Agent Card do protocolo A2A)."""
        return {
            "role": self.role,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "skills": self.skills,
            "produces": self.produces,
            "playbooks": [{"name": p.name, "title": p.title, "version": p.version} for p in self.playbooks()],
        }

    def playbooks(self) -> list[pb.Playbook]:
        return pb.for_role(self.role)

    def system_prompt(self, ctx: TaskContext) -> str:
        return (
            f"Você é {self.name}, {self.title} numa agência digital operada por agentes de IA. "
            f"{self.description} Escreva em português do Brasil. "
            "Siga a história e os critérios de aceite recebidos; não invente fatos sobre o "
            "cliente além do briefing — quando precisar assumir algo, deixe explícito."
        ) + "".join(f"\n\n## Playbook: {p.title} (v{p.version})\n{p.body}" for p in self.playbooks())

    def task_prompt(self, ctx: TaskContext, extra: str = "") -> str:
        parts = [
            f"## Pedido original\n{ctx.request}",
            f"## Briefing\n{ctx.brief.model_dump_json(indent=2)}",
            f"## Sua história\n{ctx.story.model_dump_json(indent=2)}",
        ]
        for name, content in ctx.inputs.items():
            parts.append(f"## Insumo: {name}\n{content[:12000]}")
        if ctx.feedback:
            parts.append(f"## Apontamentos da revisão anterior (corrija todos)\n{ctx.feedback}")
        if extra:
            parts.append(extra)
        return "\n\n".join(parts)

    @abstractmethod
    async def run(self, ctx: TaskContext) -> AgentResult: ...
