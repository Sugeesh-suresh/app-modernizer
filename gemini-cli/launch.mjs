#!/usr/bin/env node
// Starts the Stella Modernizer MCP server (modernizer-backend/cli/mcp_server.py) for Gemini CLI.
//
// Gemini CLI always has Node, so the extension starts this script rather than a Python
// path that differs per platform. Two layouts are supported:
//   - linked checkout:   <repo>/gemini-cli/launch.mjs   + <repo>/modernizer-backend/
//   - installed release: <ext>/launch.mjs + <ext>/modernizer-backend/ (the `stable` branch,
//     built by build-release.mjs; `gemini extensions install <git-url> --ref=stable`)
//
// Python: MODERNIZER_PYTHON if set; otherwise modernizer-backend/.venv-cli, created here on
// first start (and refreshed when requirements-cli.txt changes) from a Python 3.10+ on PATH.
// `node launch.mjs --setup` does only that, so the first Gemini session does not wait for it.
//
// stdout is the MCP channel: everything this script says goes to stderr.
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(realpathSync(fileURLToPath(import.meta.url)));
const win = process.platform === "win32";
const say = (msg) => process.stderr.write(`[stella-modernizer] ${msg}\n`);

const backend = resolve(process.env.MODERNIZER_BACKEND
  || [join(here, "modernizer-backend"), join(here, "..", "modernizer-backend")].find((p) => existsSync(join(p, "cli", "mcp_server.py")))
  || join(here, "..", "modernizer-backend"));

if (!existsSync(join(backend, "cli", "mcp_server.py"))) {
  say(`modernizer-backend not found at ${backend}. Install the extension from its release branch ` +
      "(`gemini extensions install <repo-url> --ref=stable`), link a checkout's gemini-cli folder " +
      "(`gemini extensions link <repo>/gemini-cli`), or set MODERNIZER_BACKEND.");
  process.exit(1);
}

// ── skills: one copy, reachable from both Gemini CLI and the Python pipeline ─────────────
// In the release layout the skills are real files at <ext>/skills and the backend reaches
// them through modernizer-backend/agents/skills, a link created here before Python starts
// (the release ships none: an install copies the clone, which would leave a dangling link).
const rootSkills = join(here, "skills");
const backendSkills = join(backend, "agents", "skills");
if (existsSync(join(rootSkills, "code-review", "SKILL.md")) && !existsSync(join(backendSkills, "code-review", "SKILL.md"))) {
  try {
    if (lstatSync(backendSkills, { throwIfNoEntry: false })) rmSync(backendSkills, { force: true, recursive: false });
    symlinkSync(rootSkills, backendSkills, win ? "junction" : "dir");
    say(`linked ${backendSkills} -> ${rootSkills}`);
  } catch (e) {
    say(`could not link the skills folder (${e.message}); the pipeline will not find its skills.`);
  }
}

// ── Python ───────────────────────────────────────────────────────────────────────────────
function systemPython() {
  for (const name of win ? ["python", "py"] : ["python3", "python"]) {
    const r = spawnSync(name, ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], { encoding: "utf-8" });
    if (r.status === 0) {
      const [maj, min] = r.stdout.trim().split(".").map(Number);
      if (maj > 3 || (maj === 3 && min >= 10)) return name;
    }
  }
  return undefined;
}

function run(cmd, args) {
  // stdout of pip/venv must not reach Gemini (it is the MCP channel): send it to stderr.
  const r = spawnSync(cmd, args, { cwd: backend, stdio: ["ignore", 2, 2] });
  return r.status === 0;
}

function ensureVenv() {
  const venv = join(backend, ".venv-cli");
  const py = win ? join(venv, "Scripts", "python.exe") : join(venv, "bin", "python");
  const reqs = join(backend, "requirements-cli.txt");
  const stamp = join(venv, ".requirements.sha256");
  const want = createHash("sha256").update(readFileSync(reqs)).digest("hex");
  if (existsSync(py) && existsSync(stamp) && readFileSync(stamp, "utf-8").trim() === want) return py;
  if (!existsSync(py)) {
    const base = systemPython();
    if (!base) {
      say("Python 3.10+ was not found on PATH. Install it, or set MODERNIZER_PYTHON to one with the packages " +
          "in modernizer-backend/requirements-cli.txt.");
      return undefined;
    }
    say(`first start: creating ${venv} (one-time, a minute or two)`);
    if (!run(base, ["-m", "venv", venv])) return undefined;
  }
  say("installing the Python requirements (requirements-cli.txt)");
  if (!run(py, ["-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", reqs])) {
    say("pip install failed — see the output above (proxy or index settings: PIP_INDEX_URL, HTTPS_PROXY).");
    return undefined;
  }
  writeFileSync(stamp, want);
  return py;
}

const python = process.env.MODERNIZER_PYTHON || ensureVenv();
if (process.argv.includes("--setup")) {
  say(python ? `ready: ${python}` : "setup failed");
  process.exit(python ? 0 : 1);
}
if (!python) process.exit(1);

const child = spawn(python, ["-m", "cli.mcp_server"], {
  cwd: backend,
  stdio: "inherit",
  env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
});
child.on("exit", (code, signal) => process.exit(signal ? 1 : code ?? 0));
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
