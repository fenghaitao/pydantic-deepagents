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
