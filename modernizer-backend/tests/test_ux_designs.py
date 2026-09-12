"""
UX design attachments for the JSP -> React pattern: the upload limits, storage
outside the migration workspace, the upload endpoint, and the
before_model_callback that puts the designs in front of the agents that shape
the UI.
"""
import asyncio
import io
import json
import pathlib
import types as pytypes
import zipfile

import pytest
from fastapi.testclient import TestClient
from google.adk.models.llm_request import LlmRequest
from google.genai import types

import main
from agents.jsp_to_react_bff.agents import frontend_generator_agent, planner_agent
from agents.shared import ux_designs

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _ctx(manifest):
    return pytypes.SimpleNamespace(state={ux_designs.STATE_KEY: json.dumps(manifest)})


def _user_request(text: str = "Generate the frontend.") -> LlmRequest:
    return LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text=text)])])


def test_save_writes_every_file_and_returns_its_manifest(tmp_path):
    manifest = ux_designs.save([("../../home.PNG", PNG), ("flows.pdf", b"%PDF-1.7")], tmp_path / "ux")

    assert [d["name"] for d in manifest] == ["home.PNG", "flows.pdf"]
    assert [d["mime_type"] for d in manifest] == ["image/png", "application/pdf"]
    for design in manifest:
        path = pathlib.Path(design["path"])
        # A client-supplied path must not escape the directory we chose.
        assert path.parent == tmp_path / "ux"
        assert path.read_bytes()


@pytest.mark.parametrize("files, message", [
    ([("notes.docx", b"x")], "not a supported"),
    ([("empty.png", b"")], "is empty"),
    ([("big.png", b"0" * (ux_designs.MAX_FILE_BYTES + 1))], "larger than"),
    ([(f"{i}.png", PNG) for i in range(ux_designs.MAX_FILES + 1)], "At most"),
    ([(f"{i}.png", b"0" * (4 * 1024 * 1024)) for i in range(4)], "add up to"),
])
def test_validate_rejects_uploads_outside_the_limits(files, message):
    with pytest.raises(ux_designs.UxDesignError, match=message):
        ux_designs.validate(files)


def test_callback_puts_the_designs_in_the_first_user_message(tmp_path):
    manifest = ux_designs.save([("home.png", PNG)], tmp_path)
    request = _user_request()
    original = request.contents[0]

    assert ux_designs.make_ux_design_callback()(_ctx(manifest), request) is None

    parts = request.contents[0].parts
    assert parts[0].text.startswith("## Attached UX designs (1)")
    assert parts[1].text == "UX design 1: home.png"
    assert parts[2].inline_data.mime_type == "image/png"
    assert parts[2].inline_data.data == PNG
    assert parts[-1].text == "Generate the frontend."
    # The session's stored event must not gain the image bytes.
    assert len(original.parts) == 1


def test_callback_adds_a_user_message_when_the_request_has_none(tmp_path):
    manifest = ux_designs.save([("home.png", PNG)], tmp_path)
    request = LlmRequest(contents=[])

    ux_designs.make_ux_design_callback()(_ctx(manifest), request)

    assert request.contents[0].role == "user"
    assert request.contents[0].parts[1].text == "UX design 1: home.png"


def test_callback_leaves_the_request_alone_when_no_designs_were_attached():
    request = _user_request()

    ux_designs.make_ux_design_callback()(_ctx([]), request)

    assert len(request.contents[0].parts) == 1


def test_callback_skips_a_design_file_that_went_missing(tmp_path):
    manifest = ux_designs.save([("home.png", PNG)], tmp_path)
    pathlib.Path(manifest[0]["path"]).unlink()
    request = _user_request()

    ux_designs.make_ux_design_callback()(_ctx(manifest), request)

    assert len(request.contents[0].parts) == 1


def test_the_ui_shaping_agents_attach_the_designs():
    # The planner decides the page/component map; the generator writes the React code.
    assert planner_agent.before_model_callback is not None
    assert frontend_generator_agent.before_model_callback is not None


def _repo_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("src/main/webapp/index.jsp", "<html><body>Hello</body></html>")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
    async def no_workflow(_session_id):
        return None

    # Upload starts the real Gemini-backed workflow as a background task; this keeps it out of the test.
    monkeypatch.setattr(main, "_run_workflow", no_workflow)
    with TestClient(main.app) as test_client:
        yield test_client


def _upload(client, pattern: str, ux_files: list[tuple[str, bytes]]):
    files = [("file", ("repo.zip", _repo_zip(), "application/zip"))]
    files += [("ux_files", (name, data, "application/octet-stream")) for name, data in ux_files]
    return client.post("/api/upload", data={"pattern": pattern}, files=files)


def test_upload_stores_designs_outside_the_workspace(client):
    res = _upload(client, "jsp-to-react-bff", [("home.png", PNG), ("flows.pdf", b"%PDF-1.7")])

    assert res.status_code == 200, res.text
    assert res.json()["ux_designs"] == 2
    state = asyncio.run(main._get_state(res.json()["session_id"]))
    manifest = json.loads(state[ux_designs.STATE_KEY])
    assert [d["name"] for d in manifest] == ["home.png", "flows.pdf"]
    # Designs living inside the workspace would show up as added files in the migration diff.
    for design in manifest:
        assert not design["path"].startswith(state["workspace_dir"])


def test_upload_without_designs_still_works(client):
    res = _upload(client, "jsp-to-react-bff", [])

    assert res.status_code == 200, res.text
    assert res.json()["ux_designs"] == 0
    state = asyncio.run(main._get_state(res.json()["session_id"]))
    assert json.loads(state[ux_designs.STATE_KEY]) == []


def test_upload_rejects_designs_for_other_patterns(client):
    res = _upload(client, "java-8-to-25", [("home.png", PNG)])

    assert res.status_code == 400
    assert "JSP" in res.json()["detail"]


def test_upload_rejects_an_unsupported_design_file(client):
    res = _upload(client, "jsp-to-react-bff", [("notes.docx", b"x" * 16)])

    assert res.status_code == 400
    assert "not a supported" in res.json()["detail"]
