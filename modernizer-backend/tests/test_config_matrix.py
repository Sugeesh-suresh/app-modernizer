"""The configuration matrix: every environment key against every profile, read
from the files, secrets never shown."""
from pathlib import Path

from agents.shared import config_matrix as cm

R = "pds-service/src/main/resources"


def _repo(root: Path, files: dict) -> list[dict]:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return cm.scan(str(root))


def test_profiles_inherit_from_the_default_file_and_differences_are_listed(tmp_path):
    files = {f"{R}/application.properties": "pds.cache.ttl=600\npds.db.url=jdbc:oracle:thin:@//shared:1521/PDS\n"}
    for b in ("mcom", "bcom"):
        for env in ("dev", "prod"):
            files[f"{R}/application-{b}-{env}.properties"] = (
                f"pds.db.url=jdbc:oracle:thin:@//{b}-{env}:1521/PDS\npds.batch.size={5000 if env == 'prod' else 500}\n")
    [m] = _repo(tmp_path, files)
    assert m["profiles"] == ["default", "bcom-dev", "bcom-prod", "mcom-dev", "mcom-prod"]
    eff = cm.effective(m)
    assert eff["pds.cache.ttl"]["mcom-prod"] == ("600", True)                 # inherited
    md = cm.to_markdown([m])
    assert "| `pds.db.url` | `jdbc:oracle:thin:@//shared:1521/PDS` | `jdbc:oracle:thin:@//bcom-dev:1521/PDS`" in md
    assert "| `pds.batch.size` (not in every profile) | — | `500` | `5000` | `500` | `5000` |" in md
    assert "pds.cache.ttl" not in md.split("\n\n", 3)[-1].split("keys differ")[0]  # identical everywhere: not a row
    assert "1 keys differ between profiles, 1 are set in only some, 1 are identical everywhere." in md


def test_secrets_are_never_shown(tmp_path):
    [m] = _repo(tmp_path, {
        f"{R}/application.yml": """spring:
  datasource:
    url: jdbc:db2://dbuser:hunter2@db2-host:50000/PDS
    password: hunter2
pds:
  jasypt-value: ENC(abc123==)
  api-key: abcdef
  gcp-secret: ${sm://pds-api-secret}
  token: ${PDS_TOKEN}
  timeout: 30
---
spring:
  config:
    activate:
      on-profile: bcom-prod
pds:
  timeout: 60
""",
        f"{R}/application-bcom-prod.yml": "pds:\n  batch: 5000\n"})
    shown = {k: v for k, v in m["values"].items()}
    assert shown["spring.datasource.password"] == {"default": "[REDACTED]"}
    assert shown["spring.datasource.url"]["default"] == "jdbc:db2://dbuser:[REDACTED]@db2-host:50000/PDS"
    assert shown["pds.jasypt-value"]["default"] == "[encrypted]"
    assert shown["pds.api-key"]["default"] == "[REDACTED]"
    assert shown["pds.gcp-secret"]["default"] == "[secret reference]"
    assert shown["pds.token"]["default"] == "${PDS_TOKEN}"                  # a placeholder names no secret
    assert shown["pds.timeout"] == {"default": "30", "bcom-prod": "60"}      # profile section inside the YAML
    assert shown["pds.batch"] == {"bcom-prod": "5000"}
    assert "hunter2" not in cm.to_markdown([m]) and "abcdef" not in cm.to_markdown([m])


def test_test_resources_and_build_output_are_ignored(tmp_path):
    assert _repo(tmp_path, {"src/test/resources/application.properties": "a=1",
                            "target/classes/application.properties": "a=1"}) == []


def test_secrets_that_differ_between_profiles_are_listed_as_differing(tmp_path):
    # Both display as "[encrypted]", yet the environments use different secrets.
    [m] = _repo(tmp_path, {f"{R}/application.properties": "db.password=ENC(devSecret==)\nmode=x\n",
                           f"{R}/application-prod.properties": "db.password=ENC(prodSecret==)\n"})
    md = cm.to_markdown([m])
    assert "| `db.password` | `[encrypted]` | `[encrypted]` |" in md
    assert "1 keys differ between profiles" in md
    assert "devSecret" not in md and "prodSecret" not in md and "raw" not in md
