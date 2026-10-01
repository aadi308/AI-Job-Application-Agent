import logging
import re
from typing import Optional

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_PATTERN = re.compile(r"(\+?\d[\d\-\(\)\s]{7,}\d)")
_SECRET_PATTERN = re.compile(r"(sk-|gsk_)[A-Za-z0-9_-]{10,}")


def redact(text: str) -> str:
    """Strips API keys, emails, and phone-number-shaped substrings before logging. Applied
    defensively even though callers shouldn't be passing full resumes/prompts into log
    lines in the first place — only metadata (ids, provider/model names, counts, timings)
    should ever reach a logger."""
    if not text:
        return text
    text = _SECRET_PATTERN.sub("[REDACTED_KEY]", text)
    text = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_PATTERN.sub("[REDACTED_PHONE]", text)
    return text


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def log_llm_call(
    logger: logging.Logger,
    request_id: str,
    job_id: Optional[int],
    agent_name: str,
    provider: str,
    model: str,
    attempt_number: int,
    latency_ms: float,
    token_usage: dict,
    result_status: str,
    fallback_reason: Optional[str] = None,
) -> None:
    logger.info(
        "llm_call request_id=%s job_id=%s agent=%s provider=%s model=%s attempt=%d "
        "latency_ms=%.1f tokens=%s status=%s fallback_reason=%s",
        request_id, job_id, agent_name, provider, model, attempt_number,
        latency_ms, token_usage, result_status, redact(fallback_reason or "") or None,
    )
