"""Tests for pydantic_deep.toolsets.code_graph.rest_backend.RestBackend."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydantic_deep.toolsets.code_graph.rest_backend import RestBackend


def _backend(url: str = "http://localhost:8001", key: str = "k") -> RestBackend:
    return RestBackend(base_url=url, api_key=key)


class TestRestBackendInit:
    def test_strips_trailing_slash(self) -> None:
        b = RestBackend(base_url="http://localhost:8001/", api_key="k")
        assert b._base_url == "http://localhost:8001"  # pyright: ignore[reportPrivateUsage]

    def test_headers_include_api_key(self) -> None:
        b = _backend(key="mykey")
        h = b._headers()  # pyright: ignore[reportPrivateUsage]
        assert h["X-API-Key"] == "mykey"
        assert h["Content-Type"] == "application/json"


class TestGetToolsNotImplemented:
    async def test_raises_not_implemented(self) -> None:
        b = _backend()
        with pytest.raises(NotImplementedError, match="REST mode"):
            await b.get_tools(["some_tool"])


class TestRestBackendHttp:
    def _mock_client(self, json_data: object, status: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get = AsyncMock(return_value=resp)
        client.post = AsyncMock(return_value=resp)
        client.delete = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        return client

    async def test_nl_query(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"result": "ok"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.nl_query("proj-1", "what calls foo?")
        assert result == {"result": "ok"}
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "nl-query" in call_args[0][0]

    async def test_kg_search_list_result(self) -> None:
        b = _backend()
        mock_client = self._mock_client([{"node": "A"}])
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.kg_search("proj-1", ["find auth"])
        assert result == [{"node": "A"}]

    async def test_kg_search_dict_result(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"results": [{"node": "B"}]})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.kg_search("proj-1", ["find auth"])
        assert result == [{"node": "B"}]

    async def test_search_list_result(self) -> None:
        b = _backend()
        mock_client = self._mock_client([{"file": "foo.py"}])
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.search("proj-1", "foo")
        assert result == [{"file": "foo.py"}]

    async def test_search_dict_result(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"results": [{"file": "bar.py"}]})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.search("proj-1", "bar")
        assert result == [{"file": "bar.py"}]

    async def test_parse(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"project_id": "p1", "status": "READY"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.parse("/repo", "myrepo", "main", "abc123")
        assert result["project_id"] == "p1"

    async def test_parse_minimal(self) -> None:
        """Parse with no optional fields — covers the None branches."""
        b = _backend()
        mock_client = self._mock_client({"project_id": "p1", "status": "READY"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.parse(None, None, "main")
        body = mock_client.post.call_args[1]["json"]
        assert "repo_path" not in body
        assert "repo_name" not in body
        assert "commit_id" not in body

    async def test_parsing_status(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"status": "READY"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.parsing_status("proj-1")
        assert result == {"status": "READY"}

    async def test_list_projects_list(self) -> None:
        b = _backend()
        mock_client = self._mock_client([{"id": "p1"}])
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.list_projects()
        assert result == [{"id": "p1"}]

    async def test_list_projects_dict(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"projects": [{"id": "p2"}]})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.list_projects()
        assert result == [{"id": "p2"}]

    async def test_delete_project(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"deleted": "p1"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.delete_project("p1")
        assert result == {"deleted": "p1"}
        mock_client.delete.assert_called_once()

    async def test_delete_all_projects(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"deleted": 5})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.delete_all_projects()
        assert result == {"deleted": 5}

    async def test_list_agents_list(self) -> None:
        b = _backend()
        mock_client = self._mock_client([{"id": "a1", "name": "QnA"}])
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.list_agents()
        assert result == [{"id": "a1", "name": "QnA"}]

    async def test_list_agents_dict(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"agents": [{"id": "a2"}]})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.list_agents()
        assert result == [{"id": "a2"}]

    async def test_cache_stats_no_project(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"entries": 10})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.cache_stats()
        assert result == {"entries": 10}

    async def test_cache_stats_with_project(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"entries": 5})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.cache_stats(project_id="p1")
        assert result == {"entries": 5}

    async def test_cache_clean(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"removed": 3})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.cache_clean(all=True)
        assert result == {"removed": 3}

    async def test_cache_clean_with_project_id(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"removed": 1})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.cache_clean(project_id="p1", expired=True)
        assert result == {"removed": 1}
        call_kwargs = mock_client.delete.call_args[1]
        assert call_kwargs["params"]["project_id"] == "p1"

    async def test_parse_with_all_optional_fields(self) -> None:
        b = _backend()
        mock_client = self._mock_client({"project_id": "p1", "status": "READY"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await b.parse("/repo", "myrepo", "main", "abc123")
        body = mock_client.post.call_args[1]["json"]
        assert body["repo_path"] == "/repo"
        assert body["repo_name"] == "myrepo"
        assert body["commit_id"] == "abc123"
