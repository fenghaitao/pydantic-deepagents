"""Upload local traces.jsonl spans to a Phoenix (OTLP) server.

Builds the OTLP protobuf payload directly from the raw JSONL dicts so that
the original trace_id / span_id / parent_span_id values are preserved exactly.
This ensures Phoenix sees one trace with the correct span hierarchy instead of
N independent traces.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path


def upload_traces(traces_path: Path, phoenix_endpoint: str) -> int:
    """
    Read spans from *traces_path* (JSONL) and POST them to Phoenix via OTLP/HTTP.

    Returns the number of spans sent.
    """
    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
    from opentelemetry.proto.resource.v1.resource_pb2 import Resource
    from opentelemetry.proto.trace.v1.trace_pb2 import (
        ResourceSpans,
        ScopeSpans,
        Span,
        Status,
    )
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    if not traces_path.exists():
        raise FileNotFoundError(f"traces file not found: {traces_path}")

    spans_raw: list[dict] = []
    for line in traces_path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                spans_raw.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not spans_raw:
        return 0

    def _to_bytes(hex_str: str, length: int) -> bytes:
        return bytes.fromhex(hex_str.zfill(length * 2))

    def _any_value(v) -> AnyValue:
        if isinstance(v, bool):
            return AnyValue(bool_value=v)
        if isinstance(v, int):
            return AnyValue(int_value=v)
        if isinstance(v, float):
            return AnyValue(double_value=v)
        return AnyValue(string_value=str(v))

    def _kv(k: str, v) -> KeyValue:
        return KeyValue(key=k, value=_any_value(v))

    pb_spans: list[Span] = []
    for raw in spans_raw:
        try:
            trace_id = _to_bytes(raw["trace_id"], 16)
            span_id  = _to_bytes(raw["span_id"],  8)
            parent_id = (
                _to_bytes(raw["parent_span_id"], 8)
                if raw.get("parent_span_id") else b""
            )

            status_name = raw.get("status", "UNSET")
            if status_name == "ERROR":
                pb_status = Status(code=Status.STATUS_CODE_ERROR)
            elif status_name == "OK":
                pb_status = Status(code=Status.STATUS_CODE_OK)
            else:
                pb_status = Status(code=Status.STATUS_CODE_UNSET)

            attrs = [_kv(k, v) for k, v in (raw.get("attributes") or {}).items()]

            events = []
            for ev in raw.get("events") or []:
                ev_attrs = [_kv(k, v) for k, v in (ev.get("attributes") or {}).items()]
                events.append(Span.Event(
                    name=ev.get("name", ""),
                    time_unix_nano=ev.get("timestamp") or 0,
                    attributes=ev_attrs,
                ))

            pb_spans.append(Span(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_id,
                name=raw.get("name", "span"),
                start_time_unix_nano=raw.get("start_time") or 0,
                end_time_unix_nano=raw.get("end_time") or 0,
                attributes=attrs,
                events=events,
                status=pb_status,
            ))
        except Exception:
            pass

    if not pb_spans:
        return 0

    resource = Resource(attributes=[_kv("service.name", "pydantic-deep")])
    request = ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                resource=resource,
                scope_spans=[ScopeSpans(spans=pb_spans)],
            )
        ]
    )

    payload = request.SerializeToString()
    url = phoenix_endpoint.rstrip("/") + "/v1/traces"
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-protobuf"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"Phoenix returned HTTP {resp.status}")

    return len(pb_spans)
