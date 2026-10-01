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
