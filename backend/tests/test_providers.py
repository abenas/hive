import asyncio

from hive.config import Settings
from hive.llm.providers import LLMUsage, OllamaProvider


async def test_ollama_slots_serialize_calls_and_report_queue_time():
    provider = OllamaProvider(Settings(_env_file=None, ollama_max_parallel=1))

    async def fake_call(**kwargs):
        await asyncio.sleep(0.2)
        return "ok", LLMUsage("ollama", "m", 1, 1, 0, 0.0, 200)

    provider._structured = fake_call
    kwargs = dict(model="m", system="", prompt="", schema=None, effort="low", mock=None)
    (_, first), (_, second) = await asyncio.gather(provider.structured(**kwargs), provider.structured(**kwargs))
    waits = sorted([first.queue_ms, second.queue_ms])
    assert waits[0] < 50 and waits[1] >= 150  # a segunda esperou a vaga; a espera não entra no latency_ms
