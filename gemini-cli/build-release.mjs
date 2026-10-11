#!/usr/bin/env node
// Builds the installable form of the Stella Modernizer extension and, with --push, publishes it
// to a release branch, so a team installs it the way Gemini CLI installs any extension:
//
//   gemini extensions install <repo-url> --ref=stable --auto-update
//
// `gemini extensions install` copies a repository and expects the extension at its root, while in
// this repository it lives in gemini-cli/ beside modernizer-backend/. The release branch holds:
//
//   gemini-extension.json  GEMINI.md  README.md  launch.mjs  RELEASE.json
//   agents/  commands/            the subagents and slash commands (from gemini-cli/)
//   skills/                       the skills as real files (from modernizer-backend/agents/skills)
//   modernizer-backend/           only what the CLI path runs: agents/ (code), cli/,
//                                 requirements-cli.txt, approved-versions.txt, .env.example
//                                 (launch.mjs links agents/skills to ../../skills on first start)
//
// No web app, no tests, no ADK requirements. launch.mjs creates the Python environment on first start.
//
//   node gemini-cli/build-release.mjs                         # build into dist/gemini-extension
//   node gemini-cli/build-release.mjs --out <dir>
//   node gemini-cli/build-release.mjs --push                  # build, commit to `stable`, push to origin
//   node gemini-cli/build-release.mjs --push --branch stable --remote origin
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..");
const backend = join(repo, "modernizer-backend");
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 && args[i + 1] ? args[i + 1] : dflt; };
const push = args.includes("--push");
const branch = opt("--branch", "stable");
const remote = opt("--remote", "origin");

function git(cwd, ...a) {
  const r = spawnSync("git", a, { cwd, encoding: "utf-8" });
  if (r.status !== 0) throw new Error(`git ${a.join(" ")}: ${(r.stderr || r.stdout).trim()}`);
  return r.stdout.trim();
}

// Never ship caches, environments, local settings or run state.
const SKIP = new Set(["__pycache__", ".venv", ".venv-cli", ".pytest_cache", ".modernizer", ".env", "node_modules"]);
const keep = (src) => !src.split(sep).some((part) => SKIP.has(part)) && !src.endsWith(".pyc");
const copy = (from, to) => cpSync(from, to, { recursive: true, dereference: true, filter: keep });

function build(out, { clean = true } = {}) {
  // A publish builds into a git worktree, which its caller has already emptied except for `.git`.
  if (clean) rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  for (const f of ["gemini-extension.json", "GEMINI.md", "README.md", "launch.mjs"]) copy(join(here, f), join(out, f));
  for (const d of ["agents", "commands"]) copy(join(here, d), join(out, d));
  copy(join(backend, "agents", "skills"), join(out, "skills"));

  const be = join(out, "modernizer-backend");
  mkdirSync(be, { recursive: true });
  for (const f of ["requirements-cli.txt", "approved-versions.txt", ".env.example"]) {
    if (existsSync(join(backend, f))) cpSync(join(backend, f), join(be, f));
  }
  copy(join(backend, "cli"), join(be, "cli"));
  cpSync(join(backend, "agents"), join(be, "agents"), {
    recursive: true, dereference: true,
    filter: (src) => keep(src) && !src.startsWith(join(backend, "agents", "skills")),
  });
  // No link to ../../skills is shipped: `gemini extensions install` clones to a temporary folder and
  // copies it, which turns a relative link into a dangling absolute one. launch.mjs creates it.

  const manifest = JSON.parse(readFileSync(join(here, "gemini-extension.json"), "utf-8"));
  let source = "";
  try { source = git(repo, "rev-parse", "HEAD"); } catch { /* not a git checkout */ }
  writeFileSync(join(out, "RELEASE.json"), JSON.stringify({
    name: manifest.name, version: manifest.version, source_commit: source,
  }, null, 2) + "\n");
  console.log(`Built ${manifest.name} ${manifest.version} into ${out}`);
  return { manifest, source };
}

function publish() {
  if (git(repo, "status", "--porcelain")) {
    throw new Error("The working tree has uncommitted changes — commit them first, so the release names the commit it was built from.");
  }
  const wt = mkdtempSync(join(tmpdir(), "modernizer-release-"));
  rmSync(wt, { recursive: true, force: true });
  let exists = false;
  try { git(repo, "fetch", remote, branch); exists = true; } catch { /* first release */ }
  if (exists) {
    git(repo, "worktree", "add", "-B", branch, wt, `${remote}/${branch}`);
  } else {
    git(repo, "worktree", "add", "--detach", wt);
    git(wt, "checkout", "--orphan", branch);
  }
  try {
    for (const entry of readdirSync(wt)) if (entry !== ".git") rmSync(join(wt, entry), { recursive: true, force: true });
    const { manifest, source } = build(wt, { clean: false });
    git(wt, "add", "-A");
    if (!git(wt, "status", "--porcelain")) {
      console.log(`Nothing changed since the last release on ${branch}.`);
      return;
    }
    git(wt, "commit", "-q", "-m", `Release ${manifest.version} from ${source.slice(0, 12) || "a local build"}`);
    git(wt, "push", "-u", remote, branch);
    console.log(`Pushed ${branch}. Install with:\n\n  gemini extensions install <repository-url> --ref=${branch} --auto-update\n`);
  } finally {
    spawnSync("git", ["worktree", "remove", "--force", wt], { cwd: repo });
  }
}

try {
  if (push) publish();
  else build(resolve(opt("--out", join(repo, "dist", "gemini-extension"))));
} catch (e) {
  console.error(`\nRelease failed: ${e.message}`);
  process.exit(1);
}
