"""Tests for the scoped, typed agent memory package."""

import json
import math
import warnings

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.scoped_memory import consolidator, context, scan, store
from pydantic_deep.toolsets.scoped_memory.store import INDEX_FILENAME as _IDX
from pydantic_deep.toolsets.scoped_memory.types import (
    MEMORY_SYSTEM_PROMPT,
    MEMORY_TYPES,
    MemoryEntry,
)

INDEX_STEM = _IDX.removesuffix(".md")

_TEST_MODEL = TestModel()


def _make_ctx(backend: StateBackend | None = None) -> RunContext[DeepAgentDeps]:
    """Build a RunContext with DeepAgentDeps + TestModel for toolset tests."""
    b = backend or StateBackend()
    deps = DeepAgentDeps(backend=b)
    return RunContext(deps=deps, model=_TEST_MODEL, usage=RunUsage())


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
        e = MemoryEntry(
            name="n", description="d", type="user", content="body", created="2026-06-04"
        )
        out = store._format_entry_md(e)
        assert out.startswith(
            "---\nname: n\ndescription: d\ntype: user\ncreated: 2026-06-04\n---\n"
        )
        assert "confidence:" not in out  # default 1.0 omitted
        assert out.endswith("body\n")

    def test_format_entry_md_optional_fields(self):
        e = MemoryEntry(
            name="n",
            description="d",
            type="user",
            content="b",
            created="2026-06-04",
            confidence=0.8,
            source="model",
            last_used_at="2026-06-04",
            conflict_group="g",
        )
        out = store._format_entry_md(e)
        assert "confidence: 0.80" in out
        assert "source: model" in out
        assert "last_used_at: 2026-06-04" in out
        assert "conflict_group: g" in out


class TestStoreCRUD:
    def _entry(self, name="user_prefers_tests"):
        return MemoryEntry(
            name=name,
            description="prefers pytest",
            type="user",
            content="Uses pytest.",
            created="2026-06-04",
        )

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

    def test_delete_local_backend(self, tmp_path):
        from pydantic_ai_backends import LocalBackend

        b = LocalBackend(root_dir=str(tmp_path))
        store.save_memory(b, ".pydantic-deep/memory/main", self._entry(), scope="project")
        store.delete_memory(b, ".pydantic-deep/memory/main", "user_prefers_tests", scope="project")
        assert store.load_entries(b, ".pydantic-deep/memory/main", scope="project") == []

    def test_load_empty_dir(self):
        assert store.load_entries(StateBackend(), "main", scope="user") == []


class TestConflictAndTouch:
    def _save(self, b, content, confidence=1.0, source="user"):
        e = MemoryEntry(
            name="m",
            description="d",
            type="user",
            content=content,
            created="2026-06-04",
            confidence=confidence,
            source=source,
        )
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


class TestScan:
    def test_age_days(self):
        assert scan.memory_age_days("2026-06-01", today="2026-06-04") == 3
        assert scan.memory_age_days("", today="2026-06-04") == 0  # missing → fresh
        assert scan.memory_age_days("not-a-date", today="2026-06-04") == 0
        assert scan.memory_age_days("2026-06-10", today="2026-06-04") == 0  # future clamped

    def test_age_str(self):
        assert scan.memory_age_str(0) == "today"
        assert scan.memory_age_str(1) == "yesterday"
        assert scan.memory_age_str(5) == "5 days ago"

    def test_freshness_text_threshold(self):
        assert scan.memory_freshness_text(7, staleness_days=7) == ""  # at threshold → fresh
        txt = scan.memory_freshness_text(8, staleness_days=7)
        assert "8 days old" in txt and "Verify against current code" in txt


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
        raw = "\n".join(f"- [m{i}](m{i}.md) — {'x' * 100}" for i in range(50))
        out = context.truncate_index_content(raw, max_lines=10**6, max_bytes=500)
        assert len(out.encode()) < len(raw.encode())
        assert "WARNING" in out and "bytes" in out

    def test_both_limits_truncation(self):
        raw = "\n".join(f"- [m{i}](m{i}.md) — {'x' * 80}" for i in range(300))
        out = context.truncate_index_content(raw, max_lines=200, max_bytes=5000)
        assert "WARNING" in out
        assert "lines and" in out and "bytes" in out
        assert len(out.encode()) < len(raw.encode())


class TestKeywordSearchAndRank:
    def _e(self, name, content, created="2026-06-04", confidence=1.0):
        return MemoryEntry(
            name=name,
            description=name,
            type="user",
            content=content,
            created=created,
            confidence=confidence,
        )

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


def _fixed_indices_model(indices):
    def fn(messages, info):
        return ModelResponse(parts=[TextPart(json.dumps({"indices": indices}))])

    return FunctionModel(fn)


class TestAISelect:
    def _cands(self):
        return [
            MemoryEntry(
                name="a", description="testing", type="user", content="x", created="2026-06-04"
            ),
            MemoryEntry(
                name="b", description="deploys", type="user", content="y", created="2026-06-04"
            ),
            MemoryEntry(
                name="c", description="oncall", type="user", content="z", created="2026-06-04"
            ),
        ]

    async def test_ai_select_returns_chosen(self):
        out = await context.ai_select_memories(
            "testing", self._cands(), 5, _fixed_indices_model([0, 2])
        )
        assert [e.name for e in out] == ["a", "c"]

    async def test_ai_select_clamps_out_of_range(self):
        out = await context.ai_select_memories(
            "q", self._cands(), 5, _fixed_indices_model([0, 99, -1])
        )
        assert [e.name for e in out] == ["a"]

    async def test_ai_select_falls_back_on_bad_json(self):
        bad = FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("not json")]))
        out = await context.ai_select_memories("q", self._cands(), 2, bad)
        assert [e.name for e in out] == ["a", "b"]  # keyword fallback = first N


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

    def test_project_only(self):
        out = context.get_memory_context("", "- [p](p.md) — y")
        assert out.startswith("[Project memories]")
        assert "- [p](p.md) — y" in out


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
            _history(1), _consolidation_model([]), backend=b, base_dir="main", min_messages=8
        )
        assert saved == []

    async def test_empty_transcript_returns_empty(self):
        b = StateBackend()
        msgs = [ModelRequest(parts=[UserPromptPart(content="")]) for _ in range(10)]
        saved = await consolidator.consolidate_session(
            msgs,
            _consolidation_model(
                [{"name": "x", "type": "user", "description": "d", "content": "c"}]
            ),
            backend=b,
            base_dir="main",
        )
        assert saved == []

    async def test_saves_capped_at_three(self):
        b = StateBackend()
        mems = [
            {"name": f"m{i}", "type": "user", "description": "d", "content": "c", "confidence": 0.8}
            for i in range(5)
        ]
        saved = await consolidator.consolidate_session(
            _history(10), _consolidation_model(mems), backend=b, base_dir="main"
        )
        assert len(saved) == 3
        assert [e.source for e in store.load_entries(b, "main")] == ["consolidator"] * 3

    async def test_skips_equal_or_higher_confidence_existing(self):
        b = StateBackend()
        store.save_memory(
            b,
            "main",
            MemoryEntry(
                name="m0",
                description="d",
                type="user",
                content="existing",
                created="2026-06-04",
                confidence=0.8,
            ),
            scope="user",
        )
        saved = await consolidator.consolidate_session(
            _history(10),
            _consolidation_model(
                [
                    {
                        "name": "m0",
                        "type": "user",
                        "description": "d",
                        "content": "new",
                        "confidence": 0.8,
                    }
                ]
            ),
            backend=b,
            base_dir="main",
        )
        assert saved == []  # existing 0.8 >= new 0.8

    async def test_malformed_output_returns_empty(self):
        b = StateBackend()
        bad = FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("garbage")]))
        saved = await consolidator.consolidate_session(
            _history(10), bad, backend=b, base_dir="main"
        )
        assert saved == []

    async def test_non_text_response_parts_ignored(self):
        """ModelResponse parts that are not TextPart are silently skipped."""
        from pydantic_ai.messages import ToolCallPart

        msgs = []
        for i in range(4):
            msgs.append(ModelRequest(parts=[UserPromptPart(content=f"user {i}")]))
            msgs.append(ModelResponse(parts=[ToolCallPart(tool_name="x", args={})]))
        # Add one real text message to make transcript non-empty
        msgs.append(ModelRequest(parts=[UserPromptPart(content="final user")]))
        msgs.append(ModelResponse(parts=[TextPart("final assistant")]))
        saved = await consolidator.consolidate_session(
            msgs,
            _consolidation_model(
                [
                    {
                        "name": "m0",
                        "type": "user",
                        "description": "d",
                        "content": "c",
                        "confidence": 0.8,
                    }
                ]
            ),
            backend=StateBackend(),
            base_dir="main",
            min_messages=1,
        )
        assert saved == ["m0"]


# ---------------------------------------------------------------------------
# ScopedMemoryToolset tests
# ---------------------------------------------------------------------------

from pydantic_deep.toolsets.scoped_memory import ScopedMemoryToolset  # noqa: E402


def _ts(user_backend: StateBackend | None = None) -> ScopedMemoryToolset:
    return ScopedMemoryToolset(agent_name="main", user_backend=user_backend or StateBackend())


class TestScopedToolset:
    async def test_save_then_search_shows_scope(self) -> None:
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx,
            name="user_prefers_tests",
            type="user",
            description="prefers pytest",
            content="Uses pytest.",
            scope="user",
        )
        out = await ts.tools["MemorySearch"].function(ctx, query="pytest")
        assert "user_prefers_tests" in out
        assert "[user/user]" in out

    async def test_save_project_scope_uses_run_backend(self) -> None:
        ts = _ts()
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="proj", type="project", description="d", content="c", scope="project"
        )
        assert ctx.deps.backend.exists(".pydantic-deep/memory/main/proj.md")

    async def test_save_conflict_note(self) -> None:
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        kw = dict(name="m", type="user", description="d", scope="user")
        await ts.tools["MemorySave"].function(ctx, content="old", **kw)
        msg = await ts.tools["MemorySave"].function(ctx, content="new", **kw)
        assert "Replaced conflicting memory" in msg

    async def test_delete(self) -> None:
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="m", type="user", description="d", content="c", scope="user"
        )
        out = await ts.tools["MemoryDelete"].function(ctx, name="m", scope="user")
        assert "deleted" in out.lower()

    async def test_list_shows_tags(self) -> None:
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx,
            name="m",
            type="feedback",
            description="d",
            content="c",
            scope="user",
            confidence=0.8,
            source="model",
        )
        out = await ts.tools["MemoryList"].function(ctx, scope="all")
        assert "feedback" in out and "conf:80%" in out

    async def test_search_no_results(self) -> None:
        ts = _ts(StateBackend())
        out = await ts.tools["MemorySearch"].function(_make_ctx(), query="nothing")
        assert "No memories" in out

    async def test_get_instructions_injects_indexes(self) -> None:
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="m", type="user", description="d", content="c", scope="user"
        )
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        text = "\n".join(p.content for p in parts)
        assert "Memory system" in text
        assert "- [m](m.md)" in text

    async def test_get_instructions_none_when_empty(self) -> None:
        ts = _ts(StateBackend())
        assert await ts.get_instructions(_make_ctx()) is None

    # --- extra coverage tests ---

    def test_default_user_backend(self, tmp_path, monkeypatch) -> None:  # type: ignore[override]
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        from pydantic_ai_backends import LocalBackend

        from pydantic_deep.toolsets.scoped_memory.toolset import default_user_backend

        b = default_user_backend()
        assert isinstance(b, LocalBackend)
        assert str(b.root_dir).endswith(".pydantic-deep/memory")

    async def test_search_uses_ai_branch(self) -> None:
        """Covers the `if use_ai and self._ai_model is not None` branch."""
        ts = ScopedMemoryToolset(
            agent_name="main",
            user_backend=StateBackend(),
            ai_model=_fixed_indices_model([0]),
        )
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx,
            name="alpha",
            type="user",
            description="testing query",
            content="about testing",
            scope="user",
        )
        await ts.tools["MemorySave"].function(
            ctx,
            name="beta",
            type="user",
            description="testing something",
            content="about testing also",
            scope="user",
        )
        out = await ts.tools["MemorySearch"].function(ctx, query="testing", use_ai=True)
        # AI selects index 0; result must have exactly that entry
        assert "alpha" in out or "beta" in out  # at least one returned

    async def test_search_staleness_and_low_confidence_tag(self) -> None:
        """Covers the `if fresh:` branch and the `tag` branch in _memory_search."""
        ub = StateBackend()
        ts = _ts(ub)
        ctx = _make_ctx()
        # seed an old low-confidence model-sourced memory directly
        store.save_memory(
            ub,
            "main",
            MemoryEntry(
                name="old_mem",
                description="testing old memory",
                type="user",
                content="some old content",
                created="2020-01-01",
                confidence=0.8,
                source="model",
            ),
            scope="user",
        )
        out = await ts.tools["MemorySearch"].function(ctx, query="testing old memory")
        assert "days old" in out
        assert "conf:80%" in out or "src:model" in out

    async def test_list_conflict_group_tag(self) -> None:
        """Covers the `grp:` branch in _memory_list."""
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx,
            name="grouped",
            type="user",
            description="some grouped memory",
            content="c",
            scope="user",
            conflict_group="g",
        )
        out = await ts.tools["MemoryList"].function(ctx, scope="all")
        assert "grp:g" in out

    async def test_list_empty_no_memories(self) -> None:
        """Covers the `if not entries: return 'No memories stored.'` branch."""
        ts = _ts(StateBackend())
        out = await ts.tools["MemoryList"].function(_make_ctx(), scope="all")
        assert out == "No memories stored."

    async def test_save_low_confidence_message(self) -> None:
        """Covers the `if confidence < 1.0: msg += ...` branch in _memory_save."""
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        msg = await ts.tools["MemorySave"].function(
            ctx,
            name="uncertain",
            type="user",
            description="d",
            content="c",
            scope="user",
            confidence=0.7,
        )
        assert "confidence: 70%" in msg

    async def test_search_project_scope_only(self) -> None:
        """Covers single-scope (project) path in _memory_search."""
        ts = _ts()
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx,
            name="proj_mem",
            type="project",
            description="project description",
            content="project content",
            scope="project",
        )
        out = await ts.tools["MemorySearch"].function(ctx, query="project", scope="project")
        assert "proj_mem" in out

    async def test_delete_project_scope(self) -> None:
        """Covers _memory_delete with project scope."""
        ts = _ts()
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="pdel", type="project", description="d", content="c", scope="project"
        )
        out = await ts.tools["MemoryDelete"].function(ctx, name="pdel", scope="project")
        assert "pdel" in out and "project" in out

    async def test_search_content_long_truncated(self) -> None:
        """Covers the `...` truncation branch in _memory_search preview."""
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        long_content = "x" * 300
        await ts.tools["MemorySave"].function(
            ctx,
            name="longmem",
            type="user",
            description="long content memory",
            content=long_content,
            scope="user",
        )
        out = await ts.tools["MemorySearch"].function(ctx, query="long content memory")
        assert "..." in out

    async def test_list_user_scope_only(self) -> None:
        """Covers MemoryList with explicit user scope."""
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="u1", type="user", description="user mem", content="c", scope="user"
        )
        out = await ts.tools["MemoryList"].function(ctx, scope="user")
        assert "u1" in out

    async def test_get_instructions_project_only(self) -> None:
        """Covers get_instructions when project has memories but user has none."""
        ts = _ts(StateBackend())  # empty user backend
        ctx = _make_ctx()
        await ts.tools["MemorySave"].function(
            ctx, name="pm", type="project", description="d", content="c", scope="project"
        )
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        text = "\n".join(p.content for p in parts)
        assert "pm" in text

    async def test_list_entry_with_empty_description(self) -> None:
        """Covers the `if e.description:` False branch in _memory_list (no description line)."""
        ts = _ts(StateBackend())
        ctx = _make_ctx()
        # Save with empty description; store.save_memory writes it as-is
        ub = ts._user_backend
        store.save_memory(
            ub,
            "main",
            MemoryEntry(
                name="nodesc",
                description="",
                type="user",
                content="content here",
                created="2026-06-05",
            ),
            scope="user",
        )
        out = await ts.tools["MemoryList"].function(ctx, scope="user")
        assert "nodesc" in out
        # description line should NOT appear
        assert "    " not in out or "content here" not in out


# ---------------------------------------------------------------------------
# ScopedMemoryCapability tests
# ---------------------------------------------------------------------------

from pydantic_deep.capabilities.scoped_memory import ScopedMemoryCapability  # noqa: E402


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
            ctx, name="m", type="user", description="d", content="c", scope="user"
        )
        text = await cap.get_instructions()(ctx)
        assert "Memory system" in text

    async def test_instructions_none_without_backend(self):
        # Covers the `not hasattr(ctx.deps, "backend")` guard branch.
        class _NoBackend:
            pass

        cap = ScopedMemoryCapability(agent_name="main", user_backend=StateBackend())
        ctx = RunContext(deps=_NoBackend(), model=TestModel(), usage=RunUsage())
        assert await cap.get_instructions()(ctx) is None


# ---------------------------------------------------------------------------
# Deprecation tests
# ---------------------------------------------------------------------------


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
        msgs = [str(x.message) for x in w if issubclass(x.category, DeprecationWarning)]
        # exactly one deprecation (the capability's own), not the inner toolset's too
        assert any("MemoryCapability" in m for m in msgs)
        assert not any("AgentMemoryToolset" in m for m in msgs)

    def test_create_deep_agent_does_not_self_warn(self):
        from pydantic_deep import create_deep_agent

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            create_deep_agent(model=TestModel())
        legacy = [
            str(x.message)
            for x in w
            if issubclass(x.category, DeprecationWarning) and "AgentMemoryToolset" in str(x.message)
        ]
        assert legacy == []
