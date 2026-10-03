"""The interface & job inventory, read from the syntax tree, and the check that
the Technical Specification mentions every endpoint and job."""
from pathlib import Path

from agents.shared import evidence_pack as ep
from agents.shared import interfaces as itf

CODE = {
    "src/main/java/a/JobRestController.java": '''package a;
@RestController
@RequestMapping("/rest/v1/jobs")
public class JobRestController {
    @GetMapping("/{id}") public Job get(@PathVariable String id) { return service.find(id); }
    @PostMapping(value = "/run", produces = "application/json") public Job run(@RequestBody JobRequest r) { return null; }
    @RequestMapping(path = {"/a", "/b"}, method = {RequestMethod.GET, RequestMethod.HEAD}) public void both() {}
    @GetMapping public java.util.List<Job> list() { return null; }
    @Scheduled(cron = "${pds.jobs.cron:0 0 2 * * *}", zone = "America/New_York") public void nightly() {}
    @Scheduled(fixedDelay = 60000, initialDelay = 5000) public void poll() {}
    @JmsListener(destination = "pds.items.in") public void onItem(String m) {}
    public void helper() {}
}''',
    "src/main/java/a/DashboardController.java": '''package a;
@Controller
public class DashboardController {
    @GetMapping("/dashboard") public String dashboard(Model m) { return "dashboard/index"; }
    @PostMapping("/selfservicetool/upload") @ResponseBody public String upload() { return "ok"; }
}''',
    "src/main/java/a/Res.java": '''package a;
@Path("/legacy")
public class Res { @POST @GET @Path("/items") public String items() { return "x"; } }''',
    "src/test/java/a/FakeController.java": '@RestController class FakeController { @GetMapping("/x") void x() {} }',
}


def _scan(tmp_path: Path) -> dict:
    for rel, text in CODE.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return itf.scan(str(tmp_path))


def test_endpoints_jobs_and_listeners_are_read_from_the_code(tmp_path):
    inv = _scan(tmp_path)
    rows = {(e["verb"], e["path"], e["kind"], e["view"]) for e in inv["endpoints"]}
    assert rows == {
        ("GET", "/rest/v1/jobs/{id}", "REST", ""), ("POST", "/rest/v1/jobs/run", "REST", ""),
        ("GET", "/rest/v1/jobs/a", "REST", ""), ("HEAD", "/rest/v1/jobs/a", "REST", ""),
        ("GET", "/rest/v1/jobs/b", "REST", ""), ("HEAD", "/rest/v1/jobs/b", "REST", ""),
        ("GET", "/rest/v1/jobs", "REST", ""),
        ("GET", "/dashboard", "page", "dashboard/index"), ("POST", "/selfservicetool/upload", "REST", ""),
        ("GET", "/legacy/items", "REST", ""), ("POST", "/legacy/items", "REST", ""),
    }
    assert [(j["handler"], j["schedule"], j["zone"]) for j in inv["jobs"]] == [
        ("JobRestController.nightly", "cron = ${pds.jobs.cron:0 0 2 * * *}", "America/New_York"),
        ("JobRestController.poll", "fixedDelay = 60000, initialDelay = 5000", "")]
    assert inv["listeners"] == [{"kind": "Jms", "destination": "pds.items.in", "handler": "JobRestController.onItem",
                                 "source": "src/main/java/a/JobRestController.java:11"}]
    assert not any("Fake" in e["handler"] for e in inv["endpoints"])          # tests are not interfaces


def test_the_inventory_is_deterministic(tmp_path):
    assert _scan(tmp_path) == itf.scan(str(tmp_path)) == itf.scan(str(tmp_path))
    assert [e["verb"] for e in _scan(tmp_path)["endpoints"] if e["path"] == "/legacy/items"] == ["GET", "POST"]


def test_coverage_needs_the_exact_path_or_the_handler(tmp_path):
    inv = _scan(tmp_path)
    spec = ("`GET /rest/v1/jobs/{id}` returns a job. `JobRestController.run` starts one. both() serves /a and /b. "
            "/dashboard renders the dashboard. /selfservicetool/upload. /legacy/items. nightly runs at 2am.")
    assert itf.uncovered(inv, spec) == ["GET /rest/v1/jobs (JobRestController.list)", "scheduled job JobRestController.poll"]


def test_the_evidence_check_lists_what_the_specification_leaves_out():
    empty = {"evidence": set(), "rules": set(), "unknown_evidence": [], "unknown_rules": []}
    md = ep.check_markdown(empty, empty, set(), ["GET /rest/v1/jobs (JobRestController.list)"])
    assert "does not mention (1)" in md and "- GET /rest/v1/jobs (JobRestController.list)" in md
    assert "Every endpoint and scheduled job" in ep.check_markdown(empty, empty, set(), [])
    assert "Every endpoint" not in ep.check_markdown(empty, empty, set(), None)   # no inventory at all
