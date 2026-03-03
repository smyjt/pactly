_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


def estimate_llm_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Estimate cost in USD based on OpenAI pricing (per 1M tokens).

    Falls back to gpt-4o-mini rates for unknown models.
    """
    rates = _PRICING.get(model, _PRICING["gpt-4o-mini"])
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
