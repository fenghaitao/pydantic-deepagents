"""Tests for pydantic_deep.toolsets.code_graph.cgc_runtime.CGCRuntime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydantic_deep.toolsets.code_graph.cgc_runtime import CGCRuntime


def _make_server() -> MagicMock:
    """Return a mock MCPServer with all tool methods as MagicMock."""
    server = MagicMock()
    server.find_code_tool = MagicMock(return_value={"results": []})
    server.analyze_code_relationships_tool = MagicMock(return_value={"results": []})
    server.execute_cypher_query_tool = MagicMock(return_value={"results": []})
    server.list_indexed_repositories_tool = MagicMock(return_value={"repositories": []})
    server.add_code_to_graph_tool = MagicMock(return_value={"job_id": "j1"})
    server.check_job_status_tool = MagicMock(return_value={"status": "DONE"})
    server.delete_repository_tool = MagicMock(return_value={"deleted": True})
    server.get_repository_stats_tool = MagicMock(return_value={"files": 10})
    server.shutdown = MagicMock()
    return server


def _cgc_modules(mock_server: MagicMock) -> dict:
    """Return sys.modules patches for codegraphcontext."""
    mock_cgc = MagicMock()
    mock_cgc.server.MCPServer = MagicMock(return_value=mock_server)
    return {
        "codegraphcontext": mock_cgc,
        "codegraphcontext.server": mock_cgc.server,
    }


class TestCGCRuntimeLifecycle:
    async def test_close_when_no_server(self) -> None:
        r = CGCRuntime()
        r.close()  # should not raise

    async def test_close_calls_shutdown(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            r._get_server()  # pyright: ignore[reportPrivateUsage]
        r.close()
        mock_server.shutdown.assert_called_once()
        assert r._server is None  # pyright: ignore[reportPrivateUsage]

    async def test_context_manager(self) -> None:
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            async with CGCRuntime() as r:
                r._get_server()  # pyright: ignore[reportPrivateUsage]
            mock_server.shutdown.assert_called_once()

    async def test_get_server_reuses_instance(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            s1 = r._get_server()  # pyright: ignore[reportPrivateUsage]
            s2 = r._get_server()  # pyright: ignore[reportPrivateUsage]
        assert s1 is s2

    def test_default_repo_path_none(self) -> None:
        r = CGCRuntime()
        assert r._repo_path is None  # pyright: ignore[reportPrivateUsage]

    def test_custom_repo_path(self) -> None:
        r = CGCRuntime(repo_path="/my/repo")
        assert r._repo_path == "/my/repo"  # pyright: ignore[reportPrivateUsage]

    async def test_get_server_uses_repo_path(self) -> None:
        r = CGCRuntime(repo_path="/my/repo")
        mock_server = _make_server()
        modules = _cgc_modules(mock_server)
        with patch.dict("sys.modules", modules):
            r._get_server()  # pyright: ignore[reportPrivateUsage]
        modules["codegraphcontext.server"].MCPServer.assert_called_once_with(
            cwd=Path("/my/repo")
        )

    async def test_get_server_uses_cwd_when_no_repo_path(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        modules = _cgc_modules(mock_server)
        with patch("pathlib.Path.cwd", return_value=Path("/cwd")):
            with patch.dict("sys.modules", modules):
                r._get_server()  # pyright: ignore[reportPrivateUsage]
        modules["codegraphcontext.server"].MCPServer.assert_called_once_with(
            cwd=Path("/cwd")
        )


class TestCGCRuntimeSearch:
    async def test_find_code_basic(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        mock_server.find_code_tool = MagicMock(return_value={"results": [{"file": "foo.py"}]})
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            result = await r.find_code("foo")
        assert result == {"results": [{"file": "foo.py"}]}
        mock_server.find_code_tool.assert_called_once_with(query="foo")

    async def test_find_code_with_repo_path(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            await r.find_code("bar", repo_path="/my/repo")
        mock_server.find_code_tool.assert_called_once_with(query="bar", repo_path="/my/repo")

    async def test_find_code_with_fuzzy(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            await r.find_code("baz", fuzzy_search=True)
        mock_server.find_code_tool.assert_called_once_with(query="baz", fuzzy_search=True)

    async def test_find_code_repo_and_fuzzy(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            await r.find_code("x", repo_path="/r", fuzzy_search=True)
        mock_server.find_code_tool.assert_called_once_with(
            query="x", repo_path="/r", fuzzy_search=True
        )


class TestCGCRuntimeAnalyze:
    async def test_analyze_relationships_basic(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        mock_server.analyze_code_relationships_tool = MagicMock(
            return_value={"callers": ["f1"]}
        )
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            result = await r.analyze_relationships("find_callers", "my_func")
        assert result == {"callers": ["f1"]}
        mock_server.analyze_code_relationships_tool.assert_called_once_with(
            query_type="find_callers", target="my_func"
        )

    async def test_analyze_relationships_with_context(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            await r.analyze_relationships("find_callers", "f", context="src/foo.py")
        mock_server.analyze_code_relationships_tool.assert_called_once_with(
            query_type="find_callers", target="f", context="src/foo.py"
        )

    async def test_analyze_relationships_with_repo_path(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            await r.analyze_relationships("find_callees", "g", repo_path="/repo")
        mock_server.analyze_code_relationships_tool.assert_called_once_with(
            query_type="find_callees", target="g", repo_path="/repo"
        )

    async def test_analyze_relationships_with_all_args(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            await r.analyze_relationships(
                "class_hierarchy", "MyClass", context="src/m.py", repo_path="/r"
            )
        mock_server.analyze_code_relationships_tool.assert_called_once_with(
            query_type="class_hierarchy",
            target="MyClass",
            context="src/m.py",
            repo_path="/r",
        )


class TestCGCRuntimeCypher:
    async def test_execute_cypher(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        mock_server.execute_cypher_query_tool = MagicMock(return_value={"results": [1, 2]})
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            result = await r.execute_cypher("MATCH (n) RETURN n LIMIT 5")
        assert result == {"results": [1, 2]}
        mock_server.execute_cypher_query_tool.assert_called_once_with(
            cypher_query="MATCH (n) RETURN n LIMIT 5"
        )


class TestCGCRuntimeRepositories:
    async def test_list_repositories(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        mock_server.list_indexed_repositories_tool = MagicMock(
            return_value={"repositories": [{"path": "/r"}]}
        )
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            result = await r.list_repositories()
        assert result == {"repositories": [{"path": "/r"}]}
        mock_server.list_indexed_repositories_tool.assert_called_once_with()

    async def test_add_code_to_graph_basic(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            result = await r.add_code_to_graph("/some/path")
        assert result == {"job_id": "j1"}
        mock_server.add_code_to_graph_tool.assert_called_once_with(
            path="/some/path", is_dependency=False
        )

    async def test_add_code_to_graph_as_dependency(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            await r.add_code_to_graph("/lib", is_dependency=True)
        mock_server.add_code_to_graph_tool.assert_called_once_with(
            path="/lib", is_dependency=True
        )

    async def test_check_job_status(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        mock_server.check_job_status_tool = MagicMock(return_value={"status": "RUNNING"})
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            result = await r.check_job_status("job-123")
        assert result == {"status": "RUNNING"}
        mock_server.check_job_status_tool.assert_called_once_with(job_id="job-123")

    async def test_delete_repository(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            result = await r.delete_repository("/old/repo")
        assert result == {"deleted": True}
        mock_server.delete_repository_tool.assert_called_once_with(repo_path="/old/repo")

    async def test_get_stats_without_repo_path(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        mock_server.get_repository_stats_tool = MagicMock(return_value={"files": 42})
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            result = await r.get_stats()
        assert result == {"files": 42}
        mock_server.get_repository_stats_tool.assert_called_once_with()

    async def test_get_stats_with_repo_path(self) -> None:
        r = CGCRuntime()
        mock_server = _make_server()
        with patch.dict("sys.modules", _cgc_modules(mock_server)):
            await r.get_stats(repo_path="/my/repo")
        mock_server.get_repository_stats_tool.assert_called_once_with(repo_path="/my/repo")
