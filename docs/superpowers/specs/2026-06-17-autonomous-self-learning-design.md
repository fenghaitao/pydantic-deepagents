# Autonomous Self-Learning for pydantic-deep — Design

- **Date:** 2026-06-17
- **Status:** Draft (design)
- **Branch:** `feat/scoped-memory`
- **Depends on:** `feat/scoped-memory` (scoped/typed memory + `consolidate_session`), `pydantic_deep/improve/` (analyzer/extractor/synthesizer), `pydantic_deep/toolsets/skills/`, `apps/bridge/` (BridgeRunner), `apps/deepresearch` (SessionManager)

## Summary

pydantic-deep already has the *mechanisms* for self-improvement — `consolidate_session()`
(memory), the `improve/` pipeline (context files + skills), and the skills toolset — but
they are **manually triggered** (`/improve`, explicit tool calls, human approval). This
design adds the missing **autonomy layer**: a closed loop that, after a turn completes,
**automatically** decides what to remember and which skill to create/refine, plus an
**idle curator** that keeps the memory + skill libraries coherent. It deliberately reuses
the existing pipelines; the new code is orchestration and guardrails, not new extraction
logic.

## Motivation

A self-improving agent gets better at *you* and at *recurring tasks* without being asked.
Today a pydantic-deep user must run `/improve` by hand and approve diffs, so most sessions
produce zero learning. The goal is to convert the existing manual primitives into
autonomous behaviour while preserving pydantic-deep's strengths: the clean async engine,
the `BackendProtocol` abstraction, typed outputs, and per-session sandboxes.

The `feat/scoped-memory` spec explicitly lists *"Auto-running consolidation on every run"*
as a **non-goal** — the mechanism (`consolidate_session`) was built and the autonomy
deferred. This design picks up exactly there.

## Goals

- **Autonomous, post-turn learning** — fire memory consolidation and skill review after
  turns, with no user action.
- **Off the hot path** — never block the user's next message; run as a background
  `asyncio` task.
- **Unified** — one reviewer drives *both* memory (`consolidate_session`) and skills
  (`improve/`).
- **Idle curator** — consolidate/prune/archive using signals the memory layer already
  computes (`last_used_at`, `conflict_group`, `staleness_days`, `confidence`).
- **Safe by construction** — the review fork runs a restricted toolset; destructive ops
  are recoverable (archive, never delete).
- **Cheap** — gated cadence + a small auxiliary model.
- **Multi-tenant aware** — works per-session / per-uid so the WeChat bridge and the
  deepresearch server each get isolated learning.
- 100% test coverage; Pyright + MyPy strict clean (repo convention).

## Non-Goals

- Replacing the manual `/improve` flow (it stays for interactive, human-approved deep
  passes).
- Semantic/vector memory, memory versioning, team sync (already out of scope in
  scoped-memory).
- A dialectic user model in v1 (specified as optional Phase 3 via Honcho-MCP).
- Auto-deletion of memories or skills (the curator **archives**, never deletes).

## Background — what already exists (reuse, don't rebuild)

| Capability | Where | Today |
|---|---|---|
| Extract ≤3 memories from a session | `toolsets/scoped_memory/consolidator.py::consolidate_session` | app-triggered |
| Typed/scoped memory store + ranking + staleness + conflict | `toolsets/scoped_memory/` | done (branch) |
| Insight extraction → synthesis → apply to context/skills | `improve/` (`analyzer`, `extractor`, `synthesizer`) | manual `/improve` |
| Agent-callable improve | `toolsets/improve.py::ImproveToolset` | manual |
| Skill CRUD (create/patch/list) | `toolsets/skills/` | manual / `skill-creator` |
| Per-session isolated sandbox + checkpoints/fork | `apps/deepresearch` `SessionManager` | done |
| Per-uid runner | `apps/bridge/runner.py` `BridgeRunner` | done |

## Architecture

```
                 turn completes (any surface)
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
   user sees final answer      ReviewRunner.maybe_review_turn(messages)   ← async task, off hot path
                                        │  (gated: cadence / min_messages / signal)
                                        ▼
                          restricted-toolset agent run (cheap model)
                          ├── memory pass  → consolidate_session()    [scoped_memory]
                          └── skill pass   → improve pipeline          [improve/ + skills toolset]
                                        │
                                writes via BackendProtocol (scope-aware)

                 idle (no active task for N min)
                          │
                          ▼
                   Curator.run()  → consolidate conflicts, archive stale,
                                     patch/merge agent-created skills
                                     (uses last_used_at / conflict_group / staleness_days)
```

## Component 1 — Post-turn Background Review (core)

New module: `pydantic_deep/learning/review_runner.py`

```python
class ReviewRunner:
    def __init__(self, *, model: Model | str, memory_scope: str = "project",
                 cadence: int = 3, min_messages: int = 6,
                 enable_memory: bool = True, enable_skills: bool = True): ...

    async def maybe_review_turn(self, messages: list[ModelMessage],
                                deps: Any, turn_index: int) -> ReviewReport | None:
        """Fire the review iff the cadence/signal gate passes. Never raises."""
```

Behaviour:

- **Trigger**: called at each surface's post-turn point; internally **gated** (every
  `cadence` turns, or on a cheap signal — user correction phrase, novel tool sequence —
  and `min_messages`).
- **Off the hot path**: surfaces call `asyncio.create_task(...)`; failures are logged,
  never surfaced to the user.
- **Restricted toolset**: the review agent gets **only** `ScopedMemoryToolset` + skills
  write tools. Shell/file/web/browser are denied. (A self-review must not run arbitrary
  commands.)
- **Cheap model**: defaults to a small/auxiliary model, independent of the main agent's
  model.
- **Two passes**:
  - *Memory* → `consolidate_session(messages, model, backend, scope)`.
  - *Skills* → run the `improve/` pipeline scoped to this session with
    `auto_apply=high_confidence_only`; lower-confidence proposals are queued.

Integration points (one line at each surface):

- **Bridge** — `apps/bridge/runner.py::_execute`, after
  `self._histories[uid] = run.result.all_messages()`.
- **deepresearch** — `_run_agent_task`, after `_persist_history(session)`.
- **CLI** — turn-end in `apps/cli/run.py`.

> Recommendation: expose a single engine hook (e.g. an `Agent`-level `on_turn_complete`)
> so all three surfaces inherit the trigger instead of duplicating it.

## Component 2 — Curator (idle maintenance)

New module: `pydantic_deep/learning/curator.py`

- **Trigger**: inactivity-based (no running task for `idle_minutes`, last run >
  `interval_hours`). Reuses existing schedulers (`apps/bridge/jobs.py`, deepresearch
  `start_cleanup_loop`).
- **Inputs it already has** (from `feat/scoped-memory`): `last_used_at` (reserved as a
  *cleanup* signal — exactly this use), `conflict_group`, `staleness_days`, `confidence`.
- **Actions**:
  - **Memory**: reconcile slug-conflicting entries (supersede lower-confidence), archive
    stale low-confidence entries, rebuild indices.
  - **Skills**: consolidate duplicates, archive unused (old `last_used_at`), patch wrong
    ones — **agent-created only** (provenance: bundled vs created).
- **Invariants**: never auto-delete (archive, recoverable); pinned items skip
  transitions; uses the cheap model.

## Component 3 — Unified review & write contract

A single `ReviewReport` captures both passes:

```python
@dataclass
class ReviewReport:
    memories_saved: list[str]
    skills_changed: list[tuple[str, str]]   # (skill_name, "create"|"patch"|"archive")
    deferred: list[ProposedChange]          # low-confidence → approval queue
```

Write rules:

- Bias the skill pass to **patch existing over create new** (keep skills class-level).
- All writes go through `BackendProtocol` so they land in the right sandbox/scope.

## Component 4 — Approval model (per surface)

- **CLI**: reuse `apps/cli/modals/improve_review.py` for deferred low-confidence changes;
  high-confidence auto-applied.
- **deepresearch server**: surface deferred changes over the existing WS approval channel.
- **Bridge / headless**: no UI → **auto-apply high-confidence, archive-not-delete**;
  optionally a `!review` command to list/accept recent changes.

## Component 5 (Phase 3, optional) — Dialectic user model

Scoped memory is typed facts, not a reasoned evolving model of the user. Two paths:

- **Honcho via MCP** (low effort) — pydantic-deep already supports MCP; add Honcho's MCP
  server for dialectic user modelling.
- **`USER.md` synthesis** (self-contained) — a review sub-pass that maintains an evolving
  user profile.

Recommendation: Honcho-MCP first to validate value.

## Multi-tenant / scope mapping

- `project` scope = `ctx.deps.backend` (the run's sandbox). With **per-uid backends** (the
  bridge isolation fix), project memory is **automatically per-user**.
- Optionally namespace `user` scope by uid for per-user global memory.
- Result: scoped memory + per-uid sandboxes ⇒ multi-tenant learning with no extra
  learning-layer code.

## Locked design decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Trigger model | Post-turn async task, **gated** | Off hot path; cost control |
| 2 | Review toolset | **Restricted** (memory+skills only) | Safety: no arbitrary commands |
| 3 | Review model | **Cheap/auxiliary**, configurable | Autonomy ⇒ cost matters |
| 4 | Reuse vs build | **Reuse** `consolidate_session` + `improve/` | Mechanisms already exist |
| 5 | Skill bias | **Patch > create** | Avoid flat one-session skill sprawl |
| 6 | Destructive ops | **Archive, never delete** | Recoverable |
| 7 | Curator trigger | **Idle-based**, not cron | No daemon; matches existing loops |
| 8 | Provenance | Curate **agent-created only** | Don't rewrite bundled/user skills |
| 9 | Dialectic model | **Phase 3, optional, Honcho-MCP** | Not required for v1 value |
| 10 | Conflict on consolidation | **Supersede or defer to curator** | Prevent conflicting-pair growth |

## Cost model

- Per-turn review cost ≈ one small-model call every `cadence` turns. At `cadence=3` and a
  cheap model, overhead is a small fraction of main-agent cost.
- Curator cost is amortised (idle, infrequent).
- Both independently disable-able via config.

## Config surface

```yaml
learning:
  review:
    enabled: true
    model: <cheap-model-id>
    cadence: 3
    min_messages: 6
    memory: true
    skills: true
    auto_apply: high_confidence   # high_confidence | never | always
  curator:
    enabled: true
    idle_minutes: 10
    interval_hours: 6
    staleness_days: 7
  dialectic:
    provider: none   # none | honcho_mcp | user_md
```

## Testing strategy

- `TestModel` for the review/curator agents (deterministic, no network) — same approach as
  the scoped-memory branch.
- Unit: gating logic, restricted-toolset enforcement, archive-not-delete, conflict
  supersede.
- Integration: post-turn hook fires once per cadence across all three surfaces against a
  temp backend; per-uid isolation verified.
- Coverage 100%; strict typing.

## Phased plan

1. **Phase 1 — Autonomous memory.** `ReviewRunner` (memory pass only) + engine post-turn
   hook + bridge/CLI/deepresearch wiring + config + tests. Smallest end-to-end win.
2. **Phase 2 — Skills + curator.** Add the skill pass (reusing `improve/`),
   provenance/usage tracking, and the idle curator.
3. **Phase 3 — Dialectic.** Honcho-MCP (or `USER.md` synthesis).

## Open questions

- Engine hook shape: does `pydantic_deep.Agent` expose a clean `on_turn_complete` seam, or
  is per-surface wiring acceptable for v1?
- Signal-based vs purely cadence-based triggering — start cadence-only, add
  correction-detection later?
- Where does the deferred-changes approval queue persist for headless/bridge?

## Appendix — provenance of ideas (Hermes mapping)

The autonomy patterns are adapted from the Hermes agent's self-improvement loop:

- Post-turn fork → `agent/background_review.py`
- Idle curator, archive-not-delete, provenance → `agent/curator.py`, `tools/skill_usage.py`
- Restricted review toolset / off-hot-path → `background_review.py` (whitelist + daemon thread)
- Dialectic user model → Honcho (`plugins/memory/honcho/`)
