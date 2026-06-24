"""Scoped, typed agent memory on BackendProtocol."""

from __future__ import annotations

from .toolset import ScopedMemoryToolset, default_user_backend
from .types import (
    MEMORY_FORMAT_EXAMPLE,
    MEMORY_SYSTEM_PROMPT,
    MEMORY_TYPE_DESCRIPTIONS,
    MEMORY_TYPES,
    WHAT_NOT_TO_SAVE,
    MemoryEntry,
)

__all__ = [
    "MemoryEntry",
    "MEMORY_TYPES",
    "MEMORY_TYPE_DESCRIPTIONS",
    "MEMORY_SYSTEM_PROMPT",
    "WHAT_NOT_TO_SAVE",
    "MEMORY_FORMAT_EXAMPLE",
    "ScopedMemoryToolset",
    "default_user_backend",
]
