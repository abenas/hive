"""Provedores de LLM atrás de uma única interface de saída estruturada.

- mock: determinístico, custo zero (reporta custo "sombra" estimado)
- anthropic: Claude via API Anthropic
- bedrock: Claude via Amazon Bedrock (cliente Mantle, autenticação IAM)
- ollama: modelo local (ex.: gpt-oss:20b / qwen3:14b numa GPU de 16 GB)
"""

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
import httpx
from pydantic import BaseModel, ValidationError

from hive.config import Settings
from hive.llm.gpu import GpuArbiter
from hive.llm.pricing import energy_cost, token_cost

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMUsage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    latency_ms: int
    simulated: bool = False
    queue_ms: int = 0  # espera por uma vaga no provedor (não conta como tempo de geração)


class Provider(Protocol):
    name: str

    async def structured(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: type[T],
        effort: str,
        mock: Callable[[], T],
    ) -> tuple[T, LLMUsage]: ...


class MockProvider:
    """Executa a resposta simulada do agente. Útil para demo, testes e CI sem custo."""

    name = "mock"

    def __init__(self, settings: Settings):
        self.s = settings

    async def structured(self, *, model, system, prompt, schema, effort, mock):
        start = time.perf_counter()
        await asyncio.sleep(self.s.mock_latency_s)
        out = mock()
        tokens_in = (len(system) + len(prompt)) // 4
        tokens_out = len(out.model_dump_json()) // 4
        shadow = self.s.mock_shadow_model
        return out, LLMUsage(
            provider=self.name,
            model=f"mock({shadow})",
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cache_read_tokens=0,
            cost_usd=token_cost(shadow, tokens_in, tokens_out),
            latency_ms=int((time.perf_counter() - start) * 1000),
            simulated=True,
        )


class ClaudeProvider:
    """Claude com saída estruturada validada por Pydantic (`messages.parse`)."""

    def __init__(self, settings: Settings, bedrock: bool = False):
        self.s = settings
        self.bedrock = bedrock
        self.name = "bedrock" if bedrock else "anthropic"
        self.client = (
            anthropic.AsyncAnthropicBedrockMantle(aws_region=settings.aws_region)
            if bedrock
            else anthropic.AsyncAnthropic()
        )

    async def _call(self, model: str, system: str, prompt: str, schema: type[T], effort: str):
        return await self.client.messages.parse(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
            output_config={"effort": effort},
        )

    async def structured(self, *, model, system, prompt, schema, effort, mock):
        start = time.perf_counter()
        try:
            response = await self._call(model, system, prompt, schema, effort)
            if response.stop_reason == "refusal":
                # Fallback do lado do cliente: tenta uma vez com o modelo alternativo configurado.
                fallback = self.s.fallback_model
                model = f"anthropic.{fallback}" if self.bedrock else fallback
                response = await self._call(model, system, prompt, schema, effort)
        except anthropic.RateLimitError as e:
            raise LLMError(f"Limite de taxa atingido em {self.name}: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Erro {e.status_code} em {self.name}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Falha de conexão com {self.name}") from e

        if response.stop_reason == "refusal":
            raise LLMError("O modelo recusou a solicitação (inclusive no fallback).")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError(f"Resposta incompleta (stop_reason={response.stop_reason}).")

        u = response.usage
        cache_read = u.cache_read_input_tokens or 0
        return response.parsed_output, LLMUsage(
            provider=self.name,
            model=model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=cache_read,
            cost_usd=token_cost(model, u.input_tokens, u.output_tokens, cache_read),
            latency_ms=int((time.perf_counter() - start) * 1000),
        )


class OllamaProvider:
    """LLM local via Ollama, com JSON Schema imposto pelo parâmetro `format`."""

    name = "ollama"

    def __init__(self, settings: Settings, gpu: GpuArbiter | None = None):
        self.s = settings
        self.client = httpx.AsyncClient(base_url=settings.ollama_url, timeout=600)
        self.slots = asyncio.Semaphore(settings.ollama_max_parallel)
        self.gpu = gpu or GpuArbiter()

    async def structured(self, *, model, system, prompt, schema, effort, mock):
        queued = time.perf_counter()
        async with self.gpu.shared(), self.slots:
            queue_ms = int((time.perf_counter() - queued) * 1000)
            out, usage = await self._structured(model=model, system=system, prompt=prompt, schema=schema)
        usage.queue_ms = queue_ms
        return out, usage

    async def unload(self) -> list[str]:
        """Descarrega da VRAM todos os modelos carregados (para outra carga de trabalho usar a GPU)."""
        try:
            loaded = [m["name"] for m in (await self.client.get("/api/ps")).json().get("models", [])]
            for name in loaded:
                await self.client.post("/api/generate", json={"model": name, "keep_alive": 0})
            return loaded
        except httpx.HTTPError:
            return []

    async def _structured(self, *, model, system, prompt, schema):
        start = time.perf_counter()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{prompt}\n\nResponda somente com JSON válido no schema."},
        ]
        # Proteção de contexto: prompt + resposta precisam caber em num_ctx. Se não couber, o Ollama
        # descarta o início da conversa e o modelo pode seguir gerando sem fim.
        est_prompt = (len(system) + len(prompt)) // 3  # ~3,4 caracteres por token medidos em pt-BR + JSON
        room = self.s.ollama_num_ctx - est_prompt - 512
        if room < 1024:
            raise LLMError(f"Prompt de ~{est_prompt} tokens não cabe no contexto de {self.s.ollama_num_ctx}")
        num_predict = min(self.s.ollama_num_predict, room)
        tokens_in = tokens_out = 0
        for attempt in range(2):
            payload = {
                "model": model,
                "messages": messages,
                "format": schema.model_json_schema(),
                "stream": False,
                "options": {"num_ctx": self.s.ollama_num_ctx, "num_predict": num_predict,
                            "temperature": 0.3},
            }
            if self.s.ollama_think is not None:
                payload["think"] = self.s.ollama_think
            try:
                r = await self.client.post("/api/chat", json=payload)
                r.raise_for_status()
            except httpx.TimeoutException as e:
                raise LLMError(f"O modelo local {model} não respondeu em {self.client.timeout.read:.0f} s") from e
            except httpx.ConnectError as e:
                raise LLMError(f"Ollama indisponível em {self.s.ollama_url}") from e
            except httpx.HTTPError as e:
                raise LLMError(f"Erro ao chamar o Ollama ({type(e).__name__}): {e}") from e
            body = r.json()
            if body.get("done_reason") == "length":
                if attempt == 1:
                    raise LLMError(f"Modelo local atingiu o teto de {num_predict} tokens duas vezes")
                messages.append({"role": "user", "content": "Sua resposta passou do limite de tamanho e foi cortada. "
                                 "Responda de novo, completa e bem mais concisa."})
                continue
            tokens_in += body.get("prompt_eval_count", 0)
            tokens_out += body.get("eval_count", 0)
            content = body["message"]["content"]
            try:
                out = schema.model_validate_json(content)
                break
            except ValidationError as e:
                if attempt == 1:
                    raise LLMError(f"Modelo local devolveu JSON inválido: {e}") from e
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"JSON inválido: {e}. Corrija e responda de novo."},
                ]
        elapsed = time.perf_counter() - start
        return out, LLMUsage(
            provider=self.name,
            model=model,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cache_read_tokens=0,
            cost_usd=energy_cost(elapsed, self.s.local_gpu_watts, self.s.energy_price_per_kwh_usd),
            latency_ms=int(elapsed * 1000),
        )


class ProviderRegistry:
    def __init__(self, settings: Settings):
        self.s = settings
        self._cache: dict[str, Provider] = {}
        self.gpu = GpuArbiter()  # uma GPU local compartilhada entre LLM e imagens

    def get(self, name: str) -> Provider:
        if name not in self._cache:
            match name:
                case "mock":
                    self._cache[name] = MockProvider(self.s)
                case "anthropic":
                    self._cache[name] = ClaudeProvider(self.s)
                case "bedrock":
                    self._cache[name] = ClaudeProvider(self.s, bedrock=True)
                case "ollama":
                    self._cache[name] = OllamaProvider(self.s, self.gpu)
                case _:
                    raise LLMError(f"Provedor desconhecido: {name}")
        return self._cache[name]


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
