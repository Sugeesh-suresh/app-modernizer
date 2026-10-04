"""
UI Screens: the application's pages rendered from its own templates with
generated sample data, for the stack-discovery "UI Screens" document. No model
is involved: what is rendered, with which data and in which states is read from
the code, and the same repository always gives the same screens.

Flow (`capture`):

1. Pages: every page endpoint of the Interface Inventory (`interfaces.scan`)
   whose view is a literal template name, then the top-level templates no
   controller names (layouts, fragments and mail templates excluded).
2. Data and states (`ui_mock_data`): the controller's model and the template's
   own expressions give the default state; each condition the page tests gives
   another (an empty list, a message shown, a request parameter, fewer roles,
   signed out), up to `UI_SCREENSHOTS_MAX_STATES` per page.
3. Render: the Thymeleaf renderer (tools/thymeleaf-render: Spring's Thymeleaf
   engine with the layout dialect, form binding and `sec:` stand-ins) turns each
   state into HTML. It runs on a copy of the templates, without the session's
   environment, with expressions barred from reaching Java classes. A page it
   cannot render falls back to a static preview of the raw template, labelled.
4. Screenshot: headless Chromium (Playwright), 1366 px wide, scripts off, every
   request answered from the module's static folders or refused — nothing
   leaves the machine.

Everything not rendered is listed with its reason; a failure here never stops
the reverse-engineering documents.
"""
import asyncio
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .. import config
from . import config_matrix, ui_mock_data
from .dependency_graph import EXCLUDED_DIRS

#: Stacks the pipeline can render, by detected stack id.
RENDERABLE = {"thymeleaf"}
UI_KINDS = {"web-tier", "frontend"}
VIEWPORT = {"width": 1366, "height": 900}
MAX_HEIGHT = 4000
MIN_HEIGHT = 240
_CONTENT_BOTTOM = """() => {
  let bottom = 0;
  for (const el of document.body ? document.body.querySelectorAll('*') : []) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) bottom = Math.max(bottom, r.bottom + window.scrollY);
  }
  return Math.ceil(bottom);
}"""
BASE_URL = "http://app.local"
_FRAGMENT_DIRS = re.compile(r"(?:^|/)(?:fragments?|layouts?|partials?|includes?|common|shared|mail|emails?)/",
                            re.I)

_TOOLS: dict | None = None


# ── availability ────────────────────────────────────────────────────────────

def _java_major(java: str) -> int:
    try:
        out = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=20,
                             env={"PATH": os.environ.get("PATH", "")})
    except (OSError, subprocess.TimeoutExpired):
        return 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out.stderr + out.stdout)
    if not m:
        return 0
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major


def _installed_chromium(expected: Path) -> Path | None:
    """The newest other Chromium build next to the one Playwright expects
    (…/ms-playwright/chromium-1194/chrome-linux/chrome)."""
    parts = expected.parts
    idx = next((i for i, part in enumerate(parts) if part.startswith("chromium-")), None)
    if idx is None:
        return None
    base = Path(*parts[:idx])
    tails = [Path(*parts[idx + 1:]), Path("chrome-linux64/chrome"), Path("chrome-linux/chrome"),
             Path("chrome-mac/Chromium.app/Contents/MacOS/Chromium"), Path("chrome-win/chrome.exe"),
             Path("chrome-win64/chrome.exe")]
    builds = sorted(base.glob("chromium-*"), key=lambda d: int(re.sub(r"\D", "", d.name) or 0), reverse=True)
    return next((d / tail for d in builds for tail in tails if (d / tail).is_file()), None)


def tools(refresh: bool = False) -> dict:
    """What is installed: {"browser": bool, "renderer": bool, "notes": [...]}. Cached per process."""
    global _TOOLS
    if _TOOLS is not None and not refresh:
        return _TOOLS
    notes, browser, renderer, chromium = [], False, False, config.UI_SCREENSHOTS_CHROMIUM
    try:
        from playwright.sync_api import sync_playwright   # noqa: F401
        exe = config.UI_SCREENSHOTS_CHROMIUM
        if exe:
            browser = Path(exe).is_file()
            if not browser:
                notes.append(f"Chromium not found at UI_SCREENSHOTS_CHROMIUM ({exe})")
        else:
            with sync_playwright() as p:
                expected = Path(p.chromium.executable_path)
            browser = expected.is_file()
            if not browser:
                # Another installed Chromium build in Playwright's browser folder usually works.
                found = _installed_chromium(expected)
                if found:
                    browser, chromium = True, str(found)
                else:
                    notes.append("Playwright's Chromium is not installed (playwright install chromium, "
                                 "or set UI_SCREENSHOTS_CHROMIUM)")
    except Exception as exc:                              # not installed, or no browser
        notes.append(f"Playwright is not available ({type(exc).__name__})")
    java = shutil.which("java")
    if not java or _java_major(java) < 17:
        notes.append("Java 17 or later not found")
    elif not Path(config.UI_THYMELEAF_RENDERER).is_file():
        notes.append("the Thymeleaf renderer is not built (python dev.py setup-ui, or "
                     "mvn -f tools/thymeleaf-render/pom.xml package)")
    else:
        renderer = True
    _TOOLS = {"browser": browser, "renderer": renderer, "java": java or "", "chromium": chromium, "notes": notes}
    return _TOOLS


def offer(stacks: list[dict]) -> dict | None:
    """Whether to offer screenshots for these detected stacks. None: say nothing
    (disabled, or no UI). Otherwise {"available", "default", "stacks", "reason"}."""
    if config.UI_SCREENSHOTS == "off":
        return None
    ui = [s for s in stacks if s.get("kind") in UI_KINDS or s.get("pattern") in RENDERABLE]
    if not ui:
        return None
    renderable = sorted(s["pattern"] for s in ui if s.get("pattern") in RENDERABLE)
    if not renderable:
        names = ", ".join(sorted(s.get("label") or s["pattern"] for s in ui))
        return {"available": False, "default": False, "stacks": [],
                "reason": f"UI screenshots support Thymeleaf pages; not yet {names}."}
    status = tools()
    if not status["browser"]:
        return {"available": False, "default": False, "stacks": [],
                "reason": "Screenshots need a headless browser on the server: " + "; ".join(status["notes"]) + "."}
    reason = "" if status["renderer"] else (
        "Pages will be static template previews (no sample data): " + "; ".join(status["notes"]) + ".")
    return {"available": True, "default": config.UI_SCREENSHOTS_DEFAULT, "stacks": renderable, "reason": reason}


# ── planning ────────────────────────────────────────────────────────────────

@dataclass
class Page:
    template: str                  # name relative to the templates root, without .html
    templates_root: str            # relative to the workspace
    endpoint: dict | None          # the Interface Inventory endpoint, None for a template no controller names
    states: list = field(default_factory=list)
    files: list = field(default_factory=list)   # template files read, relative to the workspace


def _safe_files(root: Path):
    """Regular files under `root`, never following or returning a symbolic link."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not Path(dirpath, d).is_symlink())
        for name in sorted(filenames):
            path = Path(dirpath, name)
            if not path.is_symlink() and path.is_file():
                yield path


def templates_roots(workspace_dir: str) -> list[str]:
    """Thymeleaf template folders, relative to the workspace: `<resources>/templates`
    (Spring Boot's default) and any `spring.thymeleaf.prefix` the configuration names."""
    root = Path(workspace_dir)
    prefixes = {"templates"}
    for matrix in config_matrix.scan(workspace_dir):
        for value in matrix["values"].get("spring.thymeleaf.prefix", {}).values():
            m = re.match(r"classpath\*?:/?(.+?)/?$", value.strip())
            if m:
                prefixes.add(m.group(1).strip("/"))
    dirs = set()
    for path in _safe_files(root):
        rel = path.relative_to(root).as_posix()
        m = re.match(r"^((?:.*/)?src/main/resources)/(.+\.html?)$", rel)
        if not m:
            continue
        for prefix in prefixes:
            if m.group(2).startswith(prefix + "/"):
                dirs.add(f"{m.group(1)}/{prefix}")
    return sorted(dirs)


def _is_page_template(text: str, rel: str) -> bool:
    if _FRAGMENT_DIRS.search(rel + "/") or _FRAGMENT_DIRS.search(rel):
        return False
    if "layout:fragment" in text and not re.search(r"layout:decorat", text):
        return False                                    # a layout
    if not re.search(r"<html|<!doctype|layout:decorat", text, re.I):
        return False                                    # a fragment file
    return True


def plan(workspace_dir: str, inventory: dict) -> tuple[list[Page], list[dict]]:
    """(pages to render, [{"what", "template", "reason"}] not rendered), in a fixed order."""
    root = Path(workspace_dir)
    roots = templates_roots(workspace_dir)
    pages, skipped, used = [], [], set()

    def locate(view: str, source: str) -> tuple[str, str] | None:
        name = view.strip().lstrip("/")
        name = name[:-5] if name.endswith(".html") else name
        ranked = sorted(roots, key=lambda r: (-len(os.path.commonprefix([r, source])), r))
        for r in ranked:
            path = root / r / f"{name}.html"
            if path.is_file() and not path.is_symlink():
                return r, name
        return None

    for e in inventory.get("endpoints", []):
        if e.get("kind") != "page" or e.get("verb") not in ("GET", "ANY"):
            continue
        what = f"{e['verb']} {e['path']} ({e['handler']})"
        view = e.get("view", "")
        if not view:
            skipped.append({"what": what, "template": "—", "reason": "the view name is not a literal in the code"})
            continue
        if view.startswith(("redirect:", "forward:")):
            continue
        found = locate(view, e.get("source", ""))
        if not found:
            skipped.append({"what": what, "template": view,
                            "reason": "no Thymeleaf template with this name (JSP or another view technology)"})
            continue
        key = (found[0], found[1], e["path"])
        if key in used:
            continue
        used.add(key)
        used.add((found[0], found[1]))
        pages.append(Page(found[1], found[0], e))
    for r in roots:
        base = root / r
        for path in _safe_files(base):
            if path.suffix != ".html":
                continue
            name = path.relative_to(base).with_suffix("").as_posix()
            if (r, name) in used:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if _is_page_template(text, name):
                used.add((r, name))
                pages.append(Page(name, r, None))
    return pages, skipped


# ── rendering ───────────────────────────────────────────────────────────────

def _copy_tree(src: Path, dest: Path, suffixes: tuple | None = None) -> None:
    for path in _safe_files(src):
        if suffixes and path.suffix.lower() not in suffixes:
            continue
        target = dest / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _static_dirs(workspace: Path, templates_root: str) -> list[Path]:
    resources = (workspace / templates_root).parent
    while resources.name != "resources" and resources != workspace and resources.parent != resources:
        resources = resources.parent
    main = resources.parent
    found = [resources / d for d in ("static", "public", "resources", "META-INF/resources")] + [main / "webapp"]
    return [d for d in found if d.is_dir() and not d.is_symlink()]


def _message_basenames(work: Path, workspace: Path, templates_root: str, k: int) -> list[str]:
    resources = (workspace / templates_root).parent
    out_dir = work / f"messages-{k}"
    bases = set()
    for path in sorted(resources.glob("*.properties")):
        m = re.match(r"(messages|i18n)(?:_[\w]+)?\.properties$", path.name)
        if m and not path.is_symlink():
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out_dir / path.name)
            bases.add(str(out_dir / m.group(1)))
    i18n = resources / "i18n"
    if i18n.is_dir() and not i18n.is_symlink():
        for path in sorted(i18n.glob("*.properties")):
            if not path.is_symlink():
                (out_dir / "i18n").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, out_dir / "i18n" / path.name)
                bases.add(str(out_dir / "i18n" / re.sub(r"(?:_[a-zA-Z]{2,3})*\.properties$", "", path.name)))
    return sorted(bases)


async def _run_renderer(work: Path, k: int, spec: dict, timeout: float) -> dict[str, dict]:
    status = tools()
    jobs_file, results_file = work / f"jobs-{k}.json", work / f"results-{k}.json"
    jobs_file.write_text(json.dumps(spec), encoding="utf-8")
    # No inherited environment: the session's credentials never reach the renderer.
    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "HOME": str(work)}
    proc = await asyncio.create_subprocess_exec(
        status["java"], "-Xmx512m", "-Duser.timezone=UTC", "-Duser.language=en", "-Duser.country=US",
        "-Djava.awt.headless=true", "-jar", config.UI_THYMELEAF_RENDERER, str(jobs_file), str(results_file),
        cwd=str(work), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=max(5.0, timeout))
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {j["id"]: {"ok": False, "error": "the renderer ran out of time"} for j in spec["jobs"]}
    if not results_file.is_file():
        reason = (err or b"").decode("utf-8", "replace").strip().splitlines()
        reason = next((l for l in reversed(reason) if l and "JAVA_TOOL_OPTIONS" not in l), "no output")
        return {j["id"]: {"ok": False, "error": f"the renderer failed: {reason[:200]}"} for j in spec["jobs"]}
    return {r["id"]: r for r in json.loads(results_file.read_text(encoding="utf-8"))}


async def _screenshot(pages: list[tuple[str, Path, list[Path], Path]], deadline: float) -> dict[str, str]:
    """[(screen id, html file, static dirs, png out)] → {screen id: error} for the ones that failed."""
    from playwright.async_api import async_playwright
    errors: dict[str, str] = {}
    async with async_playwright() as p:
        launch = {"headless": True}
        if tools().get("chromium"):
            launch["executable_path"] = tools()["chromium"]
        browser = await p.chromium.launch(**launch)
        try:
            context = await browser.new_context(viewport=VIEWPORT, device_scale_factor=1, locale="en-US",
                                                timezone_id="UTC", java_script_enabled=False,
                                                reduced_motion="reduce", color_scheme="light")
            for sid, html_file, static_dirs, png in pages:
                if time.monotonic() > deadline:
                    errors[sid] = "the screenshot stage ran out of time"
                    continue
                page = await context.new_page()
                body = html_file.read_bytes()

                async def handle(route, request, body=body, static_dirs=static_dirs):
                    url = request.url
                    if url.split("#")[0].split("?")[0] == f"{BASE_URL}/__page":
                        await route.fulfill(status=200, body=body, content_type="text/html; charset=utf-8")
                        return
                    if not url.startswith(BASE_URL + "/"):
                        await route.abort()                     # nothing leaves the machine
                        return
                    rel = url[len(BASE_URL) + 1:].split("?")[0].split("#")[0]
                    for d in static_dirs:
                        target = (d / rel).resolve()
                        if target.is_file() and d.resolve() in target.parents and not (d / rel).is_symlink():
                            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                            await route.fulfill(status=200, body=target.read_bytes(), content_type=ctype)
                            return
                    await route.abort()

                await page.route("**/*", handle)
                try:
                    await page.goto(f"{BASE_URL}/__page", wait_until="load", timeout=20000)
                    # Down to the lowest element on the page (not the window's empty
                    # remainder), at most MAX_HEIGHT pixels.
                    bottom = await page.evaluate(_CONTENT_BOTTOM)
                    height = max(MIN_HEIGHT, min(MAX_HEIGHT, int(bottom) + 24))
                    await page.screenshot(path=str(png), animations="disabled", type="png", full_page=True,
                                          clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": height})
                except Exception as exc:
                    errors[sid] = f"the browser could not show the page ({type(exc).__name__})"
                finally:
                    await page.close()
        finally:
            await browser.close()
    return errors


async def capture(workspace_dir: str, inventory: dict, out_dir: str,
                  max_screens: int | None = None, max_states: int | None = None,
                  timeout_s: float | None = None) -> dict:
    """Render the pages and write `SCR-nnnn.png` into `out_dir`. Returns the
    manifest the document is built from (`to_markdown`)."""
    max_screens = max_screens or config.UI_SCREENSHOTS_MAX_PAGES
    max_states = max_states or config.UI_SCREENSHOTS_MAX_STATES
    deadline = time.monotonic() + (timeout_s or config.UI_SCREENSHOTS_TIMEOUT_S)
    workspace = Path(workspace_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"screens": [], "not_rendered": [], "notes": [], "pages": 0}
    status = await asyncio.to_thread(tools)      # Playwright's sync check cannot run on the event loop
    if not status["browser"]:
        manifest["notes"].append("No screenshots: " + "; ".join(status["notes"]) + ".")
        return manifest
    if not status["renderer"]:
        manifest["notes"].append("Pages are static template previews without sample data: "
                                 + "; ".join(status["notes"]) + ".")

    classes = await asyncio.to_thread(ui_mock_data.index_classes, workspace_dir)
    pages, skipped = await asyncio.to_thread(plan, workspace_dir, inventory)
    manifest["not_rendered"] += skipped
    manifest["pages"] = len(pages)

    # Screens, in page order, each page's states in their fixed order, up to the limit.
    screens = []
    for page in pages:
        troot = workspace / page.templates_root
        facts = ui_mock_data.read_template(troot, page.template)
        page.files = [f"{page.templates_root}/{f}" for f in facts.files]
        controller = ui_mock_data.controller_model(workspace_dir, page.endpoint["source"], classes) \
            if page.endpoint else {}
        for st in ui_mock_data.states(controller, facts, classes, max_states):
            what = _what(page)
            if len(screens) >= max_screens:
                manifest["not_rendered"].append({"what": f"{what} — {st.name}", "template": page.template,
                                                 "reason": f"screen limit reached (UI_SCREENSHOTS_MAX_PAGES = "
                                                           f"{max_screens})"})
                continue
            screens.append((f"SCR-{len(screens) + 1:04d}", page, st))

    with tempfile.TemporaryDirectory(prefix="modernizer-ui-") as tmp:
        work = Path(tmp)
        html_dir = work / "html"
        html_dir.mkdir()
        results: dict[str, dict] = {}
        roots = sorted({p.templates_root for _, p, _ in screens})
        for k, troot in enumerate(roots):
            copy = work / f"templates-{k}"
            await asyncio.to_thread(_copy_tree, workspace / troot, copy, (".html", ".htm", ".xml", ".txt", ".css",
                                                                           ".js", ".svg", ".properties"))
            if not status["renderer"]:
                continue
            spec = {"templates": str(copy), "messages": _message_basenames(work, workspace, troot, k), "jobs": [
                {"id": sid, "template": page.template, "model": st.model, "roles": st.roles,
                 "authenticated": st.authenticated, "out": str(html_dir / f"{sid}.html")}
                for sid, page, st in screens if page.templates_root == troot]}
            results.update(await _run_renderer(work, k, spec, deadline - time.monotonic()))

        shots = []
        for sid, page, st in screens:
            k = roots.index(page.templates_root)
            r = results.get(sid, {"ok": False, "error": "the Thymeleaf renderer is not available"})
            if r.get("ok"):
                mode, html_file, note = "rendered", html_dir / f"{sid}.html", ""
            else:
                mode = "static preview"
                html_file = work / f"templates-{k}" / f"{page.template}.html"
                note = f"Template engine: {r.get('error', 'not rendered')}"
            shots.append((sid, html_file, _static_dirs(workspace, page.templates_root), out / f"{sid}.png"))
            manifest["screens"].append({
                "id": sid, "image": f"{sid}.png", "mode": mode, "note": _clean(note, tmp, workspace_dir),
                "template": f"{page.templates_root}/{page.template}.html", "files": page.files,
                "endpoint": page.endpoint, "state": st.name, "description": st.description,
                "model": st.model if mode == "rendered" else {},
            })
        if shots:
            errors = await _screenshot(shots, deadline)
        else:
            errors = {}
    kept = []
    for screen in manifest["screens"]:
        if screen["id"] in errors or not (out / screen["image"]).is_file():
            manifest["not_rendered"].append({"what": f"{_what_from(screen)} — {screen['state']}",
                                             "template": screen["template"],
                                             "reason": errors.get(screen["id"], "no image was produced")})
        else:
            kept.append(screen)
    manifest["screens"] = kept
    return manifest


def _clean(text: str, tmp: str, workspace_dir: str) -> str:
    """Error text without the machine's temporary or workspace paths."""
    text = re.sub(re.escape(tmp) + r"/templates-\d+/", "", text)
    return text.replace(workspace_dir.rstrip("/") + "/", "")


def _what(page: Page) -> str:
    if page.endpoint:
        return f"{page.endpoint['verb']} {page.endpoint['path']}"
    return f"template {page.template}"


def _what_from(screen: dict) -> str:
    e = screen.get("endpoint")
    return f"{e['verb']} {e['path']}" if e else f"template {screen['template']}"


# ── document ────────────────────────────────────────────────────────────────

def _rules_for(screen: dict, ledger: dict | None) -> list[str]:
    """Rules whose source is one of the screen's template files, or its handler method."""
    if not ledger:
        return []
    files = set(screen.get("files") or [screen["template"]])
    handler_file, handler_line = "", 0
    if screen.get("endpoint"):
        handler_file, _, line = screen["endpoint"]["source"].rpartition(":")
        handler_line = int(line) if line.isdigit() else 0
    out = []
    for rule in ledger.get("rules", []):
        for s in rule.get("sources", []):
            if s["path"] in files or (s["path"] == handler_file and s["start"] <= handler_line + 1
                                      and handler_line <= s["end"]):
                out.append(rule["id"])
                break
    return out


def _display(value):
    """Sample data as a reader needs it: dates as text, a list as its first item and a count."""
    if isinstance(value, dict):
        if "$date" in value:
            return value["$date"].replace("T", " ")
        return {k: _display(v) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 1:
            return [_display(value[0]), f"… and {len(value) - 1} more like it"]
        return [_display(v) for v in value]
    return value


def to_markdown(manifest: dict, ledger: dict | None = None, image_prefix: str = "screens/") -> str:
    screens = manifest.get("screens", [])
    lines = ["## UI Screens", "",
             "_Rendered by the pipeline from the repository's own templates with generated sample data — not "
             "screenshots of a running system. Layout, labels, conditions and role-based visibility come from the "
             "templates; every value shown is made up. Scripts are not run._", ""]
    rendered = sum(1 for s in screens if s["mode"] == "rendered")
    previews = len(screens) - rendered
    lines.append(f"{len(screens)} screen{'s' if len(screens) != 1 else ''} of {manifest.get('pages', 0)} "
                 f"page{'s' if manifest.get('pages', 0) != 1 else ''}: {rendered} rendered with sample data, "
                 f"{previews} static template preview{'s' if previews != 1 else ''}; "
                 f"{len(manifest.get('not_rendered', []))} not rendered (listed at the end).")
    for note in manifest.get("notes", []):
        lines += ["", f"> {note}"]
    current = None
    page_default: dict = {}            # page → its first rendered screen, which shows the full sample data
    for s in screens:
        key = (s["template"], json.dumps(s.get("endpoint"), sort_keys=True))
        if key != current:
            current = key
            e = s.get("endpoint")
            title = f"`{e['verb']} {e['path']}`" if e else f"`{s['template'].rsplit('/templates/', 1)[-1]}`"
            lines += ["", f"### {title}", ""]
            if e:
                lines.append(f"- Handler: `{e['handler']}` (`{e['source']}`)")
            else:
                lines.append("- Handler: none found — a template no controller names")
            lines.append(f"- Template: `{s['template']}`")
        rules = _rules_for(s, ledger)
        lines += ["", f"#### {s['id']} · {s['state']}", "",
                  f"- State: {s['description']}",
                  f"- Mode: {'rendered with sample data' if s['mode'] == 'rendered' else 'static template preview — the raw template as a browser shows it, without data'}"]
        if rules:
            lines.append(f"- Rules on this page: {', '.join(rules)}")
        if s.get("note"):
            lines.append(f"- Note: {s['note']}")
        alt = re.sub(r"[\[\]`]", "", f"{s['id']} — {s['state']}")
        lines += ["", f"![{alt}]({image_prefix}{s['image']})"]
        if s["mode"] == "rendered":
            first = page_default.get(key)
            if first is None or first["id"] == s["id"]:
                page_default[key] = s
                data = json.dumps(_display(s.get("model") or {}), indent=2, ensure_ascii=False)
                if len(data) > 2500:
                    data = data[:2500] + "\n… (shortened)"
                lines += ["", "Sample data:", "", "```json", data, "```"]
            else:
                changed = [k for k in sorted(set(s["model"]) | set(first["model"]))
                           if s["model"].get(k) != first["model"].get(k)]
                lines += ["", f"Sample data: as {first['id']}" + (", with " + "; ".join(
                    f"`{k}` = `{json.dumps(_display(s['model'].get(k)), ensure_ascii=False)}`" for k in changed)
                    if changed else "") + "."]
    if manifest.get("not_rendered"):
        lines += ["", "### Not rendered", "", "| Page | Template | Reason |", "|---|---|---|"]
        for n in manifest["not_rendered"]:
            lines.append(f"| {n['what'].replace('|', '/')} | `{n['template']}` | {n['reason'].replace('|', '/')} |")
    if not screens and not manifest.get("not_rendered"):
        lines += ["", "No Thymeleaf pages were found in the confirmed stacks."]
    return "\n".join(lines).rstrip() + "\n"
