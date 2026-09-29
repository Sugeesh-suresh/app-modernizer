"""
LLM authentication: a Gemini API key, or Vertex AI.

`llm_auth.apply` is checked on plain dicts, then against the real Google GenAI
SDK -- the thing that actually picks the backend -- so the mode this module
reports is the mode the agents really use.
"""
import os

import pytest
from fastapi.testclient import TestClient

import llm_auth
import main

SECRET = "AIza-this-must-never-be-shown"
GCP_ENV = {"GOOGLE_GENAI_USE_VERTEXAI": "True", "GCP_PROJECT_ID": "acme-modernize", "GCP_LOCATION": "us-central1"}


@pytest.fixture
def adc(tmp_path, monkeypatch):
    """A gcloud ADC file where this OS keeps it, so Vertex AI has credentials."""
    config = tmp_path / "gcloud"
    config.mkdir()
    (config / "application_default_credentials.json").write_text("{}")
    return {"CLOUDSDK_CONFIG": str(config), "APPDATA": str(tmp_path)}


class TestApiKey:
    def test_gemini_api_key_is_copied_to_the_name_the_sdk_reads(self):
        env = {"GEMINI_API_KEY": SECRET}
        cfg = llm_auth.apply(env)
        assert cfg.mode == llm_auth.API_KEY and cfg.ok
        assert env["GOOGLE_API_KEY"] == SECRET

    def test_an_explicit_false_flag_keeps_the_api_key_even_with_a_project(self):
        env = {"GEMINI_API_KEY": SECRET, "GOOGLE_GENAI_USE_VERTEXAI": "false", "GCP_PROJECT_ID": "p"}
        cfg = llm_auth.apply(env)
        assert cfg.mode == llm_auth.API_KEY
        assert any("project is ignored" in w for w in cfg.warnings)


class TestVertex:
    def test_the_gcp_style_names_are_mapped_onto_the_sdk_names(self, adc):
        env = {**GCP_ENV, **adc}
        cfg = llm_auth.apply(env)
        assert (cfg.mode, cfg.project, cfg.location) == (llm_auth.VERTEX, "acme-modernize", "us-central1")
        assert env["GOOGLE_CLOUD_PROJECT"] == "acme-modernize"
        assert env["GOOGLE_CLOUD_LOCATION"] == "us-central1"
        assert env["GOOGLE_GENAI_USE_VERTEXAI"] == "true"
        assert cfg.mapped == {"GOOGLE_CLOUD_PROJECT": "GCP_PROJECT_ID", "GOOGLE_CLOUD_LOCATION": "GCP_LOCATION"}
        assert cfg.credentials == "Application Default Credentials (gcloud)"
        assert cfg.ok

    def test_the_standard_names_work_as_they_are(self, adc):
        env = {"GOOGLE_GENAI_USE_VERTEXAI": "1", "GOOGLE_CLOUD_PROJECT": "p1", "GOOGLE_CLOUD_LOCATION": "global", **adc}
        cfg = llm_auth.apply(env)
        assert (cfg.mode, cfg.project, cfg.location, cfg.mapped) == (llm_auth.VERTEX, "p1", "global", {})

    def test_both_styles_set_and_different_the_standard_name_wins_and_says_so(self, adc):
        env = {**GCP_ENV, "GOOGLE_CLOUD_PROJECT": "standard-wins", **adc}
        cfg = llm_auth.apply(env)
        assert cfg.project == "standard-wins"
        assert any("GOOGLE_CLOUD_PROJECT and GCP_PROJECT_ID" in w for w in cfg.warnings)

    def test_a_project_without_a_key_or_flag_means_vertex(self, adc):
        env = {"GCP_PROJECT_ID": "p", "GCP_LOCATION": "europe-west4", **adc}
        cfg = llm_auth.apply(env)
        assert cfg.mode == llm_auth.VERTEX and env["GOOGLE_GENAI_USE_VERTEXAI"] == "true"

    def test_a_service_account_key_file_is_used_when_given(self, tmp_path):
        key = tmp_path / "sa.json"
        key.write_text("{}")
        cfg = llm_auth.apply({**GCP_ENV, "GOOGLE_APPLICATION_CREDENTIALS": str(key)})
        assert cfg.ok and "service account" in cfg.credentials

    def test_a_missing_service_account_key_file_is_an_error(self, tmp_path):
        cfg = llm_auth.apply({**GCP_ENV, "GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "gone.json")})
        assert not cfg.ok and "does not exist" in cfg.error

    def test_no_local_credentials_falls_back_to_the_metadata_server(self, tmp_path):
        cfg = llm_auth.apply({**GCP_ENV, "CLOUDSDK_CONFIG": str(tmp_path), "APPDATA": str(tmp_path)})
        assert cfg.ok and "metadata server" in cfg.credentials

    def test_a_flag_with_an_api_key_and_no_project_is_express_mode(self):
        cfg = llm_auth.apply({"GOOGLE_GENAI_USE_VERTEXAI": "true", "GEMINI_API_KEY": SECRET})
        assert cfg.mode == llm_auth.VERTEX_EXPRESS and cfg.ok

    def test_an_api_key_alongside_a_project_is_ignored_with_a_warning(self, adc):
        cfg = llm_auth.apply({**GCP_ENV, "GEMINI_API_KEY": SECRET, **adc})
        assert cfg.mode == llm_auth.VERTEX
        assert any("ignores it" in w for w in cfg.warnings)


class TestMisconfiguration:
    @pytest.mark.parametrize("env, message", [
        ({}, "No LLM credentials"),
        ({"GOOGLE_GENAI_USE_VERTEXAI": "true"}, "no project is set"),
        ({"GOOGLE_GENAI_USE_VERTEXAI": "true", "GCP_PROJECT_ID": "p"}, "no location is set"),
        ({"GOOGLE_GENAI_USE_VERTEXAI": "maybe", "GEMINI_API_KEY": SECRET}, "is not true or false"),
    ])
    def test_each_half_configured_setup_says_what_is_missing(self, env, message):
        cfg = llm_auth.apply(env)
        assert not cfg.ok and message in cfg.error

    def test_upload_is_refused_before_anything_is_unpacked(self, monkeypatch):
        monkeypatch.setattr(main, "LLM_AUTH", llm_auth.apply({}))
        with TestClient(main.app) as client:
            res = client.post("/api/upload", data={"pattern": "java-8-to-11"},
                              files={"file": ("repo.zip", b"not read", "application/zip")})
        assert res.status_code == 503 and "No LLM credentials" in res.json()["detail"]


class TestReporting:
    def test_health_reports_the_mode_and_never_a_secret(self, monkeypatch, adc):
        cfg = llm_auth.apply({**GCP_ENV, "GEMINI_API_KEY": SECRET, **adc})
        monkeypatch.setattr(main, "LLM_AUTH", cfg)
        with TestClient(main.app) as client:
            body = client.get("/health").json()
        assert body["llm"]["mode"] == "vertex-ai"
        assert body["llm"]["project"] == "acme-modernize" and body["llm"]["location"] == "us-central1"
        assert SECRET not in str(body) and SECRET not in cfg.summary()

    def test_the_startup_line_names_where_each_value_came_from(self, adc):
        line = llm_auth.apply({**GCP_ENV, **adc}).summary()
        assert "Vertex AI — project acme-modernize, location us-central1" in line
        assert "GCP_PROJECT_ID → GOOGLE_CLOUD_PROJECT" in line


class TestTheSdkAgrees:
    """The real SDK makes the same choice from the normalised environment."""

    def _sdk_client(self, monkeypatch, env):
        for name in list(os.environ):
            if name.startswith(("GOOGLE_", "GEMINI_", "GCP_")):
                monkeypatch.delenv(name)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        from google import genai
        return genai.Client()._api_client

    def test_vertex_from_gcp_style_names(self, monkeypatch, adc):
        env = {**GCP_ENV, "GEMINI_API_KEY": SECRET, **adc}
        llm_auth.apply(env)
        api = self._sdk_client(monkeypatch, env)
        assert (api.vertexai, api.project, api.location, api.api_key) == (True, "acme-modernize", "us-central1", None)

    def test_api_key_from_gemini_api_key(self, monkeypatch):
        env = {"GEMINI_API_KEY": SECRET}
        llm_auth.apply(env)
        api = self._sdk_client(monkeypatch, env)
        assert not api.vertexai and api.api_key == SECRET
