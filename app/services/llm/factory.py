from app.services.llm.base import LLMProvider


def create_llm_provider(settings) -> LLMProvider:
    """Create and return the configured LLM provider.

    Reads LLM_PROVIDER from settings. Adding a new provider = one new elif block here,
    zero changes to business logic elsewhere.
    """
    if settings.LLM_PROVIDER == "openai":
        from app.services.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(api_key=settings.OPENAI_API_KEY, model=settings.LLM_MODEL)

    raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER!r}")
