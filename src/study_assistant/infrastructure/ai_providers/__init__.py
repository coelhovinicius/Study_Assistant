"""Provedores concretos de IA e o orquestrador de cascata de fallback."""

from study_assistant.infrastructure.ai_providers.cascade import AIProviderCascade, CascadeRunResult
from study_assistant.infrastructure.ai_providers.gemini_provider import GeminiProvider
from study_assistant.infrastructure.ai_providers.groq_provider import GroqProvider
from study_assistant.infrastructure.ai_providers.mistral_provider import MistralProvider
from study_assistant.infrastructure.ai_providers.n8n_webhook_provider import N8nWebhookProvider
from study_assistant.infrastructure.ai_providers.openai_provider import OpenAIProvider

__all__ = [
    "AIProviderCascade",
    "CascadeRunResult",
    "GeminiProvider",
    "GroqProvider",
    "MistralProvider",
    "N8nWebhookProvider",
    "OpenAIProvider",
]
