"""ScopedMemoryToolset: MemorySave/Search/Delete/List + system-prompt injection."""

from __future__ import annotations

from datetime import date
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
        # Built lazily on first user-scope access so merely constructing the toolset
        # (e.g. in a dry run or with project scope only) never touches ~/.pydantic-deep.
        self._user_backend = user_backend
        self._project_base = project_base.rstrip("/")
        self._staleness_days = staleness_days
        self._max_results_default = max_results_default
        self._ai_model = ai_model

        self.add_function(self._memory_save, name="MemorySave")
        self.add_function(self._memory_search, name="MemorySearch")
        self.add_function(self._memory_delete, name="MemoryDelete")
        self.add_function(self._memory_list, name="MemoryList")

    def _ensure_user_backend(self) -> BackendProtocol:
        if self._user_backend is None:
            self._user_backend = default_user_backend()
        return self._user_backend

    def _resolve(self, ctx: RunContext[Any], scope: str) -> tuple[BackendProtocol, str]:
        if scope == "project":
            return ctx.deps.backend, f"{self._project_base}/{self._agent_name}"
        return self._ensure_user_backend(), self._agent_name

    def _load_scope(self, ctx: RunContext[Any], scope: str) -> list[MemoryEntry]:
        backend, base = self._resolve(ctx, scope)
        return store.load_entries(backend, base, scope=scope)

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
        backend, base = self._resolve(ctx, scope)
        entry = MemoryEntry(
            name=name,
            description=description,
            type=type,
            content=content,
            created=date.today().isoformat(),
            confidence=confidence,
            source=source,
            conflict_group=conflict_group,
        )
        conflict = store.check_conflict(backend, base, entry)
        store.save_memory(backend, base, entry, scope=scope)
        msg = f"Memory saved: '{name}' [{type}/{scope}]"
        if confidence < 1.0:
            msg += f" (confidence: {confidence:.0%})"
        if conflict:
            preview = str(conflict["existing_content"])[:120]
            existing_conf = float(str(conflict["existing_confidence"]))
            msg += (
                f"\n⚠ Replaced conflicting memory (was {conflict['existing_source']}-sourced, "
                f"{existing_conf:.0%} confidence, "
                f"written {conflict['existing_created'] or 'unknown date'}). Old: {preview}"
            )
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

    async def get_instructions(self, ctx: RunContext[Any]) -> list[InstructionPart] | None:
        user_backend, user_base = self._resolve(ctx, "user")
        proj_backend, proj_base = self._resolve(ctx, "project")
        user_idx = store.get_index_content(user_backend, user_base)
        proj_idx = store.get_index_content(proj_backend, proj_base)
        body = ctxmod.get_memory_context(user_idx, proj_idx)
        if not body:
            return None
        return [
            InstructionPart(content=f"{MEMORY_SYSTEM_PROMPT}\n\n## MEMORY.md\n{body}", dynamic=True)
        ]
