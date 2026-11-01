from google import genai
from google.genai import types


def can_try_fallback(exc: Exception, primary_model: str, fallback_model: str) -> bool:
    """Only fail over for provider outages or exhausted per-model quota."""
    return (
        getattr(exc, "code", None) in (429, 503)
        and bool(fallback_model)
        and fallback_model != primary_model
    )


def create_gemini_client(api_key: str):
    """Create a Gemini client with short retries so fallback models can be tried sooner."""
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=2,
                initial_delay=0.5,
                max_delay=2.0,
            )
        ),
    )
