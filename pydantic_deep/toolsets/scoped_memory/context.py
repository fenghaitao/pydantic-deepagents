"""System-prompt index injection, keyword+AI relevance, and index truncation."""

from __future__ import annotations

import math

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model

from .scan import memory_age_days
from .store import INDEX_FILENAME
from .types import MemoryEntry

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


def keyword_filter(entries: list[MemoryEntry], query: str) -> list[MemoryEntry]:
    """Case-insensitive substring match over name + description + content."""
    q = query.lower()
    return [e for e in entries if q in f"{e.name} {e.description} {e.content}".lower()]


def rank_score(entry: MemoryEntry, today: str | None = None) -> float:
    """confidence × exp(-age_days / 30), age from `created` only."""
    age = memory_age_days(entry.created, today=today)
    return entry.confidence * math.exp(-age / 30)


def rank_entries(entries: list[MemoryEntry], today: str | None = None) -> list[MemoryEntry]:
    """Sort by rank_score descending (stable)."""
    return sorted(entries, key=lambda e: rank_score(e, today=today), reverse=True)


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
        agent: Agent[None, _Selection] = Agent(
            model, output_type=_Selection, system_prompt=_AI_SELECT_SYSTEM
        )
        result = await agent.run(
            f"Query: {query}\nReturn at most {max_results} indices.\n\nMemories:\n{manifest}"
        )
        chosen = result.output.indices
    except Exception:
        chosen = list(range(min(max_results, len(candidates))))

    out: list[MemoryEntry] = []
    for i in chosen[:max_results]:
        if 0 <= i < len(candidates):
            out.append(candidates[i])
    return out
