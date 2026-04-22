# pydantic-deep Web App

A browser-based AI coding assistant backed by the pydantic-deep agent and the
Potpie code knowledge graph.

## Architecture

```
Browser ──→ Next.js (UI, port 3000)
                  │
                  ↓ AG-UI / HTTP proxy
            Python Agent (Starlette, port 8000)
                  │
                  ↓
         Potpie runtime (Postgres, Neo4j, Redis)
```

Both processes are started together with a single command.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.13.x** | Must match the root venv (`pyproject.toml` requires `==3.13.*`) |
| **uv** | `pip install uv` or `curl -Lsf https://astral.sh/uv/install.sh \| sh` |
| **Node.js ≥ 18** | For the Next.js UI |
| **npm ≥ 9** | Included with Node.js |
| **Postgres / Neo4j / Redis** | Managed by Potpie — credentials go in `code-graph-providers/potpie/.env` |

---

## Setup (one-time)

### 1 — Install Python dependencies

```bash
# From the repo root
make install          # creates .venv and installs all packages
# or manually:
uv venv && uv pip install -e ".[dev]"
```

### 2 — Configure Potpie services

Copy and fill in the Potpie env file:

```bash
cp code-graph-providers/potpie/.env.example code-graph-providers/potpie/.env
# Edit .env: set POSTGRES_SERVER, NEO4J_URI, REDIS_URL, etc.
```

### 3 — Set an LLM API key

The agent auto-detects available keys in this order:

1. `PYDANTIC_DEEP_MODEL` env var (explicit model string, e.g. `anthropic:claude-sonnet-4-5`)
2. `.pydantic-deep/config.toml` `[model]` field in the repo root
3. `ANTHROPIC_API_KEY` → uses Anthropic Claude
4. `OPENAI_API_KEY` → uses OpenAI GPT-4o
5. Fallback: GitHub Copilot via LiteLLM (`litellm:github_copilot/gpt-4o`)

Export the key you want to use:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# or
export OPENAI_API_KEY="sk-..."
```

### 4 — Install Node dependencies

```bash
cd apps/web
npm install
```

---

## Starting the app

### Quick start (recommended)

```bash
# From repo root
./apps/web/start.sh
```

This script:
- Verifies the root `.venv` exists
- Installs Node deps if missing
- Finds a free port starting from 3000
- Runs `npm run dev` (starts both UI and agent concurrently)

### Manual start

```bash
cd apps/web
npm run dev
```

This runs two processes in parallel:

| Process | Command | Default port |
|---|---|---|
| **UI** | `next dev` | 3000 |
| **Agent** | `python agent/start.py` | 8000 (auto-selects next free) |

`agent/start.py` writes `AGENT_URL=http://localhost:<port>` to
`apps/web/.env.local` so the Next.js proxy always knows where the agent is.

### Custom ports

```bash
UI_PORT=3001 AGENT_PORT=8001 npm run dev
```

---

## Usage

1. Open `http://localhost:3000` in your browser.
2. **Repo & Setup** (left sidebar) — enter a local repo path and branch, then
   click **Parse Repo**. This builds the code knowledge graph in the background.
3. **Active project** — once parsing completes the project appears in the
   dropdown. Select it to activate the knowledge graph for chat and wiki.
4. **Wiki** (left sidebar) — expand the Wiki section and click **Generate Wiki**
   to create documentation for the selected project.
5. **Chat** (bottom-right button) — open the CopilotKit chat panel and talk to
   the agent about the active codebase.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `UI_PORT` | `3000` | Port for the Next.js dev server |
| `AGENT_PORT` | `8000` | Starting port for the Python agent |
| `PYDANTIC_DEEP_MODEL` | _(auto)_ | Override the LLM model string |
| `POTPIE_USER_ID` | `defaultuser` | User ID passed to the Potpie runtime |
| `DEBUG` | `false` | Set to `true` to enable uvicorn auto-reload |

Variables in `code-graph-providers/potpie/.env` are loaded automatically by
the agent at startup.

---

## Running tests

```bash
cd apps/web/agent
python -m pytest tests/ -v
```
