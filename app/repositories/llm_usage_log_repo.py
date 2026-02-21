from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_usage_log import LLMUsageLog


class LLMUsageLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> LLMUsageLog:
        """Log one LLM call. Required: provider, model, operation, input_tokens, output_tokens, latency_ms, success."""
        log = LLMUsageLog(**kwargs)
        self.session.add(log)
        await self.session.flush()
        return log
