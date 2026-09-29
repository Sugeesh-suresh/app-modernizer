"""
How the backend authenticates to Gemini: a Gemini API key, or Vertex AI.

The Google GenAI SDK (and ADK on top of it) chooses its backend from the
environment on its own:

  - API key:   GOOGLE_API_KEY (or GEMINI_API_KEY)
  - Vertex AI: GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT,
               GOOGLE_CLOUD_LOCATION, and Google Cloud credentials
               (Application Default Credentials or GOOGLE_APPLICATION_CREDENTIALS)

It only understands those exact names, and it gives no sign of which backend
it picked until the first model call fails. This module runs once at startup,
before any agent is built, and:

  1. accepts the other names teams commonly put in `.env` for the same values
     (`GCP_PROJECT_ID`, `GCP_LOCATION`, `GEMINI_API_KEY`, ...) and copies them
     onto the names the SDK reads -- a standard name that is already set
     always wins;
  2. decides the mode: Vertex AI when `GOOGLE_GENAI_USE_VERTEXAI` is true, or
     when it is unset and a project is configured with no API key; the API key
     otherwise;
  3. reports what it decided -- in the startup log and on `/health`, never
     printing a secret -- and says exactly what is missing when a mode is only
     half configured, instead of leaving it to a stack trace mid-migration.

Standard library only: it must run before the SDK is imported.
"""
import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path

API_KEY = "api-key"
VERTEX = "vertex-ai"
VERTEX_EXPRESS = "vertex-ai-express"   # Vertex AI authenticated with an API key, no project
UNCONFIGURED = "unconfigured"

#: SDK name -> other names accepted for it, in priority order.
ALIASES: dict[str, tuple[str, ...]] = {
    "GOOGLE_CLOUD_PROJECT": ("GCP_PROJECT_ID", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT_ID", "VERTEX_PROJECT", "VERTEXAI_PROJECT"),
    "GOOGLE_CLOUD_LOCATION": ("GCP_LOCATION", "GCP_REGION", "GOOGLE_CLOUD_REGION", "VERTEX_LOCATION", "VERTEXAI_LOCATION"),
    "GOOGLE_GENAI_USE_VERTEXAI": ("USE_VERTEX_AI", "USE_VERTEXAI", "GOOGLE_GENAI_USE_VERTEX_AI"),
    "GOOGLE_API_KEY": ("GEMINI_API_KEY",),
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass
class AuthConfig:
    mode: str
    project: str = ""
    location: str = ""
    credentials: str = ""
    #: `{sdk name: alias it was copied from}` — shown so a reviewer can see why a value applied.
    mapped: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def public(self) -> dict:
        """Safe to show anywhere: no key, no credential contents."""
        out = {"mode": self.mode, "ok": self.ok}
        if self.mode in (VERTEX, VERTEX_EXPRESS):
            out.update(project=self.project or None, location=self.location or None)
        if self.credentials:
            out["credentials"] = self.credentials
        if self.error:
            out["error"] = self.error
        if self.warnings:
            out["warnings"] = self.warnings
        return out

    def summary(self) -> str:
        if self.mode == API_KEY:
            line = "LLM auth: Gemini API key"
        elif self.mode == VERTEX:
            line = f"LLM auth: Vertex AI — project {self.project}, location {self.location}, credentials: {self.credentials}"
        elif self.mode == VERTEX_EXPRESS:
            line = "LLM auth: Vertex AI express mode (API key, no project)"
        else:
            line = "LLM auth: NOT CONFIGURED"
        if self.mapped:
            line += " [from " + ", ".join(f"{alias} → {name}" for name, alias in self.mapped.items()) + "]"
        return line


def _get(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _flag(raw: str) -> bool | None:
    raw = raw.strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return None


def adc_file(env: Mapping[str, str]) -> Path:
    """Where `gcloud auth application-default login` writes credentials."""
    if os.name == "nt":
        return Path(env.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "gcloud" / "application_default_credentials.json"
    config = env.get("CLOUDSDK_CONFIG")
    return Path(config) / "application_default_credentials.json" if config else \
        Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def _credential_source(env: Mapping[str, str]) -> tuple[str, str]:
    """(description, error) for the Vertex AI credentials, without reading them."""
    explicit = _get(env, "GOOGLE_APPLICATION_CREDENTIALS")
    if explicit:
        if not Path(explicit).is_file():
            return "", (f"GOOGLE_APPLICATION_CREDENTIALS points to '{explicit}', which does not exist. "
                        "Fix the path, or remove it to use `gcloud auth application-default login`.")
        return "service account key (GOOGLE_APPLICATION_CREDENTIALS)", ""
    if adc_file(env).is_file():
        return "Application Default Credentials (gcloud)", ""
    # Not an error: on GCE, GKE, Cloud Run and Cloud Workstations the metadata
    # server supplies credentials, and there is no file to look for.
    return "metadata server (no key file or gcloud login found locally)", ""


def apply(env: MutableMapping[str, str] | None = None) -> AuthConfig:
    """Normalise *env* (os.environ by default) for the SDK and return the decision."""
    env = os.environ if env is None else env
    mapped: dict[str, str] = {}
    warnings: list[str] = []

    for name, aliases in ALIASES.items():
        present = [a for a in aliases if _get(env, a)]
        if not present:
            continue
        if _get(env, name):
            if any(_get(env, a) != _get(env, name) for a in present):
                warnings.append(f"{name} and {present[0]} are both set and differ; using {name}.")
            continue
        env[name] = _get(env, present[0])
        mapped[name] = present[0]

    raw_flag = _get(env, "GOOGLE_GENAI_USE_VERTEXAI")
    flag = _flag(raw_flag) if raw_flag else None
    if raw_flag and flag is None:
        return AuthConfig(UNCONFIGURED, mapped=mapped, warnings=warnings, error=(
            f"GOOGLE_GENAI_USE_VERTEXAI='{raw_flag}' is not true or false."))

    project, location = _get(env, "GOOGLE_CLOUD_PROJECT"), _get(env, "GOOGLE_CLOUD_LOCATION")
    api_key = _get(env, "GOOGLE_API_KEY")

    # Unset flag: a project with no API key can only mean Vertex AI.
    if flag is None and project and not api_key:
        flag = True
        mapped.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "(inferred from the project)")

    if flag:
        env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        if not project:
            if api_key:
                return AuthConfig(VERTEX_EXPRESS, mapped=mapped, warnings=warnings)
            return AuthConfig(UNCONFIGURED, mapped=mapped, warnings=warnings, error=(
                "Vertex AI is enabled but no project is set. Add GOOGLE_CLOUD_PROJECT (or GCP_PROJECT_ID) "
                "and GOOGLE_CLOUD_LOCATION (or GCP_LOCATION) to .env."))
        if not location:
            return AuthConfig(UNCONFIGURED, project=project, mapped=mapped, warnings=warnings, error=(
                "Vertex AI is enabled but no location is set. Add GOOGLE_CLOUD_LOCATION (or GCP_LOCATION) "
                "to .env, e.g. us-central1 or global."))
        if api_key:
            warnings.append("An API key is also set; Vertex AI uses the project's credentials and ignores it.")
        credentials, error = _credential_source(env)
        return AuthConfig(VERTEX, project, location, credentials, mapped, warnings, error)

    if flag is False:
        env["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
    if api_key:
        if project and flag is False:
            warnings.append("GOOGLE_GENAI_USE_VERTEXAI is false, so the Gemini API key is used and the project is ignored.")
        return AuthConfig(API_KEY, mapped=mapped, warnings=warnings)
    return AuthConfig(UNCONFIGURED, mapped=mapped, warnings=warnings, error=(
        "No LLM credentials. Set GEMINI_API_KEY for the Gemini API, or for Vertex AI set "
        "GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION."))
