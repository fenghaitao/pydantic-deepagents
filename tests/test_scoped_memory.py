"""Tests for the scoped, typed agent memory package."""
from pydantic_deep.toolsets.scoped_memory import store
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
