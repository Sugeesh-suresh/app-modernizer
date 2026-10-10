"""
`python -m cli` — the pipeline from a terminal, without Gemini CLI.

Useful to inspect or nudge a run, to script the deterministic steps, and to see
exactly what a subagent would be asked:

    python -m cli start java-8-to-11 --workspace ~/src/legacy-app
    python -m cli next                  # runs deterministic steps, prints the next brief
    python -m cli status
    python -m cli complete <step_id>    # after something saved .modernizer/out/<step_id>.md
    python -m cli confirm plan
    python -m cli refine plan "Keep Hibernate on 5.6"
    python -m cli export
    python -m cli serve                 # the MCP server (stdio), as Gemini CLI runs it

Model steps still need an agent: Gemini CLI (the extension in gemini-cli/), or
any agent that reads the brief and writes its answer to `.modernizer/out/<step_id>.md`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND / ".env")
except ImportError:
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cli", description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", "-w", default="", help="repository root (default: current directory)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", help="start a run")
    s.add_argument("pattern")
    s.add_argument("--strategy", default="bigbang", choices=("bigbang", "incremental"))
    s.add_argument("--springboot-upgrade", action="store_true")
    s.add_argument("--junit-upgrade", action="store_true")
    s.add_argument("--context-file", action="append", default=[])
    s.add_argument("--restart", action="store_true")
    sub.add_parser("status", help="show the run")
    sub.add_parser("next", help="advance to the next step that needs an agent or a person")
    c = sub.add_parser("complete", help="process the output saved for a step")
    c.add_argument("step_id")
    k = sub.add_parser("confirm", help="record a decision at a gate")
    k.add_argument("gate")
    k.add_argument("--select", nargs="*", default=None)
    k.add_argument("--documents", nargs="*", default=None)
    r = sub.add_parser("refine", help="send a document back with feedback")
    r.add_argument("gate")
    r.add_argument("feedback")
    sub.add_parser("export", help="write Word copies of the documents")
    sub.add_parser("patterns", help="list the patterns")
    sub.add_parser("serve", help="run the MCP server on stdio")
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        from cli.mcp_server import main as serve
        serve()
        return 0

    from cli import docs, pipeline, patterns as P
    from cli.mcp_server import _format_step
    from cli.runstate import Run, RunError, resolve_workspace

    try:
        if args.cmd == "patterns":
            print("\n".join([*P.PATTERNS, P.STACK_DISCOVERY]))
        elif args.cmd == "start":
            run = pipeline.start(resolve_workspace(args.workspace or None), args.pattern, args.strategy,
                                 args.springboot_upgrade, args.junit_upgrade, args.context_file, args.restart)
            print(pipeline.summary(run))
        else:
            run = Run.load(args.workspace or None)
            if args.cmd == "status":
                print(pipeline.summary(run))
            elif args.cmd == "next":
                step, log = pipeline.next_step(run)
                print(_format_step(step, log))
            elif args.cmd == "complete":
                print(pipeline.complete_step(run, args.step_id))
            elif args.cmd == "confirm":
                print(pipeline.confirm(run, args.gate, args.select, args.documents))
            elif args.cmd == "refine":
                print(pipeline.refine(run, args.gate, args.feedback))
            elif args.cmd == "export":
                print(docs.export(run))
    except (RunError, KeyError) as exc:
        print(f"error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
