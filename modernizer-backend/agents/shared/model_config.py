from google.genai import types

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
