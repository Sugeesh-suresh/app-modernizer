"""Shared test setup."""
import pytest

import llm_auth
import main


@pytest.fixture(autouse=True)
def configured_llm(monkeypatch):
    """Tests never reach a model, but the upload endpoint refuses to start a run
    without LLM credentials — so every test sees a configured API-key setup
    unless it replaces this itself."""
    monkeypatch.setattr(main, "LLM_AUTH", llm_auth.AuthConfig(llm_auth.API_KEY))


@pytest.fixture(autouse=True)
def no_preflight(monkeypatch):
    """The preflight runs real Maven builds; tests that exercise it switch it on."""
    from agents import config
    monkeypatch.setattr(config, "PREFLIGHT", "off")


@pytest.fixture(autouse=True)
def no_skill_learning(monkeypatch):
    """Runs through the real agents must never write learned patterns into the
    repository's own skill files; tests of that mechanism use temporary files."""
    from agents.shared import callbacks, learned_fixes
    monkeypatch.setattr(callbacks, "_LEARNING_ENABLED", False)
    monkeypatch.setattr(learned_fixes, "_LEARNING_ENABLED", False)


@pytest.fixture(autouse=True)
def no_rules_extraction(monkeypatch):
    """Rules extraction runs its own agents outside _run_step, which most
    workflow tests stub; the tests of that mechanism switch it on."""
    from agents import config
    monkeypatch.setattr(config, "RULES_EXTRACTION", "off")
