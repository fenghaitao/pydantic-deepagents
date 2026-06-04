"""Tests for the scoped, typed agent memory package."""

import json
import math

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai_backends import StateBackend

from pydantic_deep.toolsets.scoped_memory import context, scan, store
from pydantic_deep.toolsets.scoped_memory.store import INDEX_FILENAME as _IDX
from pydantic_deep.toolsets.scoped_memory.types import (
    MEMORY_SYSTEM_PROMPT,
    MEMORY_TYPES,
    MemoryEntry,
)

INDEX_STEM = _IDX.removesuffix(".md")


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
