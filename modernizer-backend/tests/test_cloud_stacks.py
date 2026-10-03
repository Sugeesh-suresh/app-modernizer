"""Cloud data stores, secret stores and email are stacks of their own, detected
deterministically from dependencies, imports and configuration."""
from pathlib import Path

import pytest

import main
from agents.shared import stack_detector as sd


def _repo(root: Path, files: dict) -> set[str]:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return {s["pattern"] for s in sd.detect_stacks(str(root))}


def _pom(*deps: str) -> str:
    return "<project><dependencies>" + "".join(
        f"<dependency><groupId>{d.split(':')[0]}</groupId><artifactId>{d.split(':')[1]}</artifactId></dependency>"
        for d in deps) + "</dependencies></project>"


@pytest.mark.parametrize("files, stack", [
    ({"pom.xml": _pom("com.google.cloud:google-cloud-bigquery")}, "bigquery"),
    ({"A.java": "import com.google.cloud.bigquery.BigQuery;\nclass A {}"}, "bigquery"),
    ({"pom.xml": _pom("com.google.cloud:google-cloud-secretmanager")}, "gcp-secret-manager"),
    ({"application.yml": "db:\n  password: ${sm://pds-db-password}\n"}, "gcp-secret-manager"),
    ({"pom.xml": _pom("com.google.cloud:google-cloud-storage")}, "gcs"),
    ({"job.properties": "export.path=gs://pds-exports/daily\n"}, "gcs"),
    ({"pom.xml": _pom("software.amazon.awssdk:s3")}, "aws-s3"),
    ({"pom.xml": _pom("software.amazon.awssdk:secretsmanager")}, "aws-secrets-manager"),
    ({"pom.xml": _pom("org.springframework.boot:spring-boot-starter-mail")}, "email"),
    ({"application.properties": "spring.mail.host=smtp.acme.net\n"}, "email"),
])
def test_each_cloud_and_mail_stack_is_detected(tmp_path, files, stack):
    assert stack in _repo(tmp_path, files)


def test_every_new_stack_has_a_checklist():
    refs = Path(main.__file__).parent / "agents" / "skills" / "stack-discovery-re" / "references"
    for spec in sd.CATALOG:
        if spec.pattern not in sd.DEDICATED_RUNNERS:
            assert (refs / spec.reference).is_file(), spec.pattern


def test_cloud_storage_urls_in_code_comments_or_docs_do_not_count_without_a_scanned_file(tmp_path):
    assert "gcs" not in _repo(tmp_path, {"README.md": "Exports land in gs://pds-exports"})
