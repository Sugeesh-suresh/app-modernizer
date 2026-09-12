# Stella Modernizer

An AI-powered application modernization platform that helps engineering teams migrate legacy codebases to modern architectures. The platform uses an agentic workflow driven by **Google Gemini** to reverse-engineer source code, generate a Business Requirements Document (BRD) and Technical Specification, produce a migration plan, and finally generate the target codebase — with human review and approval at every key step.

---

## Supported Modernization Patterns

| Pattern | From | To | Phase | Reverse-engineering? |
|---|---|---|---|---|
| Java Version Upgrade | Java 11 | Java 25 | Direct upgrade | No — real-repo scan, real `mvn compile` validate/fix loop |
| Java Version Upgrade | Java 17 | Java 25 | Rewrite | Yes — full BRD + Technical Spec |
| Language Migration | Java | Go | Rewrite | Yes — full BRD + Technical Spec |
| Framework Migration | Java / Spring Boot | Quarkus | Rewrite | Yes — full BRD + Technical Spec, plus a validate/fix loop (max 4 iterations) |
| Integration Migration | TIBCO BusinessWorks | Java Spring Boot | Rewrite | Yes — full BRD + Technical Spec |
| Framework Version Upgrade | .NET Framework 4 | .NET 8 | Direct upgrade | No |
| Framework Version Upgrade | .NET 8 | .NET 9 | Direct upgrade | No |
| Framework Version Upgrade | .NET 9 | .NET 10 | Direct upgrade | No |
| Framework Version Upgrade | .NET 10 | .NET 11 (preview) | Direct upgrade | No |
| Language Migration | C# .NET | Java / Spring Boot | Rewrite | Yes — full BRD + Technical Spec |

**Direct upgrade** patterns skip the reverse-engineering / BRD phase entirely and go straight from upload to plan generation, since the target is a newer version of the same language/framework rather than a rewrite. **Rewrite** patterns run the full pipeline: reverse-engineer → BRD/Tech Spec review → plan → plan review → code generation.

---

## Architecture Overview

```
modernizer-app/        ← React + TypeScript frontend (Vite + Tailwind)
modernizer-backend/    ← Python backend (FastAPI + Google ADK + Gemini)
```

### Frontend (`modernizer-app`)

A single-page React application that guides users through the full modernization workflow via a clean, dark-themed UI.

**Key responsibilities:**
- Present modernization pattern selection cards
- Accept repository upload (ZIP file)
- Display live streaming output from the AI agents via Server-Sent Events (SSE)
- Show a step-by-step progress indicator across the full pipeline
- Provide an **Analysis Review** screen with two editable panels:
  - **BRD tab** — review and edit the AI-generated Business Requirements Document
  - **Technical Specification tab** — review the dependency graph and migration groups, API contracts, data models, and migration impact matrix (diagrams are plain-text trees and tables — no diagram library)
- Allow uploading additional context files (Swagger, OpenAPI specs, design diagrams) to enrich plan generation
- Show the **Migration Plan** for review and approval before code generation begins
- Display the final generated code files in a syntax-highlighted file browser with download support

**Tech stack:** React 18, TypeScript, Vite, Tailwind CSS, react-markdown, react-syntax-highlighter, Lucide icons

---

### Backend (`modernizer-backend`)

A Python FastAPI service that orchestrates a multi-step agentic pipeline. Each modernization pattern has its own set of **Google ADK `LlmAgent`** instances powered by Gemini, registered in `agents/__init__.py`'s `PATTERN_RUNNERS` map.

**Key responsibilities:**
- Receive and extract uploaded repository ZIP files
- Create an ADK session to persist state across the full pipeline
- Run the agentic workflow as a background task:
  1. **Reverse Engineering** *(rewrite patterns only)* — analyse the source code and produce Analysis + BRD + Technical Specification (with plain-text diagrams and tables) in a single Gemini call
  2. **Analysis Review (HITL)** *(rewrite patterns only)* — pause and wait for human confirmation of BRD and Technical Spec
  3. **Plan Generation** — generate a detailed `plan.md` (direct-upgrade patterns work straight from the uploaded source; rewrite patterns use the confirmed BRD, Technical Spec, and any uploaded context files)
  4. **Plan Review (HITL)** — pause and wait for human confirmation of the migration plan
  5. **Code Generation** — generate the fully migrated target codebase
- Stream all AI output in real time to the frontend via **Server-Sent Events (SSE)**
- Expose REST endpoints for human-in-the-loop confirmations and context file uploads

**Skills-based agent instructions:** every agent loads its prompt and reference material at runtime from a `SKILL.md` (+ `references/*.md`) directory under `agents/skills/<skill-name>/` via ADK's `SkillToolset`, instead of hard-coding the instruction string in Python. This keeps long migration checklists and before/after code patterns out of the agent-wiring code and lets each pattern's domain knowledge be edited independently.

**Two agent architectures:**
- **Text-blob patterns** (most patterns) — agents read a single concatenated text dump of the uploaded repo and return the fully migrated codebase as fenced code blocks, parsed by `agents/shared/code_parser.py`.
- **Real-workspace pattern** (`java11-to-java25` only) — the uploaded repo is unpacked to a real per-session directory on disk, and the `modifier`/`validator`/`fixer` agents get real `list_files`/`read_file`/`write_file`/`run_command` tools (`agents/java11_to_java25/tools.py`). The `validator` agent actually shells out to `mvn compile` and loops with a `fixer` agent (max 3 iterations) until the build passes.

`java-to-quarkus` also runs a validate/fix `LoopAgent` (max 4 iterations) after code generation, but — unlike `java11-to-java25` — validation happens against the generated text blob rather than a real Maven build.

**Tech stack:** Python 3.12, FastAPI, Google ADK (`google-adk`), Google Gemini (`gemini-2.5-flash`), Uvicorn, Pydantic

---

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| Gemini API Key | [Get one here](https://aistudio.google.com/app/apikey) |

---

## Setup

### 1. Clone the repository
```bash
git clone https://github.com/Sugeesh-suresh/app-modernizer.git
cd app-modernizer
```

### 2. Configure the backend environment
```bash
cd modernizer-backend
cp .env.example .env
```

Edit `.env` and add your Gemini API key:
```
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

### 3. Install backend dependencies
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 4. Install frontend dependencies
```bash
cd ../modernizer-app
npm install
```

---

## Launching the Application

Open **two terminal windows** from the project root.

### Terminal 1 — Backend (port 8000)
```bash
cd modernizer-backend
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2 — Frontend (port 5173)
```bash
cd modernizer-app
npm run dev
```

Open **http://localhost:5173** in your browser.

### Verify both services are running
```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","framework":"google-adk"}
```

---

## Stopping the Applications

```bash
kill -9 $(lsof -ti:8000,5173) 2>/dev/null
```

---

## Usage

1. Open **http://localhost:5173**
2. Select a modernization pattern (e.g. Java → Quarkus, or .NET 8 → .NET 9)
3. Upload your project as a **.zip** archive
4. **Rewrite patterns** — watch the AI reverse-engineer your codebase in real time, review the generated **BRD** and **Technical Specification** (edit inline, optionally upload Swagger / OpenAPI / design files), then click **Confirm Analysis & Generate Plan**. **Direct-upgrade patterns** skip straight to plan generation.
5. Review the **Migration Plan** — edit if needed, then confirm
6. The AI generates the fully migrated target code (for `java11-to-java25`, this includes a real `mvn compile` validate/fix loop against your actual repo)
7. Browse files in the code viewer, copy, or **Download All**

---

## Project Structure

```
app-modernizer/
├── README.md
├── modernizer-app/                  # React frontend
│   ├── src/
│   │   ├── App.tsx                  # Main app + SSE state machine
│   │   ├── api.ts                   # Backend API client
│   │   ├── types/index.ts           # Shared TypeScript types
│   │   ├── data/patterns.ts         # Pattern config (cards, colors, benefits)
│   │   └── components/
│   │       ├── Header.tsx
│   │       ├── PatternSelection.tsx
│   │       ├── FileUpload.tsx
│   │       ├── StepIndicator.tsx
│   │       ├── ProcessingView.tsx
│   │       ├── BRDReview.tsx        # Tabbed editor with plain-text diagram rendering
│   │       ├── PlanReview.tsx
│   │       └── CodeOutput.tsx
│   └── package.json
│
└── modernizer-backend/              # Python backend
    ├── main.py                      # FastAPI app + workflow orchestration
    ├── requirements.txt
    ├── .env.example
    ├── agents/
    │   ├── __init__.py              # ADK runner registry (PATTERN_RUNNERS, TARGET_LANGS)
    │   ├── config.py                # Model / env config
    │   ├── java11_to_java25/        # Java 11 → Java 25 — real-workspace + mvn build/validate/fix loop
    │   ├── java17_to_java25/        # Java 17 → Java 25 agents
    │   ├── java_to_go/              # Java → Go agents
    │   ├── java_to_quarkus/         # Java/Spring → Quarkus agents (+ validate/fix loop)
    │   ├── tibco_to_springboot/     # TIBCO BW → Spring Boot agents
    │   ├── dotnet4_to_dotnet8/      # .NET Framework 4 → .NET 8 agents
    │   ├── dotnet8_to_dotnet9/      # .NET 8 → .NET 9 agents
    │   ├── dotnet9_to_dotnet10/     # .NET 9 → .NET 10 agents
    │   ├── dotnet10_to_dotnet11/    # .NET 10 → .NET 11 (preview) agents
    │   ├── dotnet_to_java/          # C# .NET → Java agents
    │   ├── skills/                  # SKILL.md + references/*.md per agent, loaded via SkillToolset
    │   └── shared/                  # File parser, code parser utilities
    └── models/
        └── schemas.py               # Pydantic request/response models
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | — | Your Google Gemini API key |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model to use |
| `DATABASE_URL` | No | — | SQLite/Postgres URL for persistent sessions (omit for in-memory) |

---

## Notes

- The `.env` file is excluded from version control — never commit your API key
- Each modernization session is stateful; refreshing the browser mid-workflow will lose progress (use in-memory mode only for development)
- Large repositories are truncated to ~100 KB of source text before being sent to Gemini (text-blob patterns); `java11-to-java25` instead extracts the real repo to disk, capped at 5,000 files / 100 MB
