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

# Rough character limit before sending to LLM.
# 4 chars ≈ 1 token for English text, so 400_000 chars ≈ 100k tokens.
_MAX_CHARS = 400_000


class ClauseService:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def extract_clauses(
        self, contract_id: uuid.UUID, raw_text: str
    ) -> tuple[ClauseExtractionResult, dict]:
        """Call the LLM to extract structured clauses from raw contract text.

        Returns:
            (ClauseExtractionResult, usage_dict) — validated clauses and usage metadata.
        """
        truncated_text = raw_text[:_MAX_CHARS]

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
            max_tokens=4000,
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
