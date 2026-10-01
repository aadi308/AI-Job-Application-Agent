"""Typed exceptions for the LLM provider layer.

None of these carry raw API keys, secrets, or full prompt/resume content in their
messages — callers should only pass short, safe descriptions.
"""


class LLMError(Exception):
    """Base class for all LLM provider errors."""


class AuthenticationError(LLMError):
    """Provider rejected the API key."""


class MissingAPIKeyError(LLMError):
    """Required API key isn't set in the environment."""


class RateLimitError(LLMError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderTimeoutError(LLMError):
    """Provider didn't respond within the configured timeout, after retries."""


class ProviderUnavailableError(LLMError):
    """Provider returned a 5xx / connection-level failure."""


class InvalidJSONError(LLMError):
    """Provider returned a response that isn't valid JSON."""


class SchemaValidationError(LLMError):
    def __init__(self, message: str, validation_errors: list[str] | None = None):
        super().__init__(message)
        self.validation_errors = validation_errors or []


class ContextLengthError(LLMError):
    """Prompt exceeded the model's context window."""


class EmptyResponseError(LLMError):
    """Provider returned an empty completion."""


class LowConfidenceError(LLMError):
    def __init__(self, message: str, confidence: float):
        super().__init__(message)
        self.confidence = confidence


class AllProvidersFailedError(LLMError):
    """Every provider in the routing chain failed — caller must not fabricate a result."""

    def __init__(self, message: str, attempts: list[dict] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


# Errors worth retrying (transient). Auth/missing-key/context-length/schema errors are not
# retryable — retrying them wastes calls on something that can't self-resolve.
RETRYABLE_EXCEPTIONS = (RateLimitError, ProviderTimeoutError, ProviderUnavailableError, EmptyResponseError)
