"""The computed System Inventory (agents/shared/system_inventory.py): database,
integrations, security and logging/monitoring/auditing facts with file:line."""
from pathlib import Path

from agents.shared import system_inventory as si

FIXTURE = str(Path(__file__).parent / "fixtures" / "arch-inventory")


def _inv():
    return si.scan(FIXTURE)


def test_data_sources_are_listed_with_credentials_redacted():
    sources = {s["key"]: s for s in _inv()["database"]["sources"]}
    assert sources["spring.datasource.url"]["product"] == "Oracle"
    assert sources["spring.datasource.url"]["where"] == "src/main/resources/application.yml:3"
    assert sources["spring.datasource.password"]["value"] == "[REDACTED]"
    assert "spring.datasource.hikari.maximum-pool-size" in sources
    assert "s3cret" not in si.to_markdown(_inv())


def test_entities_columns_relationships_and_transient_fields():
    [claim] = _inv()["database"]["entities"]
    assert (claim["class"], claim["table"]) == ("Claim", "claim")
    fields = {f["field"]: f for f in claim["fields"]}
    assert "scratch" not in fields                                     # @Transient is not persisted
    assert fields["policyNo"]["column"] == "policy_no" and "nullable = false" in fields["policyNo"]["notes"]
    assert "@ManyToOne" in fields["adjuster"]["notes"] and fields["adjuster"]["column"] == "adjuster_id"
    assert "@Id" in fields["id"]["notes"]


def test_ddl_objects_repositories_migrations_and_transactions():
    db = _inv()["database"]
    objects = {(o["kind"], o["name"]): o for o in db["objects"]}
    assert "FOREIGN KEY (policy_no) REFERENCES policy(policy_no)" in objects[("TABLE", "claim")]["detail"]
    assert objects[("INDEX", "ix_claim_policy")]["detail"] == "on claim(policy_no)"
    assert "AFTER INSERT OR UPDATE ON claim" in objects[("TRIGGER", "trg_claim_audit")]["detail"]
    [repo] = db["repositories"]
    assert (repo["name"], repo["base"], repo["entity"]) == ("ClaimRepository", "JpaRepository", "Claim")
    assert [m["tool"] for m in db["migrations"]] == ["Flyway"]
    [tx] = db["transactions"]
    assert tx["target"] == "get" and tx["args"] == "readOnly = true"


def test_integrations_resolve_configured_endpoints_and_classify_hosts():
    integ = _inv()["integrations"]
    clients = {c["kind"]: c for c in integ["clients"]}
    assert "api.stripe.com" in clients["RestTemplate"]["resolved"]
    assert clients["RestTemplate"]["host_hint"] == "third-party (public service)"
    assert clients["Feign client"]["host_hint"] == "internal (private host)"
    assert clients["JMS listener"]["target"] == 'destination = "claims.submitted"'
    hosts = {e["host"]: e["host_hint"] for e in integ["endpoints"]}
    assert hosts == {"api.stripe.com": "third-party (public service)", "policy-svc.corp": "internal (private host)"}


def test_host_classification():
    assert si.classify_host("10.1.2.3") == "internal (private host)"
    assert si.classify_host("billing") == "internal (private host)"
    assert si.classify_host("storage.googleapis.com") == "third-party (public service)"
    assert si.classify_host("partner.example.org") == ""
    assert si.classify_host("${host}") == ""


def test_security_mechanisms():
    sec = _inv()["security"]
    kinds = [(r["kind"], r["detail"]) for r in sec["rows"]]
    assert ("URL rule", 'requestMatchers("/admin/**") → hasRole("ADMIN")') in kinds
    assert ("URL rule", "anyRequest() → authenticated()") in kinds
    assert any(k == "Method rule" and "ADJUSTER" in d and "get" in d for k, d in kinds)
    assert any(k == "Form login" for k, _ in kinds)
    assert any(k == "CSRF" and "ignoringRequestMatchers" in d for k, d in kinds)
    assert any(k == "Password encoder" and d == "BCryptPasswordEncoder" for k, d in kinds)
    assert sec["encrypted_values"] == 1
    keys = {k["key"]: k["value"] for k in sec["keys"]}
    assert keys["server.ssl.key-store-password"] == "[encrypted]"


def test_logging_monitoring_and_auditing():
    obs = _inv()["observability"]
    assert "SLF4J" in obs["facades"] and obs["levels"] == {"info": 1}
    appender = next(c for c in obs["config"] if c["kind"] == "appender")
    assert appender["name"] == "FILE" and "maxHistory=30" in appender["detail"]
    assert {(c["kind"], c["name"], c["detail"]) for c in obs["config"] if c["kind"] != "appender"} == {
        ("logger level", "org.hibernate.SQL", "WARN"), ("root level", "root", "INFO")}
    assert [m["key"] for m in obs["mdc"]] == ["correlationId"]
    monitoring = {m["kind"] for m in obs["monitoring"]}
    assert {"Spring Boot Actuator", "Health indicator", "Micrometer metrics"} <= monitoring
    auditing = {a["kind"] for a in obs["auditing"]}
    assert {"Spring Data auditing enabled", "Audit field", "Entity listener"} <= auditing
    assert [t["table"] for t in obs["audit_tables"]] == ["claim_audit"]


def test_markdown_states_absence_rather_than_omitting_a_section(tmp_path):
    (tmp_path / "App.java").write_text("class App {}")
    md = si.to_markdown(si.scan(str(tmp_path)))
    for heading in ("### Database Details (computed)", "### Integrations (computed)",
                    "### Security Mechanisms (computed)", "### Logging, Monitoring & Auditing (computed)"):
        assert heading in md
    assert "No authentication mechanism found" in md
