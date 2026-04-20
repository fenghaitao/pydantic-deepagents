"""Tests for pydantic_deep.toolsets.code_graph.__init__ (factory functions)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic_deep.toolsets.code_graph import make_cgc_runtime, make_runtime
from pydantic_deep.toolsets.code_graph.cgc_runtime import CGCRuntime
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


class TestMakeCGCRuntime:
    def test_returns_cgc_runtime(self) -> None:
        with patch(
            "pydantic_deep.toolsets.code_graph.CGCRuntime"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(spec=CGCRuntime)
            runtime = make_cgc_runtime()
            mock_cls.assert_called_once()
            assert runtime is mock_cls.return_value

    def test_returns_cgc_runtime_instance(self) -> None:
        runtime = make_cgc_runtime()
        assert isinstance(runtime, CGCRuntime)

    def test_passes_repo_path(self) -> None:
        runtime = make_cgc_runtime(repo_path="/my/repo")
        assert runtime._repo_path == "/my/repo"  # pyright: ignore[reportPrivateUsage]
