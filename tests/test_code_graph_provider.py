"""Tests for pydantic_deep.code_graph_provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydantic_deep.providers.code_graph import CGCProvider, CodeGraphProvider, make_provider


# ── CGCProvider ───────────────────────────────────────────────────────────────


class TestCGCProvider:
    def _make_runtime(self) -> MagicMock:
        rt = MagicMock()
        rt.list_repositories = AsyncMock(
            return_value={
                "repositories": [
                    {"path": "/repo/a", "name": "project-a"},
                    {"path": "/repo/b", "name": "project-b"},
                ]
            }
        )
        rt.delete_repository = AsyncMock(return_value={"deleted": True})
        return rt

    async def test_list_projects_maps_repos(self) -> None:
        rt = self._make_runtime()
        provider = CGCProvider(rt)
        projects = await provider.list_projects()
        assert len(projects) == 2
        assert projects[0] == {
            "id": "/repo/a",
            "repo_name": "project-a",
            "branch_name": "",
            "status": "ready",
        }
        assert projects[1] == {
            "id": "/repo/b",
            "repo_name": "project-b",
            "branch_name": "",
            "status": "ready",
        }

    async def test_list_projects_empty(self) -> None:
        rt = MagicMock()
        rt.list_repositories = AsyncMock(return_value={"repositories": []})
        provider = CGCProvider(rt)
        assert await provider.list_projects() == []

    async def test_list_projects_missing_repositories_key(self) -> None:
        rt = MagicMock()
        rt.list_repositories = AsyncMock(return_value={})
        provider = CGCProvider(rt)
        assert await provider.list_projects() == []

    async def test_list_projects_repo_with_only_path(self) -> None:
        rt = MagicMock()
        rt.list_repositories = AsyncMock(
            return_value={"repositories": [{"path": "/some/repo"}]}
        )
        provider = CGCProvider(rt)
        projects = await provider.list_projects()
        assert projects[0]["id"] == "/some/repo"
        assert projects[0]["repo_name"] == "/some/repo"  # falls back to path

    async def test_list_projects_repo_with_only_name(self) -> None:
        rt = MagicMock()
        rt.list_repositories = AsyncMock(
            return_value={"repositories": [{"name": "myrepo"}]}
        )
        provider = CGCProvider(rt)
        projects = await provider.list_projects()
        assert projects[0]["id"] == "myrepo"
        assert projects[0]["repo_name"] == "myrepo"

    async def test_delete_project_delegates(self) -> None:
        rt = self._make_runtime()
        provider = CGCProvider(rt)
        result = await provider.delete_project("/repo/a")
        rt.delete_repository.assert_awaited_once_with("/repo/a")
        assert result == {"deleted": True}

    async def test_delete_all_projects_deletes_each(self) -> None:
        rt = self._make_runtime()
        provider = CGCProvider(rt)
        result = await provider.delete_all_projects()
        assert result["deleted"] == 2
        assert "errors" not in result
        assert rt.delete_repository.await_count == 2

    async def test_delete_all_projects_empty(self) -> None:
        rt = MagicMock()
        rt.list_repositories = AsyncMock(return_value={"repositories": []})
        provider = CGCProvider(rt)
        result = await provider.delete_all_projects()
        assert result == {"deleted": 0}

    async def test_delete_all_projects_partial_failure(self) -> None:
        rt = MagicMock()
        rt.list_repositories = AsyncMock(
            return_value={"repositories": [{"path": "/a", "name": "a"}, {"path": "/b", "name": "b"}]}
        )
        rt.delete_repository = AsyncMock(side_effect=[Exception("boom"), None])
        provider = CGCProvider(rt)
        result = await provider.delete_all_projects()
        assert result["deleted"] == 1
        assert len(result["errors"]) == 1
        assert "/a" in result["errors"][0]

    def test_satisfies_protocol(self) -> None:
        rt = MagicMock()
        provider = CGCProvider(rt)
        assert isinstance(provider, CodeGraphProvider)


# ── make_provider ─────────────────────────────────────────────────────────────


class TestMakeProvider:
    def test_cgc_returns_cgc_provider(self) -> None:
        mock_rt = MagicMock()
        mock_cgc_mod = MagicMock()
        mock_cgc_mod.CGCRuntime = MagicMock(return_value=mock_rt)
        with patch.dict(
            "sys.modules",
            {
                "pydantic_deep.toolsets.code_graph.cgc": MagicMock(),
                "pydantic_deep.toolsets.code_graph.cgc.runtime": mock_cgc_mod,
            },
        ):
            provider = make_provider("cgc")
        assert isinstance(provider, CGCProvider)
        mock_cgc_mod.CGCRuntime.assert_called_once_with(repo_path=None)

    def test_cgc_passes_repo_path(self) -> None:
        mock_rt = MagicMock()
        mock_cgc_mod = MagicMock()
        mock_cgc_mod.CGCRuntime = MagicMock(return_value=mock_rt)
        with patch.dict(
            "sys.modules",
            {
                "pydantic_deep.toolsets.code_graph.cgc": MagicMock(),
                "pydantic_deep.toolsets.code_graph.cgc.runtime": mock_cgc_mod,
            },
        ):
            make_provider("cgc", repo_path="/my/repo")
        mock_cgc_mod.CGCRuntime.assert_called_once_with(repo_path="/my/repo")

    def test_potpie_returns_potpie_runtime(self) -> None:
        mock_rt = MagicMock()
        mock_potpie_mod = MagicMock()
        mock_potpie_mod.PotpieRuntime = MagicMock(return_value=mock_rt)
        with patch.dict(
            "sys.modules",
            {
                "pydantic_deep.toolsets.code_graph.potpie": MagicMock(),
                "pydantic_deep.toolsets.code_graph.potpie.runtime": mock_potpie_mod,
            },
        ):
            provider = make_provider("potpie")
        assert provider is mock_rt
        mock_potpie_mod.PotpieRuntime.assert_called_once_with(user_id=None)

    def test_potpie_passes_user_id(self) -> None:
        mock_rt = MagicMock()
        mock_potpie_mod = MagicMock()
        mock_potpie_mod.PotpieRuntime = MagicMock(return_value=mock_rt)
        with patch.dict(
            "sys.modules",
            {
                "pydantic_deep.toolsets.code_graph.potpie": MagicMock(),
                "pydantic_deep.toolsets.code_graph.potpie.runtime": mock_potpie_mod,
            },
        ):
            make_provider("potpie", user_id="myuser")
        mock_potpie_mod.PotpieRuntime.assert_called_once_with(user_id="myuser")

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown code-graph provider: 'foobar'"):
            make_provider("foobar")
