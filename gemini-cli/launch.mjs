#!/usr/bin/env node
// Starts the Stella Modernizer MCP server (modernizer-backend/cli/mcp_server.py) for Gemini CLI.
//
// Gemini CLI always has Node, so the extension starts this script rather than a Python
// path that differs per platform. It picks the Python that has the CLI requirements:
//   1. MODERNIZER_PYTHON, if set;
//   2. modernizer-backend/.venv-cli (created by `node gemini-cli/install.mjs`);
//   3. python3, then python, on PATH.
// MODERNIZER_BACKEND overrides where modernizer-backend is (default: beside this folder).
import { spawn, spawnSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(realpathSync(fileURLToPath(import.meta.url)));
const backend = resolve(process.env.MODERNIZER_BACKEND || join(here, "..", "modernizer-backend"));

function venvPython() {
  const candidates = process.platform === "win32"
    ? [join(backend, ".venv-cli", "Scripts", "python.exe")]
    : [join(backend, ".venv-cli", "bin", "python3"), join(backend, ".venv-cli", "bin", "python")];
  return candidates.find((p) => existsSync(p));
}

function onPath() {
  for (const name of process.platform === "win32" ? ["python", "py"] : ["python3", "python"]) {
    const probe = spawnSync(name, ["--version"], { stdio: "ignore" });
    if (probe.status === 0) return name;
  }
  return undefined;
}

if (!existsSync(join(backend, "cli", "mcp_server.py"))) {
  process.stderr.write(`[stella-modernizer] modernizer-backend not found at ${backend}. ` +
    "Install the extension with `gemini extensions link <repo>/gemini-cli` (not `install`), " +
    "or set MODERNIZER_BACKEND.\n");
  process.exit(1);
}

const python = process.env.MODERNIZER_PYTHON || venvPython() || onPath();
if (!python) {
  process.stderr.write("[stella-modernizer] No Python found. Run `node gemini-cli/install.mjs`, or set MODERNIZER_PYTHON.\n");
  process.exit(1);
}

const child = spawn(python, ["-m", "cli.mcp_server"], {
  cwd: backend,
  stdio: "inherit",
  env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
});
child.on("exit", (code, signal) => process.exit(signal ? 1 : code ?? 0));
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
