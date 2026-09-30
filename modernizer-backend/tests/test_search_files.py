"""
search_files: the content search the Java 11 reverse-engineering skill relies on.

The skill asks for every use of each removed API "with file and line". Before
this tool the agent had only list_files (paths) and read_file (one file), so the
instruction could not be carried out on a large repository.
"""
import asyncio
import types as pytypes

import pytest
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents import config
from agents.java_8_to_11 import agents as j11_agents
from agents.shared import workspace_tools as wt
from agents.shared.unknown_tool_guard import unknown_tool_response

FILES = {
    "orders/src/main/java/com/acme/Codec.java": "import sun.misc.BASE64Encoder;\nclass Codec {}\n",
    "orders/src/main/java/com/acme/Xml.java": "import javax.xml.bind.JAXBContext;\nimport javax.xml.bind.Marshaller;\n",
    "orders/src/main/java/com/acme/Plain.java": "class Plain {}\n",
    "web/src/main/webapp/index.jsp": '<%@ page import="sun.misc.BASE64Encoder" %>\n',
    "web/src/main/webapp/WEB-INF/tags/b.tag": "sun.misc.BASE64Decoder\n",
    "target/classes/Codec.java": "import sun.misc.BASE64Encoder;\n",   # build output: excluded
    "README.md": "mentions sun.misc.BASE64Encoder in prose\n",
}


@pytest.fixture
def ctx(tmp_path):
    for rel, text in FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return pytypes.SimpleNamespace(state={"workspace_dir": str(tmp_path)})


def _lines(result: str) -> list[str]:
    return result.splitlines()[1:]


class TestSearch:
    def test_finds_every_hit_with_file_and_line_in_java_only(self, ctx):
        result = wt.search_files(ctx, "sun[.]misc[.]BASE64|javax[.]xml[.]bind", glob="*.java")
        assert _lines(result) == [
            "orders/src/main/java/com/acme/Codec.java:1: import sun.misc.BASE64Encoder;",
            "orders/src/main/java/com/acme/Xml.java:1: import javax.xml.bind.JAXBContext;",
            "orders/src/main/java/com/acme/Xml.java:2: import javax.xml.bind.Marshaller;",
        ]
        assert "3 matching line(s) in 2 file(s); 3 file(s) searched" in result.splitlines()[0]

    def test_several_globs_cover_the_jsp_tier_at_any_depth(self, ctx):
        result = wt.search_files(ctx, "sun[.]misc", glob="*.jsp,*.jspf,*.tag")
        assert [l.split(":")[0] for l in _lines(result)] == [
            "web/src/main/webapp/WEB-INF/tags/b.tag", "web/src/main/webapp/index.jsp",
        ]

    def test_build_output_is_never_searched(self, ctx):
        assert "target/" not in wt.search_files(ctx, "BASE64")

    def test_files_only_counts_per_file_and_counts_files_searched(self, ctx):
        result = wt.search_files(ctx, ".", glob="*.java", subdir="orders/src/main", files_only=True)
        assert "3 file(s) searched" in result.splitlines()[0]
        assert "orders/src/main/java/com/acme/Xml.java: 2 matches" in result

    def test_ignore_case_and_subdir(self, ctx):
        assert "no matches" in wt.search_files(ctx, "JAXBCONTEXT")
        assert "Xml.java:1" in wt.search_files(ctx, "JAXBCONTEXT", ignore_case=True, subdir="orders")

    def test_results_page_and_the_header_says_how_to_continue(self, ctx, monkeypatch):
        monkeypatch.setattr(config, "SEARCH_MAX_RESULTS", 2)
        first = wt.search_files(ctx, "sun[.]misc|javax")
        assert "showing 1-2 of 6" in first and "offset=2" in first
        assert len(_lines(first)) == 2
        last = wt.search_files(ctx, "sun[.]misc|javax", offset=4)
        assert "showing 5-6 of 6" in last and "offset=" not in last

    def test_oversized_files_are_reported_not_silently_skipped(self, ctx, monkeypatch):
        monkeypatch.setattr(config, "SEARCH_MAX_FILE_BYTES", 40)
        assert "file(s) over 40 bytes NOT searched" in wt.search_files(ctx, "x")

    @pytest.mark.parametrize("call, error", [
        (dict(pattern="("), "invalid regular expression"),
        (dict(pattern="x", subdir="../.."), "escapes the workspace root"),
        (dict(pattern="x", subdir="nope"), "does not exist"),
    ])
    def test_bad_input_is_an_error_string(self, ctx, call, error):
        result = wt.search_files(ctx, **call)
        assert result.startswith("ERROR:") and error in result


class _Scripted(BaseLlm):
    """Searches once, then answers; records the tool names it was offered."""
    offered: list = []
    results: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.offered[:] = sorted(llm_request.tools_dict)
        done = [p.function_response for c in llm_request.contents for p in (c.parts or []) if p.function_response]
        if not done:
            part = types.Part(function_call=types.FunctionCall(
                name="search_files", args={"pattern": "sun[.]misc", "glob": "*.java"}))
        else:
            self.results[:] = [str(done[0].response)]
            part = types.Part(text="done")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def test_the_java11_re_agent_offers_search_files_to_the_model_and_it_runs(ctx):
    model = _Scripted(model="scripted")
    agent = j11_agents.re_agent.model_copy(update={"model": model})
    service = InMemorySessionService()
    runner = Runner(app=App(name="retest", root_agent=agent), session_service=service)

    async def go():
        session = await service.create_session(app_name="retest", user_id="u", state=dict(ctx.state))
        async for _ in runner.run_async(user_id="u", session_id=session.id,
                                        new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass

    asyncio.run(go())
    assert {"list_files", "search_files", "read_file"} <= set(model.offered)
    assert "orders/src/main/java/com/acme/Codec.java:1: import sun.misc.BASE64Encoder;" in model.results[0]


class TestGuardMessage:
    def test_a_read_only_agent_is_told_it_cannot_run_anything_and_how_to_inspect(self):
        tools = ["list_skills", "load_skill", "list_files", "search_files", "read_file"]
        msg = unknown_tool_response("google:python_interpreter", tools)["error"]
        assert "You cannot run code or commands." in msg
        assert "use search_files, list_files, read_file" in msg

    def test_an_agent_with_run_command_is_not_told_it_cannot_run_commands(self):
        tools = ["run_command", "check_java11_invariants", "signal_build_success"]
        msg = unknown_tool_response("code_execution", tools)["error"]
        assert "cannot run code or commands" not in msg
        assert "build commands run_command accepts" in msg

    def test_other_unknown_names_get_no_interpreter_hint(self):
        msg = unknown_tool_response("grep_repo", ["list_files"])["error"]
        assert "interpreter" not in msg and "Call only these tools: list_files." in msg
