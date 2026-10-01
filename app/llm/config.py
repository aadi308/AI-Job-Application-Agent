import os

from dotenv import load_dotenv

from app.llm.exceptions import MissingAPIKeyError
from app.llm.groq_provider import GroqProvider
from app.llm.openrouter_provider import OpenRouterProvider
from app.llm.router import LLMRouter

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes")


def build_router() -> LLMRouter:
    """Validates required configuration and constructs the shared router.

    OPENROUTER_API_KEY is required — it's the fallback every routing chain ends at, Groq
    or not. GROQ_API_KEY is treated as optional: if it's absent, the router silently
    degrades to OpenRouter-only (the app's pre-Groq behavior) rather than hard-failing —
    consistent with "Groq is unavailable" already being one of the documented fallback
    triggers, just evaluated once at startup instead of per-request.
    """
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise MissingAPIKeyError(
            "OPENROUTER_API_KEY is not set — required as the fallback provider even when "
            "Groq is configured as primary. Add it to .env."
        )
    openrouter = OpenRouterProvider(
        api_key=openrouter_key,
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    )
    fallback_model = os.environ.get("OPENROUTER_FALLBACK_MODEL", "openai/gpt-4o-mini")

    primary_provider = os.environ.get("LLM_PRIMARY_PROVIDER", "groq").strip().lower()
    groq = None
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key and primary_provider != "openrouter":
        groq = GroqProvider(
            api_key=groq_key,
            base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        )

    return LLMRouter(
        groq=groq,
        openrouter=openrouter,
        routine_model=os.environ.get("GROQ_ROUTINE_MODEL", "openai/gpt-oss-20b"),
        strong_model=os.environ.get("GROQ_STRONG_MODEL", "openai/gpt-oss-120b"),
        fallback_model=fallback_model,
        enable_fallback=_env_bool("LLM_ENABLE_FALLBACK", True),
        routine_confidence_threshold=float(os.environ.get("LLM_ROUTINE_CONFIDENCE_THRESHOLD", "0.85")),
        max_retries=int(os.environ.get("LLM_MAX_RETRIES", "3")),
    )


_router: LLMRouter | None = None


def get_router() -> LLMRouter:
    """Process-wide shared router instance (avoids reconstructing provider clients per call)."""
    global _router
    if _router is None:
        _router = build_router()
    return _router
