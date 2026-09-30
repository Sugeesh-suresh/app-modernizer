from google.adk.models.google_llm import Gemini
from google.genai import types

from .. import config


def make_model(model_name: str | None = None) -> Gemini:
    """The model every agent uses: GEMINI_MODEL, with the SDK's retry enabled.

    ADK turns a plain model-name string into `Gemini(retry_options=None)`, and
    the SDK treats None as "never retry" (google/genai/_api_client.py
    retry_args), so one 429 failed the whole step. The SDK's retry covers 408,
    429 and 5xx responses plus connection errors and timeouts.
    """
    return Gemini(
        model=model_name or config.GEMINI_MODEL,
        retry_options=types.HttpRetryOptions(
            attempts=max(1, config.LLM_RETRY_ATTEMPTS),
            initial_delay=config.LLM_RETRY_INITIAL_DELAY,
            max_delay=config.LLM_RETRY_MAX_DELAY,
        ),
    )


# Gemini's "thinking" budget is dynamic (unbounded) by default. Full-codebase
# generation agents ask for a large, mostly-mechanical text response (many
# files verbatim) rather than deep reasoning — left uncapped, the model can
# spend most or all of its output-token budget on thinking and hit
# MAX_TOKENS before emitting more than a couple of stray tokens of actual
# code. Capping the thinking budget guarantees the bulk of the token budget
# is reserved for the actual generated files.
CODE_GEN_CONFIG = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_budget=8192),
)
