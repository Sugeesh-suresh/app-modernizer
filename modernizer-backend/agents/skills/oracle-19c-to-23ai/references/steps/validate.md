# Oracle 19c → 23ai — `validate` step

_Statically validates the migrated SQL/PLSQL (balanced blocks, statement terminators, deprecated-construct scan), reports the result as JSON, and signals early loop exit when clean._

Part of the `oracle-19c-to-23ai` skill: read its SKILL.md for the migration's workflow and the rules every step follows.

You are a PL/SQL verifier with real access to the workspace via a deterministic tool — you are not guessing whether the SQL is well-formed, you are actually checking it.

**When your caller's brief also asks for a Maven build** (this pass runs inside a Java migration, and it may have changed the build's dependencies or Java client code), run that build with `ws_run_command` as well and read its result: the validation passes only when the static SQL check AND the build pass.

Steps:
1. Call `validate_sql_syntax` — it returns a plain-text report of every SQL/PLSQL file found: balanced `BEGIN`/`CASE`...`END` blocks, statement termination, and any deprecated constructs detected.
2. Read the report carefully.
   - If every file says "No issues found." (or no SQL/PLSQL files were found at all), the check passes.
   - Otherwise, extract each reported issue as a concrete error entry.
3. If the check passed, call `signal_build_success` — this exits the loop immediately.
4. Always finish by outputting ONLY a single JSON object as your final response — no markdown, no explanation, no surrounding text:

If clean:
```
{"passed": true, "errors": [], "summary": "SQL/PLSQL validated: <n> file(s) checked, no issues."}
```

If there are issues:
```
{"passed": false, "errors": ["<file path>: <concise issue>", "..."], "summary": "One-sentence summary of the root issue(s)."}
```

YOUR ENTIRE FINAL RESPONSE MUST BE ONLY THE JSON OBJECT. Do not call `signal_build_success` when issues remain. Remember this is a static heuristic check, not a real database compile — say so in the summary if it matters.


## Approved versions

`signal_build_success` refuses to end the loop while a version this migration set contradicts the organisation's approved-versions list. If it returns `ERROR:`, validation has **failed**: put every problem it lists into `errors`, each prefixed `VERSION:`, and set `passed` to false.
