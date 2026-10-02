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
    """Validate provider configuration and construct the shared router.

    Either provider can operate alone. OpenRouter is added as a fallback only when its
    key is present; choosing Groq must not force users to create a second paid account.
    """
    primary_provider = os.environ.get("LLM_PRIMARY_PROVIDER", "groq").strip().lower()
    if primary_provider not in {"groq", "openrouter"}:
        raise ValueError("LLM_PRIMARY_PROVIDER must be 'groq' or 'openrouter'")

    fallback_requested = _env_bool("LLM_ENABLE_FALLBACK", True)
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")
    if openrouter_key and openrouter_key.startswith("gsk_"):
        raise MissingAPIKeyError(
            "OPENROUTER_API_KEY appears to contain a Groq key (gsk_...). Move that value "
            "to GROQ_API_KEY and leave OPENROUTER_API_KEY empty unless you have a separate "
            "OpenRouter key."
        )
    if groq_key and groq_key.startswith("sk-or-"):
        raise MissingAPIKeyError(
            "GROQ_API_KEY appears to contain an OpenRouter key (sk-or-...). Move that value "
            "to OPENROUTER_API_KEY and select OpenRouter or configure a Groq key."
        )
    if primary_provider == "openrouter" and not openrouter_key:
        raise MissingAPIKeyError(
            "OPENROUTER_API_KEY is not set but LLM_PRIMARY_PROVIDER=openrouter. Add the "
            "key to .env or choose groq as the primary provider."
        )
    if not groq_key and not openrouter_key:
        raise MissingAPIKeyError(
            "No LLM provider key is configured. Add GROQ_API_KEY or OPENROUTER_API_KEY to .env."
        )

    openrouter = (
        OpenRouterProvider(
            api_key=openrouter_key,
            base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )
        if openrouter_key
        else None
    )
    fallback_model = os.environ.get("OPENROUTER_FALLBACK_MODEL", "openai/gpt-4o-mini")

    groq = None
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
        enable_fallback=bool(groq and openrouter and fallback_requested),
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
