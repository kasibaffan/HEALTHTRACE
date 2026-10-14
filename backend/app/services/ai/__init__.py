import logging
import os

from app.services.ai.base import AIExtractionService
from app.services.ai.mock import MockAIExtractionService

log = logging.getLogger("healthtrace.ai")

# Register OpenAI / Claude / Gemini implementations here. Their output must go through the same
# validation in services/processing.py before anything is persisted.
_PROVIDERS: dict[str, type[AIExtractionService]] = {"mock": MockAIExtractionService}


def get_ai_service() -> AIExtractionService:
    name = os.getenv("AI_PROVIDER", "mock").lower()
    provider = _PROVIDERS.get(name)
    if provider is None:
        log.warning("AI provider '%s' is not available; using the deterministic mock service.", name)
        provider = MockAIExtractionService
    return provider()
