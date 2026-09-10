"""
Unit tests for agents/shared/companion_detector.py's deterministic (non-LLM)
detection of companion migration patterns (e.g. Oracle/Solr/TIBCO libraries
found inside a java-8-to-25 repo).
"""
from pathlib import Path

from agents.shared.companion_detector import detect_companions


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestDetectCompanions:
    def test_finds_oracle_and_solr_evidence_in_java_repo(self, tmp_path):
        _write(
            tmp_path, "pom.xml",
            """<project>
                <dependencies>
                    <dependency>
                        <groupId>com.oracle.database.jdbc</groupId>
                        <artifactId>ojdbc11</artifactId>
                    </dependency>
                    <dependency>
                        <groupId>org.apache.solr</groupId>
                        <artifactId>solr-solrj</artifactId>
                    </dependency>
                </dependencies>
            </project>""",
        )
        _write(
            tmp_path, "src/main/java/com/acme/Db.java",
            "package com.acme;\nimport oracle.jdbc.OracleDriver;\nclass Db {}\n",
        )

        recs = detect_companions(str(tmp_path), "java-8-to-25")

        patterns = {r["pattern"] for r in recs}
        assert patterns == {"oracle-19c-to-23ai", "solr-4-to-9"}
        for r in recs:
            assert r["evidence"], f"{r['pattern']} should carry non-empty evidence"
            assert r["label"]

    def test_finds_tibco_ems_evidence(self, tmp_path):
        _write(
            tmp_path, "src/main/java/com/acme/Jms.java",
            "package com.acme;\nimport com.tibco.tibjms.TibjmsConnectionFactory;\nclass Jms {}\n",
        )

        recs = detect_companions(str(tmp_path), "java-8-to-25")

        assert {r["pattern"] for r in recs} == {"tibco-ems-to-pubsub"}

    def test_clean_repo_yields_no_recommendations(self, tmp_path):
        _write(tmp_path, "src/main/java/com/acme/Plain.java", "package com.acme;\nclass Plain {}\n")

        recs = detect_companions(str(tmp_path), "java-8-to-25")

        assert recs == []

    def test_non_candidate_primary_pattern_yields_no_recommendations(self, tmp_path):
        _write(
            tmp_path, "pom.xml",
            "<project><dependencies><dependency>"
            "<groupId>com.oracle.database.jdbc</groupId><artifactId>ojdbc11</artifactId>"
            "</dependency></dependencies></project>",
        )

        # solr-4-to-9 has no companion candidates wired up in v1
        recs = detect_companions(str(tmp_path), "solr-4-to-9")

        assert recs == []

    def test_missing_workspace_dir_returns_empty_list(self, tmp_path):
        missing = tmp_path / "does-not-exist"

        recs = detect_companions(str(missing), "java-8-to-25")

        assert recs == []
