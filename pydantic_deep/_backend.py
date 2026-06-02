"""Backend compatibility helpers."""

from __future__ import annotations

from typing import cast

from pydantic_ai_backends import BackendProtocol


def read_backend_bytes(backend: BackendProtocol, path: str) -> bytes:
    """Read bytes from a backend across backend API versions."""
    reader = getattr(backend, "read_bytes", None)
    if callable(reader):
        return cast(bytes, reader(path))

    legacy_reader = getattr(backend, "_read_bytes", None)
    if callable(legacy_reader):
        return cast(bytes, legacy_reader(path))

    msg = f"{type(backend).__name__} does not support reading bytes"
    raise AttributeError(msg)
