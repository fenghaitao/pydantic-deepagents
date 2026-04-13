"""Local Logfire tracing — writes spans to .pydantic-deep/sessions/<id>/traces.jsonl when no token."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExportResult

# Maps trace_id (hex) → destination Path for that session
_trace_id_to_path: dict[str, Path] = {}

# Registry of open root spans keyed by session_id
_root_spans: dict[str, tuple] = {}


def _span_to_dict(span: "ReadableSpan") -> dict:
    """Serialize a ReadableSpan to a plain dict suitable for JSONL."""
    return {
        "name": span.name,
        "trace_id": format(span.context.trace_id, "032x") if span.context else None,
        "span_id": format(span.context.span_id, "016x") if span.context else None,
        "parent_span_id": (
            format(span.parent.span_id, "016x") if span.parent else None
        ),
        "start_time": span.start_time,
        "end_time": span.end_time,
        "status": span.status.status_code.name if span.status else None,
        "attributes": dict(span.attributes) if span.attributes else {},
        "events": [
            {
                "name": e.name,
                "timestamp": e.timestamp,
                "attributes": dict(e.attributes) if e.attributes else {},
            }
            for e in (span.events or [])
        ],
    }


class SessionFileExporter:
    """OTEL SpanExporter that writes spans as JSONL into the session directory."""

    def export(self, spans: "Sequence[ReadableSpan]") -> "SpanExportResult":
        from opentelemetry.sdk.trace.export import SpanExportResult

        try:
            for span in spans:
                trace_id_hex = (
                    format(span.context.trace_id, "032x") if span.context else None
                )
                dest = _trace_id_to_path.get(trace_id_hex) if trace_id_hex else None
                if dest is None:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                record = _span_to_dict(span)
                with open(dest, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"SessionFileExporter failed: {e}")
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def start_session_span(session_id: str, session_dir: Path) -> None:
    """Open a root OTEL span for the session so all child spans are nested under it.

    Args:
        session_id: Unique session identifier.
        session_dir: The session directory (e.g. .pydantic-deep/sessions/<id>/).
            traces.jsonl will be written there.
    """
    if session_id in _root_spans:
        return
    from opentelemetry import trace as otel_trace
    from opentelemetry.context import attach

    dest = session_dir / "traces.jsonl"
    tracer = otel_trace.get_tracer("pydantic-deep.session")
    span = tracer.start_span(f"session:{session_id}")
    span.set_attribute("session_id", session_id)
    sc = span.get_span_context()
    if sc:
        _trace_id_to_path[format(sc.trace_id, "032x")] = dest
    ctx = otel_trace.set_span_in_context(span)
    token = attach(ctx)
    _root_spans[session_id] = (span, token, dest)


def end_session_span(session_id: str) -> None:
    """End and flush the root span for a session."""
    entry = _root_spans.pop(session_id, None)
    if not entry:
        return
    span, token, dest = entry
    sc = span.get_span_context()
    if sc:
        _trace_id_to_path.pop(format(sc.trace_id, "032x"), None)
    span.end()
    from opentelemetry.context import detach
    detach(token)


def notify_session_start(session_id: str, session_dir: Path) -> None:
    """Start a session span and print the trace path if no token is set.

    Call this once per session after the session_id is resolved.
    """
    import os
    import sys

    start_session_span(session_id, session_dir)
    if not os.environ.get("LOGFIRE_TOKEN"):
        print(
            f"No LOGFIRE_TOKEN — traces will be written to {session_dir}/traces.jsonl",
            file=sys.stderr,
        )
