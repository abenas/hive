"""Configuração 12-factor: tudo vem de variáveis de ambiente (prefixo HIVE_) ou .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["mock", "anthropic", "bedrock", "ollama"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HIVE_", env_file=".env", extra="ignore")

    env: str = "local"
    data_dir: Path = Path("./data")
    database_url: str = ""  # vazio => SQLite em data_dir; em AWS: postgresql+asyncpg://...
    public_base_url: str = "http://localhost:8001"
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- LLM -------------------------------------------------------------
    # Provedor padrão para todos os agentes. Pode ser sobrescrito por papel em `routing`.
    llm_provider: ProviderName = "mock"
    # Roteamento por papel: {"orchestrator": "anthropic:claude-opus-5-5", "developer": "ollama:qwen3:14b"}
    routing: dict[str, str] = Field(default_factory=dict)
    model_orchestrator: str = "claude-opus-5-5"
    model_worker: str = "claude-sonnet-5-5"
    fallback_model: str = "claude-opus-5"  # usado se o modelo principal recusar (stop_reason=refusal)
    aws_region: str = "us-east-1"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gpt-oss:20b"
    ollama_num_ctx: int = 16384
    ollama_max_parallel: int = 1  # chamadas simultâneas; alinhe com OLLAMA_NUM_PARALLEL do servidor
    ollama_num_predict: int = 8192  # teto de tokens gerados por chamada: evita geração sem fim
    ollama_think: bool | None = None  # modelos com raciocínio (qwen3, gpt-oss): None = padrão do modelo

    # --- Imagens --------------------------------------------------------
    # svg: ilustrações vetoriais escritas pelo LLM | comfyui: SDXL local (ComfyUI com ROCm no Windows)
    image_provider: Literal["svg", "comfyui"] = "svg"
    comfyui_url: str = "http://localhost:8188"
    comfyui_checkpoint: str = "sd_xl_base_1.0.safetensors"
    comfyui_steps: int = 28
    comfyui_cfg: float = 6.5
    comfyui_width: int = 1216  # SDXL rende melhor perto de 1 megapixel
    comfyui_height: int = 832
    image_max_width: int = 1200  # largura final publicada (WebP)
    image_quality: int = 82
    # GPU única para LLM e imagens: a geração de imagens pede uso exclusivo e descarrega o LLM antes.
    gpu_shared: bool = True

    # FinOps de LLM local: custo de energia estimado da GPU durante a inferência
    local_gpu_watts: float = 304.0  # TBP da RX 9070 XT
    energy_price_per_kwh_usd: float = 0.16

    # Mock: simula latência e custo "sombra" (quanto custaria num modelo real)
    mock_latency_s: float = 1.2
    mock_shadow_model: str = "claude-sonnet-5-5"
    mock_inject_defect: bool = True  # 1ª versão do dev falha no QA para demonstrar o ciclo de retrabalho

    # --- Governança ------------------------------------------------------
    mission_budget_usd: float = 3.0
    max_rework_attempts: int = 2
    auto_approve: bool = False  # True pula os portões humanos (útil em testes)

    # --- Canais ----------------------------------------------------------
    telegram_bot_token: str | None = None

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite+aiosqlite:///{(self.data_dir / 'hive.db').resolve()}"

    def route(self, role: str) -> tuple[ProviderName, str]:
        """Resolve (provedor, modelo) para um papel de agente."""
        if spec := self.routing.get(role):
            provider, _, model = spec.partition(":")
            return provider, model  # type: ignore[return-value]
        provider = self.llm_provider
        if provider == "ollama":
            return provider, self.ollama_model
        model = self.model_orchestrator if role == "orchestrator" else self.model_worker
        if provider == "bedrock":
            model = f"anthropic.{model}"
        return provider, model


@lru_cache
def get_settings() -> Settings:
    return Settings()
