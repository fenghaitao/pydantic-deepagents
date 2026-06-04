"""Tests for the scoped, typed agent memory package."""

from pydantic_ai_backends import StateBackend

from pydantic_deep.toolsets.scoped_memory import store
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
