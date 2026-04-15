"""Tests for traces_upload module and the 'traces upload' CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from apps.cli.main import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SPAN = {
    "name": "agent run",
    "trace_id": "019d8a3f80f6203a2c4b4a9b3c119b42",
    "span_id": "3ccdcfc0fea35f3c",
    "parent_span_id": None,
    "start_time": 1776140920000000000,
    "end_time": 1776140926000000000,
    "status": "UNSET",
    "attributes": {"gen_ai.operation.name": "chat"},
    "events": [],
}

_CHILD_SPAN = {
    "name": "chat gpt-4o",
    "trace_id": "019d8a3f80f6203a2c4b4a9b3c119b42",
    "span_id": "2d3b7abc118c1875",
    "parent_span_id": "3ccdcfc0fea35f3c",
    "start_time": 1776140921000000000,
    "end_time": 1776140925000000000,
    "status": "OK",
    "attributes": {"gen_ai.request.model": "gpt-4o"},
    "events": [{"name": "my_event", "timestamp": 1776140922000000000, "attributes": {"k": "v"}}],
}


def _write_traces(path: Path, spans: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(s) for s in spans))


# ---------------------------------------------------------------------------
# Unit tests for upload_traces()
# ---------------------------------------------------------------------------


class TestUploadTraces:
    def test_raises_when_file_missing(self, tmp_path: Path) -> None:
        from apps.cli.traces_upload import upload_traces

        with pytest.raises(FileNotFoundError):
            upload_traces(tmp_path / "nonexistent.jsonl", "http://localhost:6006")

    def test_returns_zero_for_empty_file(self, tmp_path: Path) -> None:
        from apps.cli.traces_upload import upload_traces

        traces = tmp_path / "traces.jsonl"
        traces.write_text("")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            count = upload_traces(traces, "http://localhost:6006")

        assert count == 0
        mock_urlopen.assert_not_called()

    def test_uploads_spans_and_returns_count(self, tmp_path: Path) -> None:
        from apps.cli.traces_upload import upload_traces

        traces = tmp_path / "traces.jsonl"
        _write_traces(traces, [_SPAN, _CHILD_SPAN])

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            count = upload_traces(traces, "http://localhost:6006")

        assert count == 2
        mock_urlopen.assert_called_once()
        # Verify it POSTed to /v1/traces
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://localhost:6006/v1/traces"
        assert req.get_header("Content-type") == "application/x-protobuf"

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        from apps.cli.traces_upload import upload_traces

        traces = tmp_path / "traces.jsonl"
        traces.write_text(json.dumps(_SPAN) + "\nnot-json\n" + json.dumps(_CHILD_SPAN))

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            count = upload_traces(traces, "http://localhost:6006")

        assert count == 2  # malformed line skipped, 2 valid spans sent

    def test_preserves_trace_id_in_payload(self, tmp_path: Path) -> None:
        from apps.cli.traces_upload import upload_traces
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        traces = tmp_path / "traces.jsonl"
        _write_traces(traces, [_SPAN])

        captured_payload = []

        def fake_urlopen(req, timeout=None):
            captured_payload.append(req.data)
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            upload_traces(traces, "http://localhost:6006")

        assert captured_payload
        pb = ExportTraceServiceRequest()
        pb.ParseFromString(captured_payload[0])
        span = pb.resource_spans[0].scope_spans[0].spans[0]
        assert span.trace_id == bytes.fromhex(_SPAN["trace_id"])
        assert span.span_id == bytes.fromhex(_SPAN["span_id"])
        assert span.parent_span_id == b""  # root span has no parent

    def test_child_span_parent_id_preserved(self, tmp_path: Path) -> None:
        from apps.cli.traces_upload import upload_traces
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        traces = tmp_path / "traces.jsonl"
        _write_traces(traces, [_CHILD_SPAN])

        captured_payload = []

        def fake_urlopen(req, timeout=None):
            captured_payload.append(req.data)
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            upload_traces(traces, "http://localhost:6006")

        pb = ExportTraceServiceRequest()
        pb.ParseFromString(captured_payload[0])
        span = pb.resource_spans[0].scope_spans[0].spans[0]
        assert span.parent_span_id == bytes.fromhex(_CHILD_SPAN["parent_span_id"])

    def test_error_status_mapped(self, tmp_path: Path) -> None:
        from apps.cli.traces_upload import upload_traces
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
        from opentelemetry.proto.trace.v1.trace_pb2 import Status

        error_span = {**_SPAN, "status": "ERROR"}
        traces = tmp_path / "traces.jsonl"
        _write_traces(traces, [error_span])

        captured_payload = []

        def fake_urlopen(req, timeout=None):
            captured_payload.append(req.data)
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            upload_traces(traces, "http://localhost:6006")

        pb = ExportTraceServiceRequest()
        pb.ParseFromString(captured_payload[0])
        span = pb.resource_spans[0].scope_spans[0].spans[0]
        assert span.status.code == Status.STATUS_CODE_ERROR


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


class TestTracesUploadCommand:
    def test_upload_command_success(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "abc123"
        session_dir.mkdir()
        _write_traces(session_dir / "traces.jsonl", [_SPAN])

        with patch("apps.cli.traces_upload.upload_traces", return_value=1) as mock_upload:
            result = runner.invoke(
                app,
                ["traces", "upload", "abc123", "--dir", str(tmp_path)],
                env={"PHOENIX_PORT": "6006"},
            )

        assert result.exit_code == 0
        assert "Uploaded 1 span(s)" in result.output
        mock_upload.assert_called_once()

    def test_upload_command_uses_phoenix_port_env(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "abc123"
        session_dir.mkdir()
        _write_traces(session_dir / "traces.jsonl", [_SPAN])

        with patch("apps.cli.traces_upload.upload_traces", return_value=1) as mock_upload:
            runner.invoke(
                app,
                ["traces", "upload", "abc123", "--dir", str(tmp_path)],
                env={"PHOENIX_PORT": "59257"},
            )

        _, call_kwargs = mock_upload.call_args
        endpoint = mock_upload.call_args[0][1]
        assert "59257" in endpoint

    def test_upload_command_explicit_port_overrides_env(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "abc123"
        session_dir.mkdir()
        _write_traces(session_dir / "traces.jsonl", [_SPAN])

        with patch("apps.cli.traces_upload.upload_traces", return_value=1) as mock_upload:
            runner.invoke(
                app,
                ["traces", "upload", "abc123", "--dir", str(tmp_path), "--phoenix-port", "9999"],
                env={"PHOENIX_PORT": "6006"},
            )

        endpoint = mock_upload.call_args[0][1]
        assert "9999" in endpoint

    def test_upload_command_session_not_found(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["traces", "upload", "nonexistent", "--dir", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_upload_command_prefix_matching(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "abcdef123456"
        session_dir.mkdir()
        _write_traces(session_dir / "traces.jsonl", [_SPAN])

        with patch("apps.cli.traces_upload.upload_traces", return_value=1):
            result = runner.invoke(
                app,
                ["traces", "upload", "abcdef", "--dir", str(tmp_path)],
                env={"PHOENIX_PORT": "6006"},
            )

        assert result.exit_code == 0
