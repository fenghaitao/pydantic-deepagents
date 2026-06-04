# Scoped, Typed Agent Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the cheetahclaws file-per-memory model (4 types, frontmatter metadata, conflict detection, recency ranking, staleness, keyword+AI search, app-triggered consolidation) onto pydantic-deep's `BackendProtocol`/capability architecture.

**Architecture:** A new `pydantic_deep/toolsets/scoped_memory/` package with pure-ish backend-parameterized storage (`store.py`), date-based freshness (`scan.py`), prompt/search context (`context.py`), an internal-Agent consolidator (`consolidator.py`), a `ScopedMemoryToolset` (4 tools), and a `ScopedMemoryCapability`. User scope → a dedicated `LocalBackend` at `~/.pydantic-deep/memory`; project scope → the run's backend at `.pydantic-deep/memory`. The existing single-blob `AgentMemoryToolset`/`MemoryCapability` are kept and `@deprecated`.

**Tech Stack:** Python 3.13, pydantic-ai (`Agent`, `FunctionToolset`, `AbstractCapability`, `TestModel`/`FunctionModel`), `pydantic_ai_backends` (`StateBackend`/`LocalBackend`, `glob_info`/`read_bytes`/`write`), pytest (`asyncio_mode=auto`), Pyright + MyPy strict, 100% coverage.

**Spec:** `docs/superpowers/specs/2026-06-04-scoped-typed-agent-memory-design.md`

---

## Conventions (read before starting)

- **Backend reads:** use `read_backend_bytes(backend, path)` from `pydantic_deep._backend` (handles API drift). Decode `errors="replace"`.
- **Backend writes:** `result = backend.write(path, data_bytes_or_str)`; **always check `result.error`** and raise on failure inside the store.
- **Listing:** `backend.glob_info("*.md", base_dir)` → `list[FileInfo]`; read each via its returned `["path"]` (never reconstruct — `StateBackend` normalizes to leading-slash keys).
- **Test helper pattern** (mirror `tests/test_memory.py`):
  ```python
  from pydantic_ai.models.test import TestModel
  from pydantic_ai.tools import RunContext
  from pydantic_ai.usage import RunUsage
  from pydantic_ai_backends import StateBackend
  from pydantic_deep.deps import DeepAgentDeps

  def _make_ctx(backend=None):
      b = backend or StateBackend()
      return RunContext(deps=DeepAgentDeps(backend=b), model=TestModel(), usage=RunUsage())
  ```
- **Invoke a toolset tool in tests:** `await toolset.tools["MemorySave"].function(ctx, ...)`.
- **Commit cadence:** one commit per task (after its tests pass). Branch `feat/scoped-memory` is already checked out.
- **Coverage:** run `uv run pytest tests/test_scoped_memory.py -v` per task; `make test` (full suite + coverage) before the final task. Use `# pragma: no cover` only for genuinely unreachable branches.

## File Structure

| File | Responsibility |
|------|----------------|
| `pydantic_deep/toolsets/scoped_memory/__init__.py` | Package exports |
| `pydantic_deep/toolsets/scoped_memory/types.py` | `MemoryEntry`, `MEMORY_TYPES`, prompt/guidance constants |
| `pydantic_deep/toolsets/scoped_memory/store.py` | Backend CRUD + frontmatter + index + conflict + touch |
| `pydantic_deep/toolsets/scoped_memory/scan.py` | Date-based age/freshness helpers |
| `pydantic_deep/toolsets/scoped_memory/context.py` | Index injection, keyword+AI relevance, truncation |
| `pydantic_deep/toolsets/scoped_memory/consolidator.py` | `consolidate_session` (internal Agent) |
| `pydantic_deep/toolsets/scoped_memory/toolset.py` | `ScopedMemoryToolset` (4 tools + `get_instructions`) |
| `pydantic_deep/capabilities/scoped_memory.py` | `ScopedMemoryCapability` |
| `pydantic_deep/toolsets/memory.py` | Add `@deprecated` to existing classes (modify) |
| `pydantic_deep/capabilities/memory.py` | Add `@deprecated` to `MemoryCapability` (modify) |
| `pydantic_deep/__init__.py` | Export new public symbols (modify) |
| `tests/test_scoped_memory.py` | All tests for the new package |

---

## Task 1: Package scaffold + types

**Files:**
- Create: `pydantic_deep/toolsets/scoped_memory/__init__.py`
- Create: `pydantic_deep/toolsets/scoped_memory/types.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoped_memory.py
"""Tests for the scoped, typed agent memory package."""
from pydantic_deep.toolsets.scoped_memory.types import (
    MEMORY_TYPES,
    MEMORY_SYSTEM_PROMPT,
    MemoryEntry,
)


class TestMemoryEntry:
    def test_defaults(self):
        e = MemoryEntry(name="n", description="d", type="user", content="c")
        assert e.file_path == ""
        assert e.scope == "user"
        assert e.confidence == 1.0
        assert e.source == "user"
        assert e.last_used_at == ""
        assert e.conflict_group == ""

    def test_types_and_prompt(self):
        assert MEMORY_TYPES == ["user", "feedback", "project", "reference"]
        assert "Memory system" in MEMORY_SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: pydantic_deep.toolsets.scoped_memory`

- [ ] **Step 3: Create the types module**

```python
# pydantic_deep/toolsets/scoped_memory/types.py
"""Memory type taxonomy, data model, and system-prompt guidance."""
from __future__ import annotations

from dataclasses import dataclass

MEMORY_TYPES = ["user", "feedback", "project", "reference"]

MEMORY_TYPE_DESCRIPTIONS: dict[str, str] = {
    "user": (
        "Information about the user's role, goals, responsibilities, and knowledge. "
        "Helps tailor future behavior to the user's preferences."
    ),
    "feedback": (
        "Guidance the user has given about how to approach work — both what to avoid "
        "and what to keep doing. Lead with the rule, then **Why:** and **How to apply:**."
    ),
    "project": (
        "Ongoing work, goals, bugs, or incidents not derivable from code or git history. "
        "Lead with the fact/decision, then **Why:** and **How to apply:**. "
        "Always convert relative dates to absolute dates."
    ),
    "reference": (
        "Pointers to external systems (issue trackers, dashboards, Slack channels, docs)."
    ),
}

WHAT_NOT_TO_SAVE = """\
## What NOT to save in memory
- Code patterns, conventions, architecture, file paths, or project structure — derivable from the codebase.
- Git history, recent changes, who-changed-what — use `git log` / `git blame`.
- Debugging solutions or fix recipes — the fix is in the code; the commit message has context.
- Anything already documented in CLAUDE.md files.
- Ephemeral task details: in-progress work, temporary state, current conversation context.

These exclusions apply even when explicitly asked. If asked to save a PR list or activity summary,
ask what was *surprising* or *non-obvious* — that is the part worth keeping."""

MEMORY_FORMAT_EXAMPLE = """\
```markdown
---
name: {{memory name}}
description: {{one-line description — used to decide relevance, so be specific}}
type: {{user | feedback | project | reference}}
---

{{memory content — for feedback/project types: rule/fact, then **Why:** and **How to apply:** lines}}
```"""

MEMORY_SYSTEM_PROMPT = """\
## Memory system

You have a persistent, file-based memory system. Memories are stored as markdown files with
YAML frontmatter. Build this up over time so future conversations have context about the user,
their preferences, and the work you're doing together.

**Types** (save only what cannot be derived from the codebase):
- **user** — role, goals, knowledge, preferences
- **feedback** — guidance on how to work (corrections AND confirmations of non-obvious approaches)
- **project** — ongoing work, decisions, deadlines not in git history
- **reference** — pointers to external systems (Linear, Grafana, Slack, etc.)

**When to save**: If the user corrects you, confirms an approach, or shares context that should
persist beyond this conversation. For feedback: save corrections AND quiet confirmations.

**Body structure for feedback/project**: Lead with the rule/fact, then:
  **Why:** (reason given) | **How to apply:** (when this guidance kicks in)

**Format**:
{format_example}

**What NOT to save**: code patterns, architecture, git history, debugging fixes,
anything already in CLAUDE.md, or ephemeral task state.

**Before recommending from memory**: A memory naming a file, function, or flag may be stale.
Verify it still exists before acting on it. For current state, prefer `git log` or reading code.
""".format(format_example=MEMORY_FORMAT_EXAMPLE)


@dataclass
class MemoryEntry:
    """A single memory entry. ``file_path`` is this memory's OWN .md path (set on
    save/load), not source context. ``last_used_at`` is a cleanup signal, not ranked."""

    name: str
    description: str
    type: str
    content: str
    file_path: str = ""
    created: str = ""
    scope: str = "user"
    confidence: float = 1.0
    source: str = "user"
    last_used_at: str = ""
    conflict_group: str = ""
```

```python
# pydantic_deep/toolsets/scoped_memory/__init__.py
"""Scoped, typed agent memory on BackendProtocol."""
from __future__ import annotations

from .types import (
    MEMORY_FORMAT_EXAMPLE,
    MEMORY_SYSTEM_PROMPT,
    MEMORY_TYPE_DESCRIPTIONS,
    MEMORY_TYPES,
    WHAT_NOT_TO_SAVE,
    MemoryEntry,
)

__all__ = [
    "MemoryEntry",
    "MEMORY_TYPES",
    "MEMORY_TYPE_DESCRIPTIONS",
    "MEMORY_SYSTEM_PROMPT",
    "WHAT_NOT_TO_SAVE",
    "MEMORY_FORMAT_EXAMPLE",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/__init__.py pydantic_deep/toolsets/scoped_memory/types.py tests/test_scoped_memory.py
git commit -m "feat(memory): scoped_memory package scaffold + MemoryEntry/types"
```

---

## Task 2: Frontmatter + slug helpers (`store.py` part 1)

**Files:**
- Create: `pydantic_deep/toolsets/scoped_memory/store.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
from pydantic_deep.toolsets.scoped_memory import store
from pydantic_deep.toolsets.scoped_memory.types import MemoryEntry


class TestStoreHelpers:
    def test_slugify(self):
        assert store._slugify("User Prefers Tests") == "user_prefers_tests"
        assert store._slugify("Don't Mock DB!") == "dont_mock_db"
        assert store._slugify("x" * 100) == "x" * 60

    def test_parse_frontmatter(self):
        text = "---\nname: a\ntype: user\n---\nbody here"
        meta, body = store.parse_frontmatter(text)
        assert meta == {"name": "a", "type": "user"}
        assert body == "body here"

    def test_parse_frontmatter_no_frontmatter(self):
        meta, body = store.parse_frontmatter("just text")
        assert meta == {}
        assert body == "just text"

    def test_parse_frontmatter_unterminated(self):
        meta, body = store.parse_frontmatter("---\nname: a\nno close")
        assert meta == {}
        assert body == "---\nname: a\nno close"

    def test_format_entry_md_minimal(self):
        e = MemoryEntry(name="n", description="d", type="user", content="body", created="2026-06-04")
        out = store._format_entry_md(e)
        assert out.startswith("---\nname: n\ndescription: d\ntype: user\ncreated: 2026-06-04\n---\n")
        assert "confidence:" not in out  # default 1.0 omitted
        assert out.endswith("body\n")

    def test_format_entry_md_optional_fields(self):
        e = MemoryEntry(name="n", description="d", type="user", content="b",
                        created="2026-06-04", confidence=0.8, source="model",
                        last_used_at="2026-06-04", conflict_group="g")
        out = store._format_entry_md(e)
        assert "confidence: 0.80" in out
        assert "source: model" in out
        assert "last_used_at: 2026-06-04" in out
        assert "conflict_group: g" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestStoreHelpers -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError`

- [ ] **Step 3: Create `store.py` with helpers**

```python
# pydantic_deep/toolsets/scoped_memory/store.py
"""Backend-backed file-per-memory storage.

All operations take an explicit ``backend`` and ``base_dir`` so the same code
serves both the user scope (a dedicated LocalBackend) and the project scope
(the run's backend). ``base_dir`` is the directory that holds the per-memory
``<slug>.md`` files and the auto-built ``MEMORY.md`` index.
"""
from __future__ import annotations

import re

from pydantic_ai_backends import BackendProtocol

from pydantic_deep._backend import read_backend_bytes

from .types import MemoryEntry

INDEX_FILENAME = "MEMORY.md"


def _slugify(name: str) -> str:
    """Filesystem-safe slug (max 60 chars)."""
    s = name.lower().strip().replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s[:60]


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse ``---\\nkey: value\\n---\\nbody``. Returns ``({}, text)`` if absent/malformed."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta, parts[2].strip()


def _format_entry_md(entry: MemoryEntry) -> str:
    """Render a MemoryEntry as markdown with frontmatter (omitting default-valued fields)."""
    lines = [
        "---",
        f"name: {entry.name}",
        f"description: {entry.description}",
        f"type: {entry.type}",
        f"created: {entry.created}",
    ]
    if entry.confidence != 1.0:
        lines.append(f"confidence: {entry.confidence:.2f}")
    if entry.source and entry.source != "user":
        lines.append(f"source: {entry.source}")
    if entry.last_used_at:
        lines.append(f"last_used_at: {entry.last_used_at}")
    if entry.conflict_group:
        lines.append(f"conflict_group: {entry.conflict_group}")
    lines.append("---")
    lines.append(entry.content)
    return "\n".join(lines) + "\n"


def _file_path(base_dir: str, slug: str) -> str:
    return f"{base_dir.rstrip('/')}/{slug}.md"


def _index_path(base_dir: str) -> str:
    return f"{base_dir.rstrip('/')}/{INDEX_FILENAME}"


def _write_or_raise(backend: BackendProtocol, path: str, content: str) -> None:
    result = backend.write(path, content.encode("utf-8"))
    if getattr(result, "error", None):
        raise OSError(f"memory write failed for {path}: {result.error}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestStoreHelpers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/store.py tests/test_scoped_memory.py
git commit -m "feat(memory): frontmatter parse/format + slug helpers"
```

---

## Task 3: Save / load / delete / index (`store.py` part 2)

**Files:**
- Modify: `pydantic_deep/toolsets/scoped_memory/store.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
class TestStoreCRUD:
    def _entry(self, name="user_prefers_tests"):
        return MemoryEntry(name=name, description="prefers pytest", type="user",
                           content="Uses pytest.", created="2026-06-04")

    def test_save_then_load(self):
        b = StateBackend()
        store.save_memory(b, "main", self._entry(), scope="user")
        entries = store.load_entries(b, "main", scope="user")
        assert len(entries) == 1
        e = entries[0]
        assert e.name == "user_prefers_tests"
        assert e.scope == "user"
        assert e.content == "Uses pytest."
        assert e.file_path.endswith("user_prefers_tests.md")

    def test_index_rebuilt_on_save(self):
        b = StateBackend()
        store.save_memory(b, "main", self._entry(), scope="user")
        idx = store.get_index_content(b, "main")
        assert idx == "- [user_prefers_tests](user_prefers_tests.md) — prefers pytest"

    def test_index_excluded_from_entries(self):
        b = StateBackend()
        store.save_memory(b, "main", self._entry(), scope="user")
        names = [e.name for e in store.load_entries(b, "main", scope="user")]
        assert "MEMORY" not in names and INDEX_STEM not in names

    def test_delete(self):
        b = StateBackend()
        store.save_memory(b, "main", self._entry(), scope="user")
        store.delete_memory(b, "main", "user_prefers_tests")
        assert store.load_entries(b, "main", scope="user") == []
        assert store.get_index_content(b, "main") == ""

    def test_delete_missing_is_noop(self):
        b = StateBackend()
        store.delete_memory(b, "main", "nope")  # no raise
        assert store.get_index_content(b, "main") == ""

    def test_load_empty_dir(self):
        assert store.load_entries(StateBackend(), "main", scope="user") == []
```

Add at the top of the test file's imports section:
```python
from pydantic_deep.toolsets.scoped_memory.store import INDEX_FILENAME as _IDX
INDEX_STEM = _IDX.removesuffix(".md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestStoreCRUD -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'save_memory'`

- [ ] **Step 3: Add CRUD + index functions to `store.py`**

```python
# append to pydantic_deep/toolsets/scoped_memory/store.py

def _list_md_paths(backend: BackendProtocol, base_dir: str) -> list[str]:
    """Return backend paths of every .md file in base_dir except the index."""
    try:
        infos = backend.glob_info("*.md", base_dir)
    except Exception:
        return []
    paths: list[str] = []
    for info in infos:
        path = info["path"] if isinstance(info, dict) else getattr(info, "path", "")
        if path and not path.endswith(f"/{INDEX_FILENAME}") and path != INDEX_FILENAME:
            paths.append(path)
    return paths


def load_entries(backend: BackendProtocol, base_dir: str, scope: str = "user") -> list[MemoryEntry]:
    """Load all memory entries from base_dir, stamping the given scope. Sorted by name."""
    entries: list[MemoryEntry] = []
    for path in _list_md_paths(backend, base_dir):
        raw = read_backend_bytes(backend, path)
        if not raw:
            continue
        meta, body = parse_frontmatter(raw.decode("utf-8", errors="replace"))
        stem = path.rsplit("/", 1)[-1].removesuffix(".md")
        try:
            confidence = float(meta.get("confidence", 1.0))
        except ValueError:
            confidence = 1.0
        entries.append(MemoryEntry(
            name=meta.get("name", stem),
            description=meta.get("description", ""),
            type=meta.get("type", "user"),
            content=body,
            file_path=path,
            created=meta.get("created", ""),
            scope=scope,
            confidence=confidence,
            source=meta.get("source", "user"),
            last_used_at=meta.get("last_used_at", ""),
            conflict_group=meta.get("conflict_group", ""),
        ))
    entries.sort(key=lambda e: e.name)
    return entries


def _rewrite_index(backend: BackendProtocol, base_dir: str, scope: str) -> None:
    entries = load_entries(backend, base_dir, scope=scope)
    lines = [
        f"- [{e.name}]({e.file_path.rsplit('/', 1)[-1]}) — {e.description}"
        for e in entries
    ]
    body = "\n".join(lines) + ("\n" if lines else "")
    _write_or_raise(backend, _index_path(base_dir), body)


def save_memory(backend: BackendProtocol, base_dir: str, entry: MemoryEntry, scope: str = "user") -> None:
    """Write/overwrite a memory file (by slug) and rebuild the scope index."""
    slug = _slugify(entry.name)
    path = _file_path(base_dir, slug)
    _write_or_raise(backend, path, _format_entry_md(entry))
    entry.file_path = path
    entry.scope = scope
    _rewrite_index(backend, base_dir, scope)


def delete_memory(backend: BackendProtocol, base_dir: str, name: str, scope: str = "user") -> None:
    """Delete the memory file matching name (no error if absent) and rebuild the index."""
    slug = _slugify(name)
    path = _file_path(base_dir, slug)
    if backend.exists(path):
        delete = getattr(backend, "delete", None)
        if callable(delete):
            delete(path)
        else:  # pragma: no cover - all shipped backends implement delete
            backend.write(path, b"")
    _rewrite_index(backend, base_dir, scope)


def get_index_content(backend: BackendProtocol, base_dir: str) -> str:
    """Raw MEMORY.md content for base_dir, or '' if absent."""
    path = _index_path(base_dir)
    if not backend.exists(path):
        return ""
    return read_backend_bytes(backend, path).decode("utf-8", errors="replace").strip()
```

> **Note:** verify the backend `delete` method name during Step 4. If `BackendProtocol` exposes deletion under a different name (e.g. `rm`/`remove`), adjust `delete_memory` accordingly and keep the `# pragma: no cover` fallback.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestStoreCRUD -v`
Expected: PASS. If `delete` is missing on `StateBackend`, inspect with `uv run python -c "from pydantic_ai_backends import StateBackend; print([m for m in dir(StateBackend) if 'el' in m or 'rm' in m])"` and fix the method name.

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/store.py tests/test_scoped_memory.py
git commit -m "feat(memory): backend save/load/delete + auto index rebuild"
```

---

## Task 4: Conflict detection + last-used touch (`store.py` part 3)

**Files:**
- Modify: `pydantic_deep/toolsets/scoped_memory/store.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
class TestConflictAndTouch:
    def _save(self, b, content, confidence=1.0, source="user"):
        e = MemoryEntry(name="m", description="d", type="user", content=content,
                        created="2026-06-04", confidence=confidence, source=source)
        store.save_memory(b, "main", e, scope="user")
        return e

    def test_no_conflict_when_absent(self):
        b = StateBackend()
        e = MemoryEntry(name="m", description="d", type="user", content="x")
        assert store.check_conflict(b, "main", e) is None

    def test_no_conflict_identical_body(self):
        b = StateBackend()
        self._save(b, "same body")
        e = MemoryEntry(name="m", description="d", type="user", content="same body")
        assert store.check_conflict(b, "main", e) is None

    def test_conflict_differing_body(self):
        b = StateBackend()
        self._save(b, "old body", confidence=0.9, source="model")
        e = MemoryEntry(name="m", description="d", type="user", content="new body")
        c = store.check_conflict(b, "main", e)
        assert c is not None
        assert c["existing_content"] == "old body"
        assert c["existing_confidence"] == 0.9
        assert c["existing_source"] == "model"
        assert c["existing_created"] == "2026-06-04"

    def test_touch_last_used_sets_date(self):
        b = StateBackend()
        e = self._save(b, "body")
        store.touch_last_used(b, e.file_path, today="2026-06-10")
        meta, _ = store.parse_frontmatter(b.read_bytes(e.file_path).decode())
        assert meta["last_used_at"] == "2026-06-10"

    def test_touch_last_used_idempotent(self):
        b = StateBackend()
        e = self._save(b, "body")
        store.touch_last_used(b, e.file_path, today="2026-06-10")
        first = b.read_bytes(e.file_path)
        store.touch_last_used(b, e.file_path, today="2026-06-10")  # no rewrite
        assert b.read_bytes(e.file_path) == first

    def test_touch_last_used_missing_file_is_noop(self):
        store.touch_last_used(StateBackend(), "main/nope.md", today="2026-06-10")  # no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestConflictAndTouch -v`
Expected: FAIL — `AttributeError: ... 'check_conflict'`

- [ ] **Step 3: Add conflict + touch functions to `store.py`**

```python
# append to pydantic_deep/toolsets/scoped_memory/store.py
from datetime import date as _date  # noqa: E402  (grouped with other imports at top in final form)


def check_conflict(backend: BackendProtocol, base_dir: str, entry: MemoryEntry) -> dict | None:
    """Return existing-memory fields if a same-slug memory exists with a DIFFERENT body,
    else None (no file, or identical body)."""
    path = _file_path(base_dir, _slugify(entry.name))
    if not backend.exists(path):
        return None
    meta, existing = parse_frontmatter(read_backend_bytes(backend, path).decode("utf-8", errors="replace"))
    if existing.strip() == entry.content.strip():
        return None
    try:
        existing_conf = float(meta.get("confidence", 1.0))
    except ValueError:
        existing_conf = 1.0
    return {
        "existing_content": existing.strip(),
        "existing_confidence": existing_conf,
        "existing_created": meta.get("created", ""),
        "existing_source": meta.get("source", "user"),
    }


def touch_last_used(backend: BackendProtocol, file_path: str, today: str | None = None) -> None:
    """Set last_used_at on a memory file to today's date. Cleanup signal only — never
    affects ranking. Silent if the file is missing or already current."""
    if not file_path or not backend.exists(file_path):
        return
    stamp = today or _date.today().isoformat()
    meta, body = parse_frontmatter(read_backend_bytes(backend, file_path).decode("utf-8", errors="replace"))
    if meta.get("last_used_at") == stamp:
        return
    meta["last_used_at"] = stamp
    fm = ["---"]
    for k in ("name", "description", "type", "created", "confidence",
              "source", "last_used_at", "conflict_group"):
        v = meta.get(k)
        if v is not None and str(v):
            fm.append(f"{k}: {v}")
    fm.append("---")
    _write_or_raise(backend, file_path, "\n".join(fm) + "\n" + body + "\n")
```

Move `from datetime import date as _date` to the top import block when finalizing (keep imports grouped; the inline note is just for clarity).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestConflictAndTouch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/store.py tests/test_scoped_memory.py
git commit -m "feat(memory): slug-based conflict detection + last_used touch"
```

---

## Task 5: Date-based freshness (`scan.py`)

**Files:**
- Create: `pydantic_deep/toolsets/scoped_memory/scan.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
from pydantic_deep.toolsets.scoped_memory import scan


class TestScan:
    def test_age_days(self):
        assert scan.memory_age_days("2026-06-01", today="2026-06-04") == 3
        assert scan.memory_age_days("", today="2026-06-04") == 0       # missing → fresh
        assert scan.memory_age_days("not-a-date", today="2026-06-04") == 0
        assert scan.memory_age_days("2026-06-10", today="2026-06-04") == 0  # future clamped

    def test_age_str(self):
        assert scan.memory_age_str(0) == "today"
        assert scan.memory_age_str(1) == "yesterday"
        assert scan.memory_age_str(5) == "5 days ago"

    def test_freshness_text_threshold(self):
        assert scan.memory_freshness_text(7, staleness_days=7) == ""      # at threshold → fresh
        txt = scan.memory_freshness_text(8, staleness_days=7)
        assert "8 days old" in txt and "Verify against current code" in txt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestScan -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create `scan.py`**

```python
# pydantic_deep/toolsets/scoped_memory/scan.py
"""Date-based memory age + staleness helpers.

Age is computed from the immutable ``created`` frontmatter date (never mtime,
never last_used_at). The staleness warning is a CODE-STATE caveat, gated on a
configurable threshold.
"""
from __future__ import annotations

from datetime import date


def memory_age_days(created: str, today: str | None = None) -> int:
    """Whole days between ``created`` and ``today`` (both ISO). 0 if missing/invalid/future."""
    if not created:
        return 0
    try:
        c = date.fromisoformat(created)
        t = date.fromisoformat(today) if today else date.today()
    except ValueError:
        return 0
    return max(0, (t - c).days)


def memory_age_str(days: int) -> str:
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def memory_freshness_text(age_days: int, staleness_days: int = 7) -> str:
    """Staleness caveat when age_days > staleness_days; '' otherwise."""
    if age_days <= staleness_days:
        return ""
    return (
        f"This memory is {age_days} days old. "
        "Memories are point-in-time observations, not live state — "
        "claims about code behavior or file:line citations may be outdated. "
        "Verify against current code before asserting as fact."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestScan -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/scan.py tests/test_scoped_memory.py
git commit -m "feat(memory): created-date age + configurable staleness text"
```

---

## Task 6: Index truncation (`context.py` part 1)

**Files:**
- Create: `pydantic_deep/toolsets/scoped_memory/context.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
from pydantic_deep.toolsets.scoped_memory import context


class TestTruncation:
    def test_no_truncation(self):
        raw = "- [a](a.md) — x\n- [b](b.md) — y"
        assert context.truncate_index_content(raw) == raw

    def test_line_truncation(self):
        raw = "\n".join(f"- [m{i}](m{i}.md) — x" for i in range(250))
        out = context.truncate_index_content(raw, max_lines=200, max_bytes=10**9)
        assert out.count("\n- [") <= 200
        assert "WARNING" in out and "200" in out

    def test_byte_truncation(self):
        raw = "\n".join(f"- [m{i}](m{i}.md) — {'x'*100}" for i in range(50))
        out = context.truncate_index_content(raw, max_lines=10**6, max_bytes=500)
        assert len(out.encode()) < len(raw.encode())
        assert "WARNING" in out and "bytes" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestTruncation -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create `context.py` with truncation**

```python
# pydantic_deep/toolsets/scoped_memory/context.py
"""System-prompt index injection, keyword+AI relevance, and index truncation."""
from __future__ import annotations

from .store import INDEX_FILENAME

MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25_000


def truncate_index_content(
    raw: str, max_lines: int = MAX_INDEX_LINES, max_bytes: int = MAX_INDEX_BYTES
) -> str:
    """Truncate index content to line AND byte limits, appending a warning naming which
    limit fired. Line-truncates first, then byte-truncates at the last newline."""
    trimmed = raw.strip()
    content_lines = trimmed.split("\n")
    line_count = len(content_lines)
    byte_count = len(trimmed.encode())

    was_line = line_count > max_lines
    was_byte = byte_count > max_bytes
    if not was_line and not was_byte:
        return trimmed

    truncated = "\n".join(content_lines[:max_lines]) if was_line else trimmed
    if len(truncated.encode()) > max_bytes:
        raw_bytes = truncated.encode()
        cut = raw_bytes[:max_bytes].rfind(b"\n")
        truncated = raw_bytes[: cut if cut > 0 else max_bytes].decode(errors="replace")

    if was_byte and not was_line:
        reason = f"{byte_count:,} bytes (limit: {max_bytes:,}) — index entries are too long"
    elif was_line and not was_byte:
        reason = f"{line_count} lines (limit: {max_lines})"
    else:
        reason = f"{line_count} lines and {byte_count:,} bytes"

    return truncated + (
        f"\n\n> WARNING: {INDEX_FILENAME} is {reason}. "
        "Only part of it was loaded. Keep index entries to one line under ~150 chars."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestTruncation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/context.py tests/test_scoped_memory.py
git commit -m "feat(memory): index truncation with line/byte limits"
```

---

## Task 7: Keyword search + ranking (`context.py` part 2)

**Files:**
- Modify: `pydantic_deep/toolsets/scoped_memory/context.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
import math


class TestKeywordSearchAndRank:
    def _e(self, name, content, created="2026-06-04", confidence=1.0):
        return MemoryEntry(name=name, description=name, type="user",
                           content=content, created=created, confidence=confidence)

    def test_keyword_filter(self):
        entries = [self._e("a", "about testing"), self._e("b", "about deploys")]
        hits = context.keyword_filter(entries, "testing")
        assert [e.name for e in hits] == ["a"]

    def test_keyword_filter_case_insensitive_multi_field(self):
        entries = [self._e("Deploy", "x")]
        assert len(context.keyword_filter(entries, "deploy")) == 1

    def test_rank_by_confidence_and_recency(self):
        fresh_hi = self._e("fresh_hi", "q", created="2026-06-04", confidence=1.0)
        old_hi = self._e("old_hi", "q", created="2026-04-05", confidence=1.0)  # ~60d
        ranked = context.rank_entries([old_hi, fresh_hi], today="2026-06-04")
        assert [e.name for e in ranked] == ["fresh_hi", "old_hi"]

    def test_rank_score_formula(self):
        e = self._e("x", "q", created="2026-05-28", confidence=0.5)  # 7 days
        score = context.rank_score(e, today="2026-06-04")
        assert math.isclose(score, 0.5 * math.exp(-7 / 30), rel_tol=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestKeywordSearchAndRank -v`
Expected: FAIL — `AttributeError: ... 'keyword_filter'`

- [ ] **Step 3: Add search + ranking to `context.py`**

```python
# append to pydantic_deep/toolsets/scoped_memory/context.py
import math  # add to top import block when finalizing

from .scan import memory_age_days
from .types import MemoryEntry


def keyword_filter(entries: list[MemoryEntry], query: str) -> list[MemoryEntry]:
    """Case-insensitive substring match over name + description + content."""
    q = query.lower()
    return [
        e for e in entries
        if q in f"{e.name} {e.description} {e.content}".lower()
    ]


def rank_score(entry: MemoryEntry, today: str | None = None) -> float:
    """confidence × exp(-age_days / 30), age from `created` only."""
    age = memory_age_days(entry.created, today=today)
    return entry.confidence * math.exp(-age / 30)


def rank_entries(entries: list[MemoryEntry], today: str | None = None) -> list[MemoryEntry]:
    """Sort by rank_score descending (stable)."""
    return sorted(entries, key=lambda e: rank_score(e, today=today), reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestKeywordSearchAndRank -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/context.py tests/test_scoped_memory.py
git commit -m "feat(memory): keyword filter + confidence×recency ranking"
```

---

## Task 8: AI relevance ranking (`context.py` part 3)

**Files:**
- Modify: `pydantic_deep/toolsets/scoped_memory/context.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
import json
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, TextPart


def _fixed_indices_model(indices):
    def fn(messages, info):
        return ModelResponse(parts=[TextPart(json.dumps({"indices": indices}))])
    return FunctionModel(fn)


class TestAISelect:
    def _cands(self):
        return [
            MemoryEntry(name="a", description="testing", type="user", content="x", created="2026-06-04"),
            MemoryEntry(name="b", description="deploys", type="user", content="y", created="2026-06-04"),
            MemoryEntry(name="c", description="oncall", type="user", content="z", created="2026-06-04"),
        ]

    async def test_ai_select_returns_chosen(self):
        out = await context.ai_select_memories("testing", self._cands(), 5, _fixed_indices_model([0, 2]))
        assert [e.name for e in out] == ["a", "c"]

    async def test_ai_select_clamps_out_of_range(self):
        out = await context.ai_select_memories("q", self._cands(), 5, _fixed_indices_model([0, 99, -1]))
        assert [e.name for e in out] == ["a"]

    async def test_ai_select_falls_back_on_bad_json(self):
        bad = FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("not json")]))
        out = await context.ai_select_memories("q", self._cands(), 2, bad)
        assert [e.name for e in out] == ["a", "b"]  # keyword fallback = first N
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestAISelect -v`
Expected: FAIL — `AttributeError: ... 'ai_select_memories'`

- [ ] **Step 3: Add AI selection to `context.py`**

```python
# append to pydantic_deep/toolsets/scoped_memory/context.py
import json  # add to top import block when finalizing

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model


class _Selection(BaseModel):
    indices: list[int]


_AI_SELECT_SYSTEM = (
    "You select memories relevant to a query. Given a numbered list, return the 0-based "
    "indices of entries clearly relevant to the query, at most the requested count. "
    "Return an empty list if none are relevant."
)


async def ai_select_memories(
    query: str,
    candidates: list[MemoryEntry],
    max_results: int,
    model: Model | str,
) -> list[MemoryEntry]:
    """AI-rank candidates; fall back to the first ``max_results`` candidates on any error."""
    manifest = "\n".join(
        f"{i}: [{e.type}] {e.name} — {e.description}" for i, e in enumerate(candidates)
    )
    try:
        agent: Agent[None, _Selection] = Agent(model, output_type=_Selection, system_prompt=_AI_SELECT_SYSTEM)
        result = await agent.run(f"Query: {query}\nReturn at most {max_results} indices.\n\nMemories:\n{manifest}")
        chosen = result.output.indices
    except Exception:
        chosen = list(range(min(max_results, len(candidates))))

    out: list[MemoryEntry] = []
    for i in chosen[:max_results]:
        if 0 <= i < len(candidates):
            out.append(candidates[i])
    return out
```

> The bad-JSON test exercises the `except` branch because pydantic-ai raises when the model output cannot be coerced to `_Selection`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestAISelect -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/context.py tests/test_scoped_memory.py
git commit -m "feat(memory): AI relevance ranking via internal Agent with fallback"
```

---

## Task 9: Index injection text (`context.py` part 4)

**Files:**
- Modify: `pydantic_deep/toolsets/scoped_memory/context.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
class TestMemoryContext:
    def test_empty(self):
        assert context.get_memory_context("", "") == ""

    def test_user_only(self):
        out = context.get_memory_context("- [a](a.md) — x", "")
        assert out == "- [a](a.md) — x"

    def test_both_scopes_labelled(self):
        out = context.get_memory_context("- [u](u.md) — x", "- [p](p.md) — y")
        assert "- [u](u.md) — x" in out
        assert "[Project memories]" in out
        assert "- [p](p.md) — y" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestMemoryContext -v`
Expected: FAIL — `AttributeError: ... 'get_memory_context'`

- [ ] **Step 3: Add `get_memory_context` to `context.py`**

```python
# append to pydantic_deep/toolsets/scoped_memory/context.py

def get_memory_context(user_index: str, project_index: str) -> str:
    """Combine user + project index content (already raw MEMORY.md strings) for prompt
    injection, truncating each and labelling the project block. '' when both empty."""
    parts: list[str] = []
    if user_index.strip():
        parts.append(truncate_index_content(user_index))
    if project_index.strip():
        parts.append(f"[Project memories]\n{truncate_index_content(project_index)}")
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestMemoryContext -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/context.py tests/test_scoped_memory.py
git commit -m "feat(memory): combined user+project index injection text"
```

---

## Task 10: Consolidation (`consolidator.py`)

**Files:**
- Create: `pydantic_deep/toolsets/scoped_memory/consolidator.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_deep.toolsets.scoped_memory import consolidator


def _consolidation_model(memories):
    def fn(messages, info):
        return ModelResponse(parts=[TextPart(json.dumps({"memories": memories}))])
    return FunctionModel(fn)


def _history(n):
    msgs = []
    for i in range(n):
        msgs.append(ModelRequest(parts=[UserPromptPart(content=f"user msg {i}")]))
        msgs.append(ModelResponse(parts=[TextPart(f"assistant msg {i}")]))
    return msgs


class TestConsolidator:
    async def test_skips_short_session(self):
        b = StateBackend()
        saved = await consolidator.consolidate_session(
            _history(1), _consolidation_model([]), backend=b, base_dir="main", min_messages=8)
        assert saved == []

    async def test_saves_capped_at_three(self):
        b = StateBackend()
        mems = [
            {"name": f"m{i}", "type": "user", "description": "d", "content": "c", "confidence": 0.8}
            for i in range(5)
        ]
        saved = await consolidator.consolidate_session(
            _history(10), _consolidation_model(mems), backend=b, base_dir="main")
        assert len(saved) == 3
        assert [e.source for e in store.load_entries(b, "main")] == ["consolidator"] * 3

    async def test_skips_equal_or_higher_confidence_existing(self):
        b = StateBackend()
        store.save_memory(b, "main", MemoryEntry(
            name="m0", description="d", type="user", content="existing",
            created="2026-06-04", confidence=0.8), scope="user")
        saved = await consolidator.consolidate_session(
            _history(10),
            _consolidation_model([{"name": "m0", "type": "user", "description": "d",
                                   "content": "new", "confidence": 0.8}]),
            backend=b, base_dir="main")
        assert saved == []  # existing 0.8 >= new 0.8

    async def test_malformed_output_returns_empty(self):
        b = StateBackend()
        bad = FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("garbage")]))
        saved = await consolidator.consolidate_session(_history(10), bad, backend=b, base_dir="main")
        assert saved == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestConsolidator -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create `consolidator.py`**

```python
# pydantic_deep/toolsets/scoped_memory/consolidator.py
"""App-triggered AI consolidation: extract <=3 long-term memories from a session."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai_backends import BackendProtocol, LocalBackend

from .store import check_conflict, save_memory
from .types import MemoryEntry

MIN_MESSAGES_TO_CONSOLIDATE = 8
_MAX_MEMORIES = 3

_SYSTEM = (
    "You are a memory consolidation assistant. From the conversation, extract at most 3 "
    "durable memories worth keeping for future sessions: new user preferences, project "
    "decisions/facts (not derivable from code/git), or behavioral feedback. For each return "
    "name (slug), type (user|feedback|project), description (one line), content (for "
    "feedback/project lead with the rule then **Why:**/**How to apply:**), and confidence "
    "(~0.8 inferred, ~0.9 clearly stated). Return an empty list if nothing is worth saving."
)


class _ConsolidatedMemory(BaseModel):
    name: str
    type: str
    description: str
    content: str
    confidence: float = 0.8


class _ConsolidationResult(BaseModel):
    memories: list[_ConsolidatedMemory]


def _transcript(messages: list[ModelMessage], limit: int = 40) -> str:
    lines: list[str] = []
    for m in messages[-limit:]:
        if isinstance(m, ModelRequest):
            for part in m.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str) and part.content.strip():
                    lines.append(f"User: {part.content[:600]}".replace("\n", " "))
        elif isinstance(m, ModelResponse):
            for part in m.parts:
                if isinstance(part, TextPart) and part.content.strip():
                    lines.append(f"Assistant: {part.content[:600]}".replace("\n", " "))
    return "\n".join(lines)


async def consolidate_session(
    messages: list[ModelMessage],
    model: Model | str,
    *,
    backend: BackendProtocol | None = None,
    base_dir: str = "main",
    scope: str = "user",
    min_messages: int = MIN_MESSAGES_TO_CONSOLIDATE,
) -> list[str]:
    """Analyze a session and persist up to 3 consolidator-sourced memories.

    Returns saved memory names ([] on skip/error). Never raises."""
    if len(messages) < min_messages:
        return []
    transcript = _transcript(messages)
    if not transcript:
        return []
    target = backend or LocalBackend(root_dir=str(_default_user_root()))
    try:
        agent: Agent[None, _ConsolidationResult] = Agent(
            model, output_type=_ConsolidationResult, system_prompt=_SYSTEM)
        result = await agent.run(f"Conversation:\n\n{transcript}")
        candidates = result.output.memories
    except Exception:
        return []

    saved: list[str] = []
    today = date.today().isoformat()
    for m in candidates[:_MAX_MEMORIES]:
        entry = MemoryEntry(
            name=m.name, description=m.description, type=m.type, content=m.content,
            created=today, confidence=m.confidence, source="consolidator")
        conflict = check_conflict(target, base_dir, entry)
        if conflict and conflict["existing_confidence"] >= entry.confidence:
            continue
        try:
            save_memory(target, base_dir, entry, scope=scope)
        except OSError:  # pragma: no cover - defensive
            continue
        saved.append(entry.name)
    return saved


def _default_user_root() -> object:
    from pathlib import Path
    return Path.home() / ".pydantic-deep" / "memory"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestConsolidator -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/consolidator.py tests/test_scoped_memory.py
git commit -m "feat(memory): app-triggered AI consolidation (<=3, confidence-aware)"
```

---

## Task 11: `ScopedMemoryToolset` (tools + injection + scope routing)

**Files:**
- Create: `pydantic_deep/toolsets/scoped_memory/toolset.py`
- Modify: `pydantic_deep/toolsets/scoped_memory/__init__.py` (export toolset + consolidate_session)
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
from pydantic_deep.toolsets.scoped_memory import ScopedMemoryToolset


def _ts(user_backend=None):
    return ScopedMemoryToolset(agent_name="main", user_backend=user_backend or StateBackend())


class TestScopedToolset:
    async def test_save_then_search_shows_scope(self):
        ub = StateBackend()
        ts = _ts(ub)
        ctx = _make_ctx()  # project scope uses ctx.deps.backend
        await ts.tools["MemorySave"].function(
            ctx, name="user_prefers_tests", type="user",
            description="prefers pytest", content="Uses pytest.", scope="user")
        out = await ts.tools["MemorySearch"].function(ctx, query="pytest")
        assert "user_prefers_tests" in out
        assert "[user/user]" in out  # type/scope tag present

    async def test_save_project_scope_uses_run_backend(self):
        ts = _ts()
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="proj", type="project", description="d",
            content="c", scope="project")
        # stored under project base in the run backend
        assert ctx.deps.backend.exists(".pydantic-deep/memory/main/proj.md")

    async def test_save_conflict_note(self):
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        kw = dict(name="m", type="user", description="d", scope="user")
        await ts.tools["MemorySave"].function(ctx, content="old", **kw)
        msg = await ts.tools["MemorySave"].function(ctx, content="new", **kw)
        assert "Replaced conflicting memory" in msg

    async def test_delete(self):
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="m", type="user", description="d", content="c", scope="user")
        out = await ts.tools["MemoryDelete"].function(ctx, name="m", scope="user")
        assert "deleted" in out.lower()

    async def test_list_shows_tags(self):
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="m", type="feedback", description="d", content="c",
            scope="user", confidence=0.8, source="model")
        out = await ts.tools["MemoryList"].function(ctx, scope="all")
        assert "feedback" in out and "user" in out and "conf:80%" in out

    async def test_search_no_results(self):
        ts = _ts(StateBackend())
        out = await ts.tools["MemorySearch"].function(_make_ctx(), query="nothing")
        assert "No memories" in out

    async def test_get_instructions_injects_indexes(self):
        ub = StateBackend()
        ts = _ts(ub)
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="m", type="user", description="d", content="c", scope="user")
        parts = await ts.get_instructions(ctx)
        text = "\n".join(p.content for p in parts)
        assert "Memory system" in text
        assert "- [m](m.md)" in text

    async def test_get_instructions_none_when_empty(self):
        ts = _ts(StateBackend())
        assert await ts.get_instructions(_make_ctx()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestScopedToolset -v`
Expected: FAIL — `ImportError: cannot import name 'ScopedMemoryToolset'`

- [ ] **Step 3: Create `toolset.py`**

```python
# pydantic_deep/toolsets/scoped_memory/toolset.py
"""ScopedMemoryToolset: MemorySave/Search/Delete/List + system-prompt injection."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic_ai import RunContext
from pydantic_ai.messages import InstructionPart
from pydantic_ai.models import Model
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_backends import BackendProtocol, LocalBackend

from . import context as ctxmod
from . import store
from .scan import memory_age_days, memory_freshness_text
from .types import MEMORY_SYSTEM_PROMPT, MemoryEntry

_Scope = Literal["user", "project"]
_SearchScope = Literal["user", "project", "all"]


def default_user_backend() -> LocalBackend:
    """Dedicated cross-project user-scope backend at ~/.pydantic-deep/memory."""
    root = Path.home() / ".pydantic-deep" / "memory"
    return LocalBackend(root_dir=str(root))


class ScopedMemoryToolset(FunctionToolset[Any]):
    """Typed, scoped, file-per-memory toolset on top of BackendProtocol."""

    def __init__(
        self,
        *,
        agent_name: str = "main",
        user_backend: BackendProtocol | None = None,
        project_base: str = ".pydantic-deep/memory",
        staleness_days: int = 7,
        max_results_default: int = 5,
        ai_model: Model | str | None = None,
    ) -> None:
        super().__init__(id="scoped-memory")
        self._agent_name = agent_name
        self._user_backend = user_backend or default_user_backend()
        self._project_base = project_base.rstrip("/")
        self._staleness_days = staleness_days
        self._max_results_default = max_results_default
        self._ai_model = ai_model

        self.add_function(self._memory_save, name="MemorySave")
        self.add_function(self._memory_search, name="MemorySearch")
        self.add_function(self._memory_delete, name="MemoryDelete")
        self.add_function(self._memory_list, name="MemoryList")

    # ── scope resolution ────────────────────────────────────────────────
    def _resolve(self, ctx: RunContext[Any], scope: str) -> tuple[BackendProtocol, str]:
        if scope == "project":
            return ctx.deps.backend, f"{self._project_base}/{self._agent_name}"
        return self._user_backend, self._agent_name

    def _load_scope(self, ctx: RunContext[Any], scope: str) -> list[MemoryEntry]:
        backend, base = self._resolve(ctx, scope)
        return store.load_entries(backend, base, scope=scope)

    # ── tools ───────────────────────────────────────────────────────────
    async def _memory_save(
        self,
        ctx: RunContext[Any],
        name: str,
        type: str,
        description: str,
        content: str,
        scope: _Scope = "user",
        confidence: float = 1.0,
        source: Literal["user", "model", "tool"] = "user",
        conflict_group: str = "",
    ) -> str:
        """Save/update a persistent memory. Use for info that should persist across
        sessions (user prefs, feedback, project context, references). Do NOT save code
        patterns, architecture, git history, or task state. For feedback/project content
        lead with the rule/fact then **Why:** and **How to apply:** lines."""
        from datetime import date
        backend, base = self._resolve(ctx, scope)
        entry = MemoryEntry(
            name=name, description=description, type=type, content=content,
            created=date.today().isoformat(), confidence=confidence, source=source,
            conflict_group=conflict_group)
        conflict = store.check_conflict(backend, base, entry)
        store.save_memory(backend, base, entry, scope=scope)
        msg = f"Memory saved: '{name}' [{type}/{scope}]"
        if confidence < 1.0:
            msg += f" (confidence: {confidence:.0%})"
        if conflict:
            preview = conflict["existing_content"][:120]
            msg += (f"\n⚠ Replaced conflicting memory (was {conflict['existing_source']}-sourced, "
                    f"{conflict['existing_confidence']:.0%} confidence, "
                    f"written {conflict['existing_created'] or 'unknown date'}). Old: {preview}")
        return msg

    async def _memory_search(
        self,
        ctx: RunContext[Any],
        query: str,
        scope: _SearchScope = "all",
        use_ai: bool = False,
        max_results: int | None = None,
    ) -> str:
        """Search persistent memories by keyword (optionally AI-ranked). Returns matches
        with a content preview, scope tag, and a staleness caveat for old memories."""
        limit = max_results or self._max_results_default
        scopes = ["user", "project"] if scope == "all" else [scope]
        entries: list[MemoryEntry] = []
        for s in scopes:
            entries.extend(self._load_scope(ctx, s))
        hits = ctxmod.keyword_filter(entries, query)
        if not hits:
            return f"No memories found matching '{query}'."

        if use_ai and self._ai_model is not None:
            hits = await ctxmod.ai_select_memories(query, hits, limit * 3, self._ai_model)
        ranked = ctxmod.rank_entries(hits)[:limit]

        for e in ranked:
            backend, _ = self._resolve(ctx, e.scope)
            store.touch_last_used(backend, e.file_path)

        lines = [f"Found {len(ranked)} memory/memories for '{query}':", ""]
        for e in ranked:
            age = memory_age_days(e.created)
            fresh = memory_freshness_text(age, self._staleness_days)
            tag = ""
            if e.confidence < 1.0 or e.source != "user":
                tag = f"  [conf:{e.confidence:.0%} src:{e.source}]"
            preview = e.content[:200] + ("..." if len(e.content) > 200 else "")
            block = f"[{e.type}/{e.scope}] {e.name}{tag}\n  {e.description}\n  {preview}"
            if fresh:
                block += f"\n  ⚠ {fresh}"
            lines.append(block)
        return "\n\n".join(lines)

    async def _memory_delete(self, ctx: RunContext[Any], name: str, scope: _Scope = "user") -> str:
        """Delete a persistent memory entry by name."""
        backend, base = self._resolve(ctx, scope)
        store.delete_memory(backend, base, name, scope=scope)
        return f"Memory deleted: '{name}' (scope: {scope})"

    async def _memory_list(self, ctx: RunContext[Any], scope: _SearchScope = "all") -> str:
        """List stored memories with type, scope, confidence, source, and group tags."""
        scopes = ["user", "project"] if scope == "all" else [scope]
        entries: list[MemoryEntry] = []
        for s in scopes:
            entries.extend(self._load_scope(ctx, s))
        if not entries:
            return "No memories stored."
        lines = [f"{len(entries)} memory/memories:"]
        for e in entries:
            meta = ""
            if e.confidence < 1.0:
                meta += f" conf:{e.confidence:.0%}"
            if e.source != "user":
                meta += f" src:{e.source}"
            if e.conflict_group:
                meta += f" grp:{e.conflict_group}"
            lines.append(f"  [{e.type:9s}|{e.scope:7s}] {e.name}{(' —' + meta) if meta else ''}")
            if e.description:
                lines.append(f"    {e.description}")
        return "\n".join(lines)

    # ── system prompt injection ─────────────────────────────────────────
    async def get_instructions(self, ctx: RunContext[Any]) -> list[InstructionPart] | None:
        user_backend, user_base = self._resolve(ctx, "user")
        proj_backend, proj_base = self._resolve(ctx, "project")
        user_idx = store.get_index_content(user_backend, user_base)
        proj_idx = store.get_index_content(proj_backend, proj_base)
        body = ctxmod.get_memory_context(user_idx, proj_idx)
        if not body:
            return None
        return [InstructionPart(content=f"{MEMORY_SYSTEM_PROMPT}\n\n## MEMORY.md\n{body}", dynamic=True)]
```

> **Step 3a (verify API):** `FunctionToolset.add_function` is used here to register bound methods with explicit tool names. If the installed pydantic-ai version names this differently, register via the `@self.tool(name=...)` decorator inside `__init__` instead (the decorator's `name` param was confirmed available). Run a quick `uv run python -c "from pydantic_ai.toolsets import FunctionToolset; print(hasattr(FunctionToolset,'add_function'))"` and pick the working path.

Update the package init:
```python
# pydantic_deep/toolsets/scoped_memory/__init__.py  (append)
from .consolidator import consolidate_session
from .toolset import ScopedMemoryToolset, default_user_backend

__all__ += ["ScopedMemoryToolset", "default_user_backend", "consolidate_session"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestScopedToolset -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/scoped_memory/ tests/test_scoped_memory.py
git commit -m "feat(memory): ScopedMemoryToolset with 4 tools + scope routing + injection"
```

---

## Task 12: `ScopedMemoryCapability`

**Files:**
- Create: `pydantic_deep/capabilities/scoped_memory.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
from pydantic_deep.capabilities.scoped_memory import ScopedMemoryCapability


class TestScopedCapability:
    def test_get_toolset_is_scoped(self):
        cap = ScopedMemoryCapability(agent_name="main", user_backend=StateBackend())
        assert isinstance(cap.get_toolset(), ScopedMemoryToolset)

    async def test_instructions_callable_returns_none_when_empty(self):
        cap = ScopedMemoryCapability(agent_name="main", user_backend=StateBackend())
        fn = cap.get_instructions()
        assert await fn(_make_ctx()) is None

    async def test_instructions_present_after_save(self):
        ub = StateBackend()
        cap = ScopedMemoryCapability(agent_name="main", user_backend=ub)
        ts = cap.get_toolset()
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="m", type="user", description="d", content="c", scope="user")
        text = await cap.get_instructions()(ctx)
        assert "Memory system" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestScopedCapability -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create `capabilities/scoped_memory.py`**

```python
# pydantic_deep/capabilities/scoped_memory.py
"""Scoped, typed agent memory capability."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai_backends import BackendProtocol

from pydantic_deep.toolsets.scoped_memory.toolset import ScopedMemoryToolset


@dataclass
class ScopedMemoryCapability(AbstractCapability[Any]):
    """Persistent, scoped, typed memory. User scope → dedicated backend; project scope →
    the run's backend. Provides MemorySave/Search/Delete/List and injects both indexes."""

    agent_name: str = "main"
    user_backend: BackendProtocol | None = None
    project_base: str = ".pydantic-deep/memory"
    staleness_days: int = 7
    ai_model: Model | str | None = None
    _toolset: ScopedMemoryToolset | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._toolset = ScopedMemoryToolset(
            agent_name=self.agent_name,
            user_backend=self.user_backend,
            project_base=self.project_base,
            staleness_days=self.staleness_days,
            ai_model=self.ai_model,
        )

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset

    def get_instructions(self) -> Any:
        toolset = self._toolset

        async def _instructions(ctx: RunContext[Any]) -> str | None:
            if toolset is None or not hasattr(ctx.deps, "backend"):
                return None
            parts = await toolset.get_instructions(ctx)
            return "\n\n".join(p.content for p in parts) if parts else None

        return _instructions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestScopedCapability -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/capabilities/scoped_memory.py tests/test_scoped_memory.py
git commit -m "feat(memory): ScopedMemoryCapability wiring toolset + instructions"
```

---

## Task 13: Deprecate the legacy memory API

**Files:**
- Modify: `pydantic_deep/toolsets/memory.py` (decorate `AgentMemoryToolset`)
- Modify: `pydantic_deep/capabilities/memory.py` (decorate `MemoryCapability`)
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
import warnings


class TestDeprecation:
    def test_agent_memory_toolset_deprecated(self):
        from pydantic_deep.toolsets.memory import AgentMemoryToolset
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            AgentMemoryToolset(agent_name="main")
        assert any(issubclass(x.category, DeprecationWarning) for x in w)

    def test_memory_capability_deprecated(self):
        from pydantic_deep.capabilities.memory import MemoryCapability
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            MemoryCapability()
        assert any(issubclass(x.category, DeprecationWarning) for x in w)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestDeprecation -v`
Expected: FAIL — no `DeprecationWarning` emitted

- [ ] **Step 3: Add deprecation via `__init__` warnings**

In `pydantic_deep/toolsets/memory.py`, at the very start of `AgentMemoryToolset.__init__` (before `super().__init__`):
```python
        import warnings
        warnings.warn(
            "AgentMemoryToolset is deprecated; use "
            "pydantic_deep.toolsets.scoped_memory.ScopedMemoryToolset instead.",
            DeprecationWarning,
            stacklevel=2,
        )
```

In `pydantic_deep/capabilities/memory.py`, at the start of `MemoryCapability.__post_init__` (before building the toolset):
```python
        import warnings
        warnings.warn(
            "MemoryCapability is deprecated; use "
            "pydantic_deep.capabilities.scoped_memory.ScopedMemoryCapability instead.",
            DeprecationWarning,
            stacklevel=2,
        )
```

> Use a runtime `warnings.warn` rather than the `@deprecated` decorator here because the existing test suite instantiates these classes; a class-level `@deprecated` triggers type-checker errors at every call site. Confirm `make test` for the legacy `tests/test_memory.py` still passes (it asserts behavior, not warning-free construction); if any legacy test fails on the new warning, wrap that instantiation in `pytest.warns(DeprecationWarning)` or `warnings.catch_warnings`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestDeprecation tests/test_memory.py -v`
Expected: PASS (both new deprecation tests and the legacy suite)

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/toolsets/memory.py pydantic_deep/capabilities/memory.py tests/test_scoped_memory.py
git commit -m "feat(memory): deprecate legacy AgentMemoryToolset/MemoryCapability"
```

---

## Task 14: Public API exports

**Files:**
- Modify: `pydantic_deep/__init__.py`
- Test: `tests/test_scoped_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_scoped_memory.py
class TestPublicAPI:
    def test_top_level_exports(self):
        import pydantic_deep as pd
        for name in ("ScopedMemoryToolset", "ScopedMemoryCapability",
                     "consolidate_session", "MemoryEntry", "MEMORY_SYSTEM_PROMPT"):
            assert hasattr(pd, name), name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_memory.py::TestPublicAPI -v`
Expected: FAIL — `AssertionError: ScopedMemoryToolset`

- [ ] **Step 3: Add exports to `pydantic_deep/__init__.py`**

Add imports near the other toolset/capability imports:
```python
from pydantic_deep.toolsets.scoped_memory import (
    MEMORY_SYSTEM_PROMPT,
    MemoryEntry,
    ScopedMemoryToolset,
    consolidate_session,
)
from pydantic_deep.capabilities.scoped_memory import ScopedMemoryCapability
```
Add each name to `__all__`:
```python
    "ScopedMemoryToolset",
    "ScopedMemoryCapability",
    "consolidate_session",
    "MemoryEntry",
    "MEMORY_SYSTEM_PROMPT",
```

> Note: `MemoryEntry` is a new public name (the legacy module had no such export), so there is no collision. If a name clash with an existing export appears at import time, alias the scoped one (e.g. `ScopedMemoryEntry`) and update the test.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scoped_memory.py::TestPublicAPI -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pydantic_deep/__init__.py tests/test_scoped_memory.py
git commit -m "feat(memory): export scoped memory public API"
```

---

## Task 15: Full suite, coverage, type checks, docs

**Files:**
- Modify: `CLAUDE.md` (add scoped-memory entry under capabilities/toolsets — optional but recommended)
- Verify: whole repo

- [ ] **Step 1: Run the full test suite with coverage**

Run: `make test`
Expected: all tests pass; coverage 100%. If any line in the new package is uncovered, add a targeted test (e.g. the `_list_md_paths` `except` branch via a backend whose `glob_info` raises, the `parse_frontmatter` unterminated branch, the `confidence` `ValueError` branch). Use `# pragma: no cover` only for the genuinely-unreachable backend-`delete` fallback.

- [ ] **Step 2: Type checks**

Run: `make typecheck` then `make typecheck-mypy`
Expected: no errors. Fix any `Any`/Optional issues (e.g. annotate `ctx.deps.backend` access, ensure tool signatures use concrete types).

- [ ] **Step 3: Lint / pre-commit**

Run: `make all` (or `pre-commit run --all-files`)
Expected: clean.

- [ ] **Step 4: Update CLAUDE.md (recommended)**

Add a short subsection under the capabilities list documenting `ScopedMemoryCapability` / `ScopedMemoryToolset` (4 tools, dual scope, `~/.pydantic-deep/memory` user backend, `consolidate_session`), and note the legacy classes are deprecated. Mirror the existing entry style.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test(memory): close coverage; docs: document scoped memory + deprecation"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- File-per-memory + frontmatter → Tasks 2–3 ✓
- 4 types + system prompt → Task 1 ✓
- Dual scope (dedicated user backend + project) → Tasks 11–12 ✓
- Conflict detection (slug-based, advisory conflict_group) → Task 4 + Task 11 (note) ✓
- created-based recency, last_used decoupled → Tasks 5, 7 ✓
- Configurable staleness_days (default 7) → Tasks 5, 11 ✓
- Keyword + AI search, silent fallback → Tasks 7, 8, 11 ✓
- Index truncation (200/25k), index-only injection → Tasks 6, 9, 11 ✓
- App-triggered consolidation (≤3, `>=` tie-break, source=consolidator) → Task 10 ✓
- Scope shown in search/list output → Task 11 tests ✓
- Deprecate legacy API → Task 13 ✓
- Public API exports → Task 14 ✓
- 100% coverage + strict types → Task 15 ✓

**Placeholder scan:** none — every code step contains full code.

**Type/name consistency:** `save_memory`/`load_entries`/`delete_memory`/`check_conflict`/`touch_last_used`/`get_index_content` (store), `keyword_filter`/`rank_entries`/`rank_score`/`ai_select_memories`/`get_memory_context`/`truncate_index_content` (context), `memory_age_days`/`memory_freshness_text` (scan), `consolidate_session` (consolidator), tool names `MemorySave`/`MemorySearch`/`MemoryDelete`/`MemoryList` — used consistently across tasks.

**Two API-verification points flagged inline** (backend `delete` method name in Task 3; `FunctionToolset.add_function` vs `@tool` decorator in Task 11) — both have a concrete check command and fallback.
```