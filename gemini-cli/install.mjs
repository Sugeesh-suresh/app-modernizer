#!/usr/bin/env node
// One-time setup for the Stella Modernizer Gemini CLI extension.
//
//   node gemini-cli/install.mjs            # Python env + skills link, then prints the link command
//   node gemini-cli/install.mjs --link     # ... and runs `gemini extensions link` for you
//
// 1. Creates modernizer-backend/.venv-cli with requirements-cli.txt (no Google ADK, no web server).
// 2. Makes gemini-cli/skills point at modernizer-backend/agents/skills — the one copy of the
//    skills, shared with the web app. Git checks it out as a symlink on Linux/macOS; on Windows
//    (or with core.symlinks=false) it arrives as a text file, and is replaced by a junction.
import { spawnSync } from "node:child_process";
import { existsSync, lstatSync, readFileSync, realpathSync, rmSync, symlinkSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(realpathSync(fileURLToPath(import.meta.url)));
const backend = resolve(join(here, "..", "modernizer-backend"));
const win = process.platform === "win32";

function run(cmd, args, opts = {}) {
  console.log(`$ ${cmd} ${args.join(" ")}`);
  const r = spawnSync(cmd, args, { stdio: "inherit", ...opts });
  if (r.status !== 0) {
    console.error(`\nFailed: ${cmd} ${args.join(" ")}`);
    process.exit(r.status ?? 1);
  }
}

function findPython() {
  const names = process.env.MODERNIZER_PYTHON ? [process.env.MODERNIZER_PYTHON] : win ? ["python", "py"] : ["python3", "python"];
  for (const name of names) {
    const r = spawnSync(name, ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], { encoding: "utf-8" });
    if (r.status === 0) {
      const [maj, min] = r.stdout.trim().split(".").map(Number);
      if (maj > 3 || (maj === 3 && min >= 10)) return name;
      console.error(`${name} is Python ${r.stdout.trim()}; 3.10 or newer is required.`);
    }
  }
  return undefined;
}

// ── 1. Python environment ────────────────────────────────────────────────────
const venv = join(backend, ".venv-cli");
const venvPy = win ? join(venv, "Scripts", "python.exe") : join(venv, "bin", "python");
if (!existsSync(venvPy)) {
  const python = findPython();
  if (!python) {
    console.error("Python 3.10+ not found on PATH (set MODERNIZER_PYTHON to point at one).");
    process.exit(1);
  }
  run(python, ["-m", "venv", venv]);
}
run(venvPy, ["-m", "pip", "install", "--upgrade", "pip"], { cwd: backend });
run(venvPy, ["-m", "pip", "install", "-r", "requirements-cli.txt"], { cwd: backend });

// ── 2. Skills link ───────────────────────────────────────────────────────────
const skills = join(here, "skills");
const target = join(backend, "agents", "skills");
let ok = false;
try {
  ok = existsSync(join(skills, "code-review", "SKILL.md"));
} catch { ok = false; }
if (!ok) {
  try {
    if (existsSync(skills) || lstatSync(skills, { throwIfNoEntry: false })) rmSync(skills, { force: true, recursive: false });
  } catch { /* a dangling link or a text file left by git */ }
  symlinkSync(target, skills, win ? "junction" : "dir");
  console.log(`Linked ${skills} -> ${target}`);
}

// ── 3. Register the extension ────────────────────────────────────────────────
const version = JSON.parse(readFileSync(join(here, "gemini-extension.json"), "utf-8")).version;
console.log(`\nStella Modernizer extension ${version} is ready.`);
if (process.argv.includes("--link")) {
  run(win ? "gemini.cmd" : "gemini", ["extensions", "link", here]);
} else {
  console.log(`Register it with Gemini CLI (once):\n\n  gemini extensions link "${here}"\n`);
}
console.log("Then open the repository to modernize and run:  gemini   →   /modernize:start <pattern>");
