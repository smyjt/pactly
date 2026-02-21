from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: int


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 2000,
        response_format: dict | None = None,
    ) -> LLMResponse:
        """Send messages to the LLM and return a structured response."""
        ...
