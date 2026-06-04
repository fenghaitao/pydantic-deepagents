"""System-prompt index injection, keyword+AI relevance, and index truncation."""

from __future__ import annotations

from .store import INDEX_FILENAME

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
