# Scoped, Typed Agent Memory on `BackendProtocol` — Design

- **Date:** 2026-06-04
- **Status:** Approved (design); pending spec review
- **Branch:** `feat/scoped-memory`

## Summary

Port the rich, Claude-Code-style memory model from the vendored `cheetahclaws/memory/`
package onto pydantic-deep's `BackendProtocol`/capability architecture. The new system
adds file-per-memory storage, a 4-type taxonomy, frontmatter metadata
(confidence/source/last_used_at/conflict_group), conflict detection, recency ranking,
staleness warnings, keyword + AI search, and app-triggered AI consolidation — while
keeping all storage on the backend abstraction (works with `StateBackend`,
`LocalBackend`, `DockerSandbox`, `CompositeBackend`) and integrating natively via
`FunctionToolset` + `AbstractCapability`.

The existing single-blob `AgentMemoryToolset` / `MemoryCapability` remain functional and
are marked `@deprecated`, pointing to the new system.

### Canonical paths (authoritative)

The new system uses the repo-standard `.pydantic-deep/memory` convention in both scopes:

- **user** scope → dedicated `LocalBackend`, base `~/.pydantic-deep/memory/{agent_name}/`
- **project** scope → run's backend, base (relative) `.pydantic-deep/memory/{agent_name}/`

## Motivation

The current memory toolset (`pydantic_deep/toolsets/memory.py`) stores one append-only
`MEMORY.md` blob per agent with three tools (`read_memory`, `write_memory`,
`update_memory`). It has no types, scopes, search, ranking, conflict handling, or
staleness awareness. The cheetahclaws design (documented in `cheetahclaws/docs/memory/`)
is a faithful, feature-rich reimplementation of Claude Code's memory system. This work
brings that capability into pydantic-deep without abandoning the backend abstraction that
the rest of the project depends on.

### Problem with cheetahclaws as-is

cheetahclaws writes directly to the OS filesystem (`Path.home()`, `Path.cwd()`),
synchronously, outside any backend abstraction. That is why it has no Docker support and
cannot run against an in-memory or composite backend. The port must not inherit this
limitation.

## Goals

- Full feature parity with the cheetahclaws memory model (see Feature Matrix).
- All storage routed through `BackendProtocol` — no raw filesystem access in the core.
- True cross-project **user** (global) scope plus per-run **project** (local) scope.
- Native pydantic-ai integration (`FunctionToolset.get_instructions`, `AbstractCapability`).
- Per-agent isolation preserved (`agent_name` namespacing, matching current behavior).
- 100% test coverage; Pyright + MyPy strict clean.

## Non-Goals

- Migrating existing single-blob `MEMORY.md` files into the new format (the deprecated
  toolset still reads them; no auto-migration).
- Semantic/vector search, memory versioning, decay/auto-deletion, team sync (listed as
  "future" in cheetahclaws docs — out of scope).
- Auto-running consolidation on every run (consolidation is app-triggered only).

## Locked Design Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Feature scope | **Full parity** | Capture the complete model; coverage handled via `TestModel`. |
| 2 | Scope storage | **Dedicated user backend (B)** | A single project-rooted backend cannot provide true cross-project user memory. User scope gets its own `LocalBackend`. |
| 3 | `agent_name` × scope | **`agent_name` namespaces both** | Preserves the repo's per-subagent memory isolation (`clone_for_subagent`, `share_todos`). |
| 4 | Compatibility | **New alongside, deprecate old** | Honors the repo `@deprecated` convention; no breakage; clean test boundaries. |
| 5 | AI mechanism | **Internal `Agent`, app-triggered** | `consolidate_session` + `use_ai` ranking use a throwaway pydantic-ai `Agent` with a Pydantic `output_type`; `TestModel`-friendly; no lifecycle-hook guesswork. |
| 6 | Path convention | **`.pydantic-deep/memory`** | Matches the established repo convention used by skills/logs/config. |
| 7 | Recency source | **`created` frontmatter date only** | Backends (State/Docker) do not reliably expose mtime. Ranking uses immutable `created`; `last_used_at` is a cleanup signal, **not** a ranking input (see Decision 9). |
| 8 | Sync/async split | **Store sync, tools async** | Matches the existing `read_backend_bytes`/`backend.write` pattern; `BackendProtocol` methods are sync. |
| 9 | `last_used_at` semantics | **Cleanup signal, not ranking input** | Feeding usage-recency into the score inflates freshness on every search (cheetahclaws' latent bug). Decoupled so touching returned entries is harmless. |
| 10 | Staleness threshold | **Configurable `staleness_days`, default 7** | The warning is a *code-state* caveat ("verify file:line before asserting"), not a relevance signal. 7 days is a compromise from cheetahclaws' aggressive 1-day default. |
| 11 | `conflict_group` | **Advisory metadata only** | Displayed in list/search output; never drives auto-detection or auto-surfacing. `check_conflict` is slug-based only. YAGNI on auto-resolution. |

## Path & Scope Layout

| Scope | Storage | Default location |
|-------|---------|------------------|
| **user** (global, cross-project) | dedicated `LocalBackend` | `~/.pydantic-deep/memory/{agent_name}/` |
| **project** (local) | the run's backend (`ctx.deps.backend`) | `.pydantic-deep/memory/{agent_name}/` (relative path) |

Within each `{agent_name}/` namespace, individual memory files live directly in the scope
root, with a `MEMORY.md` index per `(agent_name, scope)`:

```
~/.pydantic-deep/memory/main/        # user scope (dedicated backend)
├── MEMORY.md                        # auto-built index
├── user_prefers_tests.md
└── feedback_no_db_mocks.md

<backend root>/.pydantic-deep/memory/main/   # project scope (run backend)
├── MEMORY.md
└── project_api_migration.md
```

### Backend path notes (verified empirically)

- **Relative paths** (`.pydantic-deep/memory/...`, no leading slash) work on both
  `StateBackend` (dict key) and `LocalBackend` (`<root>/.pydantic-deep/...`, persisted).
  Absolute backend paths (leading `/`) are **rejected by `LocalBackend`** as "outside
  allowed directories" and the failing write returns an error `WriteResult`. The project
  scope therefore uses a **relative** base path.
- Listing uses `backend.glob_info("*.md", <dir>)`; confirmed working on State + Local.
  `StateBackend` normalizes relative writes to leading-slash keys and returns those from
  `glob_info`/`ls_info`, so the store reads back via the **returned** `path`, not the
  input string.
- All backend writes return a `WriteResult`; the store **must check `result.error`** (the
  legacy toolset ignores it, which is the silent-failure bug above).

## Architecture

New subpackage `pydantic_deep/toolsets/scoped_memory/`, mirroring cheetahclaws' module
split but backend-backed:

| Module | Responsibility |
|--------|----------------|
| `types.py` | `MemoryEntry` dataclass (name, description, type, content, file_path, created, scope, confidence, source, last_used_at, conflict_group); `MEMORY_TYPES`; `MEMORY_TYPE_DESCRIPTIONS`; `MEMORY_SYSTEM_PROMPT`; `WHAT_NOT_TO_SAVE`; `MEMORY_FORMAT_EXAMPLE`. |
| `store.py` | Backend CRUD (sync): `save_memory`, `delete_memory`, `load_entries`, `load_index`, `search_memory`, `check_conflict`, `touch_last_used`, `_rewrite_index`, `get_index_content`; helpers `_slugify`, `parse_frontmatter`, `_format_entry_md`. All take an explicit `backend` + base path. |
| `scan.py` | Frontmatter-date freshness: `memory_age_days`, `memory_age_str`, `memory_freshness_text(age_days, staleness_days)`. Age from `created`; warning emitted only when `age_days > staleness_days`. |
| `context.py` | `get_memory_context` (index injection for both scopes), `find_relevant_memories` (keyword + optional AI), `truncate_index_content` (200 lines / 25 KB, with warning). |
| `consolidator.py` | `consolidate_session(messages, model)` — internal pydantic-ai `Agent` with structured `output_type`; hard cap of 3; confidence-aware conflict skip; `source="consolidator"`. |
| `toolset.py` | `ScopedMemoryToolset(FunctionToolset)` — tools `MemorySave`, `MemorySearch`, `MemoryDelete`, `MemoryList`; `get_instructions()` for prompt injection. |

Capability `ScopedMemoryCapability(AbstractCapability)` in
`pydantic_deep/capabilities/scoped_memory.py`, parallel to existing `MemoryCapability`.
Holds the project-scope config and the dedicated user-scope backend; wires the toolset and
instructions. Configurable fields include: `agent_name`, `user_backend` (default factory
→ `LocalBackend(~/.pydantic-deep/memory)`), `project_base` (default
`.pydantic-deep/memory`), `staleness_days` (default 7), `max_index_lines` (200),
`max_index_bytes` (25_000), and an optional `ai_model` for `use_ai` ranking (defaults to a
fast model, overridable).

### Resolving backend + base path per scope

The store functions are scope-agnostic — they receive `(backend, base_dir)`. The toolset/
capability resolves which backend and base path each scope maps to:

- `user`  → `user_backend` (default `LocalBackend(root_dir=expanduser("~/.pydantic-deep/memory"))`), base `"{agent_name}"`.
- `project` → `ctx.deps.backend`, base `".pydantic-deep/memory/{agent_name}"`.

`user_backend` is an injectable field on the capability (default factory builds the
`LocalBackend`); tests inject a `LocalBackend` rooted at a tmp dir or a `StateBackend`.

## Data Model

`MemoryEntry` (dataclass) — identical field set to cheetahclaws:

```python
name: str
description: str
type: str          # "user" | "feedback" | "project" | "reference"
content: str
file_path: str = ""        # backend path to THIS memory's own .md file (see below)
created: str = ""          # ISO "2026-06-04"
scope: str = "user"        # "user" | "project"
confidence: float = 1.0    # 0.0–1.0
source: str = "user"       # "user" | "model" | "tool" | "consolidator" (see below)
last_used_at: str = ""     # ISO date, touched on search hits (cleanup signal, not ranked)
conflict_group: str = ""
```

**`file_path`** is the backend path of *this memory's own* `.md` file — it is **not**
source-code context attached to the memory. It is empty on a freshly constructed entry,
populated by `save_memory` (after writing) and by `load_entries` (when scanning a scope),
and used to build the index links and to target `touch_last_used`.

**`source`** records provenance and takes exactly four values — there is no `"system"`:
- `user` (default) — explicit user statement.
- `model` — inferred by the agent.
- `tool` — added programmatically / extracted from tool output (covers any
  non-interactive origin).
- `consolidator` — set internally by `consolidate_session`; not selectable via the
  `MemorySave` tool (its enum exposes only `user`/`model`/`tool`).

Frontmatter format and the `_format_entry_md` field-omission rules (only emit
confidence/source/last_used_at/conflict_group when non-default) are ported verbatim.

**`conflict_group` is advisory metadata only.** It is an optional free-text tag that links
related memories (e.g. `testing_policy`). It is surfaced in `MemoryList`/`MemorySearch`
output (`grp:<group>`) so the human/agent can notice related entries and reconcile them
manually. It does **not** trigger automatic conflict detection and does **not** cause group
members to be co-surfaced during search. `check_conflict` operates purely on the slug
(same filename, differing body).

## Behavior

### Save (`MemorySave`)
Build `MemoryEntry` → `check_conflict` (read existing slug, diff body ignoring whitespace)
→ write `.md` (frontmatter + body), checking `WriteResult.error` → `_rewrite_index` for
that `(agent, scope)` → return a status string, appending a conflict-replacement note when
applicable.

### Search (`MemorySearch`)
Keyword substring filter across both scopes (name + description + content) →
optionally re-rank via internal `Agent` (`use_ai=true`) → sort by
`confidence × exp(-age_days / 30)` where `age_days` derives from the **`created`**
frontmatter date only (never `last_used_at`) → `touch_last_used` on the **final returned
set** (already capped at `max_results`, default 5) → format with a staleness caveat for
entries older than `staleness_days` (default 7).

- **Scope is always shown.** Each result line includes a `[<type>/<scope>]` tag so the
  caller knows whether a memory came from user or project scope. The `scope` field is
  stamped on each `MemoryEntry` at load time based on which backend/base it was read from,
  so there is no ambiguity even though the index filename (`MEMORY.md`) is identical in
  both scopes.
- **AI fallback is silent and never raises.** When `use_ai=true` and the internal `Agent`
  call errors (or returns unusable output), search falls back to the keyword-ranked top-N
  results. The caller always receives keyword results in that case — never an empty list
  (unless there were no keyword matches) and never an exception.
- **`last_used_at` does not affect ranking.** It is updated for the returned set purely as
  a utility/cleanup signal (surfacing memories that are never retrieved). Because it is
  decoupled from the recency score, touching every returned entry cannot inflate
  freshness.

### Delete (`MemoryDelete`)
Remove the slug file in the scope and rebuild that index. No error if absent.

### List (`MemoryList`)
Enumerate entries for the requested scope(s) with type/scope/confidence/source/group tags.
Every line carries an explicit `[<type>|<scope>]` tag; `conflict_group` (when set) appears
as `grp:<group>`, and `last_used_at` may be shown to flag unused memories.

### Prompt injection (`get_instructions`)
Inject `MEMORY_SYSTEM_PROMPT` once, then both scope indexes (user + project) for this
agent, each truncated via `truncate_index_content`. Returns `None`/empty when no memories
exist. Implemented as a `dynamic=True` `InstructionPart`, matching the existing toolset.

**What gets injected vs. what does not.** Only the **index** (`MEMORY.md`, one line per
memory: `- [name](file.md) — description`) is injected into the system prompt. Full memory
**bodies are never injected** — they are returned (with a ~200-char preview) by
`MemorySearch` and read in full on demand. Consequently:

- The 200-line / 25 KB limits apply to the **injected index content**, not to bodies. A
  large memory body is fine; it does not bloat the prompt.
- A single index *entry* is one line (~150 chars) and cannot itself exceed the byte limit.
  The limit only fires when there are **too many memories**; truncation then cuts at the
  last newline before the cap and appends a warning naming which limit fired.

### Consolidation (`consolidate_session`, app-triggered)
Standalone async function. Skips sessions shorter than the minimum message count. Builds a
condensed transcript from recent messages, calls an internal `Agent(model, output_type=...)`
returning a list of candidate memories, saves at most 3 with `source="consolidator"` and
default confidence 0.8, skipping any that would overwrite an existing memory of **equal or
higher** confidence (tie-break: `existing_confidence >= new_confidence` → existing wins,
new skipped). Returns the list of saved names. Never raises into the caller (defensive).

## Backward Compatibility

- `AgentMemoryToolset` and `MemoryCapability` keep working unchanged, decorated with
  `@deprecated("Use ScopedMemoryToolset / ScopedMemoryCapability instead.")`.
- New symbols exported from `pydantic_deep/__init__.py`:
  `ScopedMemoryToolset`, `ScopedMemoryCapability`, `MemoryEntry`, `consolidate_session`,
  and the prompt/type constants.
- `create_deep_agent` gains an opt-in path to the scoped capability (exact wiring decided
  in the implementation plan); the default remains the existing capability for one release
  to avoid behavior changes.
- No migration of legacy single-blob files.

## Testing Strategy

- **Storage:** `StateBackend` (and a tmp-rooted `LocalBackend` for the user scope) — cover
  slugify, frontmatter round-trip, save/overwrite, delete, load, index rebuild + content,
  `WriteResult.error` handling, relative-vs-returned-path read-back.
- **Conflict:** identical-content (no conflict) vs differing-content (conflict dict).
- **Truncation:** line-only, byte-only, and both-limits cases, including warning text.
- **Ranking/staleness:** age-from-`created` math, recency decay ordering, freshness text at
  the configurable threshold (`age ≤ staleness_days` → empty), `touch_last_used` idempotence,
  and confirmation that `last_used_at` does **not** alter ranking order.
- **Search:** keyword path; AI path via `TestModel` returning fixed indices; fallback on
  error.
- **Consolidation:** `TestModel` returning JSON memories; ≤3 cap; confidence-skip;
  short-session skip; malformed-output skip.
- **Capability/toolset:** `get_instructions` with/without memories; tool dispatch; scope
  routing to the correct backend.
- **Deprecation:** old classes still importable and functional; emit `DeprecationWarning`.

Use `# pragma: no cover` only for genuinely unreachable platform branches.

## Risks / Open Items

- **Default user backend at import/instantiation time** must not create `~/.pydantic-deep`
  as a side effect of merely importing the module. `LocalBackend.__init__` calls
  `mkdir(parents=True)` on its root, so the default user backend is built lazily (on first
  use / in `__post_init__` of the capability), and tests always inject their own — the
  real home dir is never touched by the suite.
- **`StateBackend` key normalization** (relative → leading-slash) means the store must
  always read back via the `path` returned by `glob_info`/`ls_info`, never reconstruct it.
- **Message format for consolidation:** the transcript builder must accept pydantic-ai
  `ModelMessage` history; the exact extraction shape is pinned in the plan.
```