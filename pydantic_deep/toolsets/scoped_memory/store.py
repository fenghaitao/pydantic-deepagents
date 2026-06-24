"""Backend-backed file-per-memory storage.

All operations take an explicit ``backend`` and ``base_dir`` so the same code
serves both the user scope (a dedicated LocalBackend) and the project scope
(the run's backend). ``base_dir`` is the directory that holds the per-memory
``<slug>.md`` files and the auto-built ``MEMORY.md`` index.
"""

from __future__ import annotations

import os
import re
from datetime import date as _date

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
        entries.append(
            MemoryEntry(
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
            )
        )
    entries.sort(key=lambda e: e.name)
    return entries


def _rewrite_index(backend: BackendProtocol, base_dir: str, scope: str) -> None:
    entries = load_entries(backend, base_dir, scope=scope)
    lines = [f"- [{e.name}]({e.file_path.rsplit('/', 1)[-1]}) — {e.description}" for e in entries]
    body = "\n".join(lines) + ("\n" if lines else "")
    _write_or_raise(backend, _index_path(base_dir), body)


def save_memory(
    backend: BackendProtocol, base_dir: str, entry: MemoryEntry, scope: str = "user"
) -> None:
    """Write/overwrite a memory file (by slug) and rebuild the scope index."""
    slug = _slugify(entry.name)
    path = _file_path(base_dir, slug)
    _write_or_raise(backend, path, _format_entry_md(entry))
    entry.file_path = path
    entry.scope = scope
    _rewrite_index(backend, base_dir, scope)


def _delete_backend_file(backend: BackendProtocol, path: str) -> None:
    """Delete a single file across backend implementations.

    BackendProtocol has no delete method, so handle the shipped backends:
    real-filesystem backends (LocalBackend, exposing ``root_dir``) via os.remove;
    in-memory StateBackend via its live ``files`` dict (keys are normalized to a
    leading slash with no trailing slash — see StateBackend._normalize_path).
    """
    native = getattr(backend, "delete", None)
    if callable(native):  # pragma: no cover - no shipped backend has this yet
        native(path)
        return
    root = getattr(backend, "root_dir", None)
    if root is not None:
        real = os.path.join(str(root), path.lstrip("/"))
        if os.path.exists(real):  # pragma: no branch - guard against double-delete
            os.remove(real)
        return
    files = getattr(backend, "files", None)
    if isinstance(files, dict):
        norm = path if path.startswith("/") else "/" + path
        files.pop(norm, None)
        return
    backend.write(path, b"")  # pragma: no cover - unknown backend tombstone fallback


def delete_memory(backend: BackendProtocol, base_dir: str, name: str, scope: str = "user") -> None:
    """Delete the memory file matching name (no error if absent) and rebuild the index."""
    slug = _slugify(name)
    path = _file_path(base_dir, slug)
    if backend.exists(path):
        _delete_backend_file(backend, path)
    _rewrite_index(backend, base_dir, scope)


def get_index_content(backend: BackendProtocol, base_dir: str) -> str:
    """Raw MEMORY.md content for base_dir, or '' if absent."""
    path = _index_path(base_dir)
    if not backend.exists(path):
        return ""
    return read_backend_bytes(backend, path).decode("utf-8", errors="replace").strip()


def check_conflict(
    backend: BackendProtocol, base_dir: str, entry: MemoryEntry
) -> dict[str, object] | None:
    """Return existing-memory fields if a same-slug memory exists with a DIFFERENT body,
    else None (no file, or identical body)."""
    path = _file_path(base_dir, _slugify(entry.name))
    if not backend.exists(path):
        return None
    meta, existing = parse_frontmatter(
        read_backend_bytes(backend, path).decode("utf-8", errors="replace")
    )
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
    meta, body = parse_frontmatter(
        read_backend_bytes(backend, file_path).decode("utf-8", errors="replace")
    )
    if meta.get("last_used_at") == stamp:
        return
    meta["last_used_at"] = stamp
    fm = ["---"]
    for k in (
        "name",
        "description",
        "type",
        "created",
        "confidence",
        "source",
        "last_used_at",
        "conflict_group",
    ):
        v = meta.get(k)
        if v is not None and str(v):
            fm.append(f"{k}: {v}")
    fm.append("---")
    _write_or_raise(backend, file_path, "\n".join(fm) + "\n" + body + "\n")
