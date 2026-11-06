"""Tabela de preços (USD por 1M tokens) para FinOps. Revise periodicamente.

Preços da API Anthropic (1ª parte). Bedrock tem tabela própria — os valores abaixo
servem como estimativa até serem conferidos em https://aws.amazon.com/bedrock/pricing/.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float


PRICES: dict[str, Price] = {
    "claude-fable-5-1": Price(10.00, 50.00, 0.25),
    "claude-opus-5-5": Price(4.00, 20.00, 0.20),
    "claude-opus-5": Price(5.00, 25.00, 0.50),
    "claude-sonnet-5-5": Price(2.00, 10.00, 0.20),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01),
}


def token_cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0) -> float:
    price = PRICES.get(model.removeprefix("anthropic."))
    if price is None:
        return 0.0
    return (
        input_tokens * price.input + output_tokens * price.output + cache_read * price.cache_read
    ) / 1_000_000


def energy_cost(seconds: float, watts: float, price_per_kwh: float) -> float:
    """Custo de energia de inferência local (GPU própria)."""
    return seconds * watts / 3_600_000 * price_per_kwh
