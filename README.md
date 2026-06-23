# App Modernizer

An AI-powered application modernization platform that helps engineering teams migrate legacy codebases to modern architectures. The platform uses an agentic workflow driven by **Google Gemini** to reverse-engineer source code, generate a Business Requirements Document (BRD) and Technical Specification, produce a migration plan, and finally generate the target codebase — with human review and approval at every key step.

---

## Supported Modernization Patterns

| Pattern | From | To |
|---|---|---|
| Java Version Upgrade | Java 17 | Java 25 |
| Language Migration | Java | Go |
| Framework Migration | Java / Spring Boot | Quarkus |
| Integration Migration | TIBCO BusinessWorks | Java Spring Boot |

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
  - **Technical Specification tab** — review Mermaid dependency graphs, API contracts, data models, and migration impact matrix
- Allow uploading additional context files (Swagger, OpenAPI specs, design diagrams) to enrich plan generation
- Show the **Migration Plan** for review and approval before code generation begins
- Display the final generated code files in a syntax-highlighted file browser with download support

**Tech stack:** React 18, TypeScript, Vite, Tailwind CSS, react-markdown, Mermaid, react-syntax-highlighter, Lucide icons

---

### Backend (`modernizer-backend`)

A Python FastAPI service that orchestrates a multi-step agentic pipeline. Each modernization pattern has its own set of **Google ADK `LlmAgent`** instances powered by Gemini.

**Key responsibilities:**
- Receive and extract uploaded repository ZIP files
- Create an ADK session to persist state across the full pipeline
- Run the agentic workflow as a background task:
  1. **Reverse Engineering** — analyse the source code and produce Analysis + BRD + Technical Specification (with Mermaid diagrams) in a single Gemini call
  2. **Analysis Review (HITL)** — pause and wait for human confirmation of BRD and Technical Spec
  3. **Plan Generation** — generate a detailed `plan.md` using the confirmed BRD, Technical Spec, and any uploaded context files
  4. **Plan Review (HITL)** — pause and wait for human confirmation of the migration plan
  5. **Code Generation** — generate the fully migrated target codebase
- Stream all AI output in real time to the frontend via **Server-Sent Events (SSE)**
- Expose REST endpoints for human-in-the-loop confirmations and context file uploads

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
2. Select a modernization pattern (e.g. Java → Quarkus)
3. Upload your project as a **.zip** archive
4. Watch the AI reverse-engineer your codebase in real time
5. Review the generated **BRD** and **Technical Specification** — edit either document inline and optionally upload Swagger / OpenAPI / design files
6. Click **Confirm Analysis & Generate Plan**
7. Review the **Migration Plan** — edit if needed, then confirm
8. The AI generates the fully migrated target code
9. Browse files in the code viewer, copy, or **Download All**

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
│   │       ├── BRDReview.tsx        # Two-tab editor with Mermaid rendering
│   │       ├── PlanReview.tsx
│   │       └── CodeOutput.tsx
│   └── package.json
│
└── modernizer-backend/              # Python backend
    ├── main.py                      # FastAPI app + workflow orchestration
    ├── requirements.txt
    ├── .env.example
    ├── agents/
    │   ├── __init__.py              # ADK runner registry
    │   ├── config.py                # Model / env config
    │   ├── java17_to_java25/        # Java 17 → Java 25 agents
    │   ├── java_to_go/              # Java → Go agents
    │   ├── java_to_quarkus/         # Java/Spring → Quarkus agents
    │   ├── tibco_to_springboot/     # TIBCO BW → Spring Boot agents
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
- Large repositories are truncated to ~100 KB of source text before being sent to Gemini
