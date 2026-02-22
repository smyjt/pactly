import json
import logging
import uuid

from app.schemas.clause import ClauseExtractionResult
from app.services.llm.base import LLMProvider
from app.services.llm.prompts.clause_extraction import (
    CLAUSE_EXTRACTION_SYSTEM,
    CLAUSE_EXTRACTION_USER,
)

logger = logging.getLogger(__name__)


class ClauseService:
    def __init__(self, llm: LLMProvider, max_chars: int = 400_000, max_output_tokens: int = 4000):
        self.llm = llm
        self.max_chars = max_chars
        self.max_output_tokens = max_output_tokens

    async def extract_clauses(
        self, contract_id: uuid.UUID, raw_text: str
    ) -> tuple[ClauseExtractionResult, dict]:
        """Call the LLM to extract structured clauses from raw contract text.

        Returns:
            (ClauseExtractionResult, usage_dict) — validated clauses and usage metadata.
        """
        truncated_text = raw_text[:self.max_chars]
        if len(raw_text) > self.max_chars:
            logger.warning(
                f"Contract {contract_id} text truncated from {len(raw_text)} "
                f"to {self.max_chars} chars before LLM call"
            )

        messages = [
            {"role": "system", "content": CLAUSE_EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": CLAUSE_EXTRACTION_USER.format(contract_text=truncated_text),
            },
        ]

        logger.info(f"Extracting clauses for contract {contract_id}")

        response = await self.llm.complete(
            messages=messages,
            temperature=0.0,
            max_tokens=self.max_output_tokens,
            response_format={"type": "json_object"},
        )

        raw_json = json.loads(response.content)
        result = ClauseExtractionResult.model_validate(raw_json)

        logger.info(
            f"Extracted {len(result.clauses)} clauses for contract {contract_id} "
            f"({response.input_tokens} in / {response.output_tokens} out tokens)"
        )

        usage = {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "model": response.model,
            "latency_ms": response.latency_ms,
        }
        return result, usage
