"""Tests for pydantic_deep.toolsets.code_graph.__init__ (make_runtime factory)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic_deep.toolsets.code_graph import make_runtime
from pydantic_deep.toolsets.code_graph.runtime import CodeGraphRuntime


class TestMakeBackend:
    def test_returns_runtime(self) -> None:
        with patch(
            "pydantic_deep.toolsets.code_graph.CodeGraphRuntime"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(spec=CodeGraphRuntime)
            backend = make_runtime()
            mock_cls.assert_called_once()
            assert backend is mock_cls.return_value

    def test_returns_runtime_instance(self) -> None:
        backend = make_runtime()
        assert isinstance(backend, CodeGraphRuntime)
