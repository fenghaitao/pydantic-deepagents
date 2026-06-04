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
