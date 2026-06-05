"""App-triggered AI consolidation: extract <=3 long-term memories from a session."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    TextPart,
    UserPromptPart,
)
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
    "name (slug), type (user|feedback|project|reference), description (one line), content (for "
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
                if (
                    isinstance(part, UserPromptPart)
                    and isinstance(part.content, str)
                    and part.content.strip()
                ):
                    lines.append(f"User: {part.content[:600]}".replace("\n", " "))
        else:  # ModelResponse
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

    Returns saved memory names ([] on skip or error). Never raises."""
    if len(messages) < min_messages:
        return []
    transcript = _transcript(messages)
    if not transcript:
        return []
    if backend is None:  # pragma: no cover - real-FS default backend, not used in tests
        backend = LocalBackend(root_dir=str(Path.home() / ".pydantic-deep" / "memory"))
    try:
        agent: Agent[None, _ConsolidationResult] = Agent(
            model, output_type=_ConsolidationResult, system_prompt=_SYSTEM
        )
        result = await agent.run(f"Conversation:\n\n{transcript}")
        candidates = result.output.memories
    except Exception:
        return []

    saved: list[str] = []
    today = date.today().isoformat()
    for m in candidates[:_MAX_MEMORIES]:
        entry = MemoryEntry(
            name=m.name,
            description=m.description,
            type=m.type,
            content=m.content,
            created=today,
            confidence=m.confidence,
            source="consolidator",
        )
        conflict = check_conflict(backend, base_dir, entry)
        existing_conf = conflict["existing_confidence"] if conflict else None
        if (
            conflict
            and isinstance(existing_conf, (int, float))
            and existing_conf >= entry.confidence
        ):
            continue
        try:
            save_memory(backend, base_dir, entry, scope=scope)
        except OSError:  # pragma: no cover - defensive
            continue
        saved.append(entry.name)
    return saved
