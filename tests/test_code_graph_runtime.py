"""Tests for pydantic_deep.toolsets.code_graph.runtime.PotpieRuntime."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime


def _make_runtime() -> MagicMock:
    rt = AsyncMock()
    rt.db.get_session.return_value = MagicMock()
    rt.projects.list = AsyncMock(return_value=[])
    rt.projects.register = AsyncMock(return_value="proj-new")
    rt.projects.delete = AsyncMock()
    rt.parsing.parse_project = AsyncMock(
        return_value=MagicMock(success=True, error_message=None)
    )
    rt.parsing.get_status = AsyncMock(return_value=MagicMock(value="READY"))
    rt.agents.list_agents = MagicMock(return_value=[])
    rt.close = AsyncMock()
    return rt


def _potpie_modules(mock_rt: MagicMock) -> dict:
    """Return sys.modules patches for potpie and app sub-modules."""
    mock_potpie = MagicMock()
    mock_potpie.PotpieRuntime = MagicMock(from_env=MagicMock(return_value=mock_rt))
    return {"potpie": mock_potpie}


class TestPotpieRuntimeLifecycle:
    async def test_close_when_no_runtime(self) -> None:
        b = PotpieRuntime()
        await b.close()  # should not raise

    async def test_close_calls_runtime_close(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            await b._get_runtime()  # pyright: ignore[reportPrivateUsage]
        await b.close()
        mock_rt.close.assert_called_once()
        assert b._runtime is None  # pyright: ignore[reportPrivateUsage]

    async def test_context_manager(self) -> None:
        mock_rt = _make_runtime()
        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            async with PotpieRuntime() as b:
                # Trigger runtime initialization
                await b._get_runtime()  # pyright: ignore[reportPrivateUsage]
            mock_rt.close.assert_called_once()

    async def test_get_runtime_reuses_instance(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            rt1 = await b._get_runtime()  # pyright: ignore[reportPrivateUsage]
            rt2 = await b._get_runtime()  # pyright: ignore[reportPrivateUsage]
        assert rt1 is rt2

    def test_default_user_id(self) -> None:
        b = PotpieRuntime()
        assert b._user_id == "defaultuser"  # pyright: ignore[reportPrivateUsage]

    def test_custom_user_id(self) -> None:
        b = PotpieRuntime(user_id="alice")
        assert b._user_id == "alice"  # pyright: ignore[reportPrivateUsage]


class TestPotpieRuntimeTools:
    async def test_get_tools(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_svc = MagicMock()
        mock_svc.get_tools.return_value = ["tool_a"]
        mock_tool_svc = MagicMock(ToolService=MagicMock(return_value=mock_svc))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.tool_service": mock_tool_svc,
        }):
            result = await b.get_tools(["tool_a"])

        assert result == ["tool_a"]

    async def test_get_tools_exclude_embedding(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_svc = MagicMock()
        mock_svc.get_tools.return_value = []
        mock_tool_svc = MagicMock(ToolService=MagicMock(return_value=mock_svc))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.tool_service": mock_tool_svc,
        }):
            await b.get_tools(["tool_a"], exclude_embedding_tools=True)

        mock_svc.get_tools.assert_called_once_with(["tool_a"], exclude_embedding_tools=True)


class TestPotpieRuntimeProjects:
    async def test_list_projects(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        proj = MagicMock()
        proj.id = "p1"
        proj.repo_name = "myrepo"
        proj.branch_name = "main"
        proj.status.value = "READY"
        proj.repo_path = "/path/to/repo"
        mock_rt.projects.list = AsyncMock(return_value=[proj])

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            result = await b.list_projects()

        assert len(result) == 1
        assert result[0]["id"] == "p1"
        assert result[0]["repo_name"] == "myrepo"

    async def test_list_projects_no_repo_path(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        proj = MagicMock(spec=["id", "repo_name", "branch_name", "status"])
        proj.id = "p2"
        proj.repo_name = "repo2"
        proj.branch_name = "dev"
        proj.status.value = "READY"
        mock_rt.projects.list = AsyncMock(return_value=[proj])

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            result = await b.list_projects()

        assert result[0]["repo_path"] == ""

    async def test_delete_project(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            result = await b.delete_project("p1")

        assert result == {"deleted": "p1"}
        mock_rt.projects.delete.assert_called_once_with("p1")

    async def test_delete_all_projects(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        p1 = MagicMock(id="p1")
        p2 = MagicMock(id="p2")
        mock_rt.projects.list = AsyncMock(return_value=[p1, p2])

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            result = await b.delete_all_projects()

        assert result["deleted"] == 2

    async def test_delete_all_projects_with_error(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        p1 = MagicMock(id="p1")
        mock_rt.projects.list = AsyncMock(return_value=[p1])
        mock_rt.projects.delete = AsyncMock(side_effect=RuntimeError("oops"))

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            result = await b.delete_all_projects()

        assert result["deleted"] == 0
        assert "errors" in result


class TestPotpieRuntimeParsing:
    async def test_parsing_status(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            result = await b.parsing_status("p1")

        assert result == {"project_id": "p1", "status": "READY"}

    async def test_parse_success(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            result = await b.parse("/repo", "myrepo", "main")

        assert result["project_id"] == "proj-new"
        assert result["status"] == "READY"

    async def test_parse_failure(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_rt.parsing.parse_project = AsyncMock(
            return_value=MagicMock(success=False, error_message="failed")
        )

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            result = await b.parse(None, "myrepo", "main")

        assert result["status"] == "ERROR"
        assert result["message"] == "failed"

    async def test_parse_no_repo_path_or_name_raises(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            with pytest.raises(ValueError, match="repo_path or repo_name"):
                await b.parse(None, None, "main")

    async def test_parse_auto_detects_commit(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_repo = MagicMock()
        mock_repo.head.commit.hexsha = "abc123"
        mock_git = MagicMock()
        mock_git.Repo = MagicMock(return_value=mock_repo)

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "git": mock_git,
        }):
            result = await b.parse("/repo", None, "main")

        assert result["project_id"] == "proj-new"
        call_kwargs = mock_rt.projects.register.call_args[1]
        assert call_kwargs["commit_id"] == "abc123"


class TestPotpieRuntimeQuery:
    async def test_nl_query(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_tool = AsyncMock()
        mock_tool.arun = AsyncMock(return_value={"result": "ok"})
        mock_nl_mod = MagicMock(NLCypherQueryTool=MagicMock(return_value=mock_tool))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool": mock_nl_mod,
        }):
            result = await b.nl_query("p1", "what calls foo?")

        assert result == {"result": "ok"}

    async def test_kg_search_list(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_tool = AsyncMock()
        mock_tool.arun = AsyncMock(return_value=[{"node": "A"}])
        mock_kg_mod = MagicMock(KnowledgeGraphQueryTool=MagicMock(return_value=mock_tool))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.kg_based_tools.ask_knowledge_graph_queries_tool": mock_kg_mod,
        }):
            result = await b.kg_search("p1", ["find auth"])

        assert result == [{"node": "A"}]

    async def test_kg_search_dict(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_tool = AsyncMock()
        mock_tool.arun = AsyncMock(return_value={"a": 1, "b": 2})
        mock_kg_mod = MagicMock(KnowledgeGraphQueryTool=MagicMock(return_value=mock_tool))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.kg_based_tools.ask_knowledge_graph_queries_tool": mock_kg_mod,
        }):
            result = await b.kg_search("p1", ["find auth"])

        assert isinstance(result, list)

    async def test_search(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_svc = AsyncMock()
        mock_svc.search_codebase = AsyncMock(return_value=[{"file": "foo.py"}])
        mock_search_mod = MagicMock(SearchService=MagicMock(return_value=mock_svc))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.search.search_service": mock_search_mod,
        }):
            result = await b.search("p1", "foo")

        assert result == [{"file": "foo.py"}]

    async def test_search_non_list_returns_empty(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_svc = AsyncMock()
        mock_svc.search_codebase = AsyncMock(return_value=None)
        mock_search_mod = MagicMock(SearchService=MagicMock(return_value=mock_svc))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.search.search_service": mock_search_mod,
        }):
            result = await b.search("p1", "foo")

        assert result == []


class TestPotpieRuntimeAgents:
    async def test_list_agents(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        agent = MagicMock()
        agent.id = "a1"
        agent.name = "QnA"
        agent.description = "Answers questions"
        mock_rt.agents.list_agents = MagicMock(return_value=[agent])

        with patch.dict("sys.modules", _potpie_modules(mock_rt)):
            result = await b.list_agents()

        assert result[0]["id"] == "a1"
        assert result[0]["name"] == "QnA"
        assert result[0]["description"] == "Answers questions"


class TestPotpieRuntimeCache:
    async def test_cache_stats(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_inference_svc = MagicMock()
        mock_inference_svc.get_cache_stats.return_value = {"entries": 10}
        mock_cleanup_svc = MagicMock()
        mock_cleanup_svc.get_cleanup_stats.return_value = {"expired": 2}

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.parsing.services.inference_cache_service": MagicMock(
                InferenceCacheService=MagicMock(return_value=mock_inference_svc)
            ),
            "app.modules.parsing.services.cache_cleanup_service": MagicMock(
                CacheCleanupService=MagicMock(return_value=mock_cleanup_svc)
            ),
        }):
            result = await b.cache_stats("p1")

        assert result == {"entries": 10, "expired": 2}

    async def test_cache_clean_all(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_svc = MagicMock()
        mock_svc.clear_all_entries.return_value = 5

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.parsing.services.cache_cleanup_service": MagicMock(
                CacheCleanupService=MagicMock(return_value=mock_svc)
            ),
        }):
            result = await b.cache_clean(all=True)

        assert result == {"all": 5}

    async def test_cache_clean_project(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_svc = MagicMock()
        mock_svc.clear_entries_for_project.return_value = 3

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.parsing.services.cache_cleanup_service": MagicMock(
                CacheCleanupService=MagicMock(return_value=mock_svc)
            ),
        }):
            result = await b.cache_clean(project_id="p1")

        assert result == {"project": 3}

    async def test_cache_clean_expired(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_svc = MagicMock()
        mock_svc.cleanup_expired_entries.return_value = 7

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.parsing.services.cache_cleanup_service": MagicMock(
                CacheCleanupService=MagicMock(return_value=mock_svc)
            ),
        }):
            result = await b.cache_clean(expired=True)

        assert result == {"expired": 7}

    async def test_cache_clean_trim(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_svc = MagicMock()
        mock_svc.cleanup_least_accessed.return_value = 4

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.parsing.services.cache_cleanup_service": MagicMock(
                CacheCleanupService=MagicMock(return_value=mock_svc)
            ),
        }):
            result = await b.cache_clean(trim=True)

        assert result == {"trimmed": 4}

    async def test_cache_clean_trim_none_result(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_svc = MagicMock()
        mock_svc.cleanup_least_accessed.return_value = None

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.parsing.services.cache_cleanup_service": MagicMock(
                CacheCleanupService=MagicMock(return_value=mock_svc)
            ),
        }):
            result = await b.cache_clean(trim=True)

        assert result == {"trimmed": 0}


class TestPotpieRuntimeSimicsTools:
    async def test_analyze_register_side_effect(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        expected = {"device_name": "my_dev", "done": 3, "total_registers": 3}
        mock_tool = AsyncMock()
        mock_tool.arun = AsyncMock(return_value=expected)
        mock_mod = MagicMock(AnalyzeRegisterSideEffectTool=MagicMock(return_value=mock_tool))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.simics_device_tools.analyze_register_side_effect_tool": mock_mod,
        }):
            result = await b.analyze_register_side_effect(
                project_id="p1",
                device_name="my_dev",
            )

        assert result == expected
        mock_tool.arun.assert_called_once_with(
            project_id="p1",
            device_name="my_dev",
            refresh=False,
            batch_size=30,
            chunk_tokens=15000,
        )

    async def test_analyze_register_side_effect_with_options(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_tool = AsyncMock()
        mock_tool.arun = AsyncMock(return_value={"done": 0})
        mock_mod = MagicMock(AnalyzeRegisterSideEffectTool=MagicMock(return_value=mock_tool))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.simics_device_tools.analyze_register_side_effect_tool": mock_mod,
        }):
            await b.analyze_register_side_effect(
                project_id="p1",
                device_name="my_dev",
                refresh=True,
                batch_size=10,
                chunk_tokens=5000,
            )

        mock_tool.arun.assert_called_once_with(
            project_id="p1",
            device_name="my_dev",
            refresh=True,
            batch_size=10,
            chunk_tokens=5000,
        )

    async def test_analyze_capability(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        expected = {"device_name": "my_dev", "capabilities": [], "cached": False}
        mock_tool = AsyncMock()
        mock_tool.arun = AsyncMock(return_value=expected)
        mock_mod = MagicMock(AnalyzeCapabilityTool=MagicMock(return_value=mock_tool))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.simics_device_tools.analyze_capability_tool": mock_mod,
        }):
            result = await b.analyze_capability(
                project_id="p1",
                device_name="my_dev",
            )

        assert result == expected
        mock_tool.arun.assert_called_once_with(
            project_id="p1",
            device_name="my_dev",
            refresh=False,
            chunk_tokens=15000,
        )

    async def test_analyze_capability_with_refresh(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        mock_tool = AsyncMock()
        mock_tool.arun = AsyncMock(return_value={"capabilities": []})
        mock_mod = MagicMock(AnalyzeCapabilityTool=MagicMock(return_value=mock_tool))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.simics_device_tools.analyze_capability_tool": mock_mod,
        }):
            await b.analyze_capability(
                project_id="p1",
                device_name="my_dev",
                refresh=True,
                chunk_tokens=8000,
            )

        mock_tool.arun.assert_called_once_with(
            project_id="p1",
            device_name="my_dev",
            refresh=True,
            chunk_tokens=8000,
        )

    async def test_list_capability(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        expected = {
            "device_name": "my_dev",
            "cached": True,
            "capabilities": {"DMA": {"overview": "DMA engine"}},
        }
        mock_tool = AsyncMock()
        mock_tool.arun = AsyncMock(return_value=expected)
        mock_mod = MagicMock(ListCapabilityTool=MagicMock(return_value=mock_tool))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.simics_device_tools.list_capability_tool": mock_mod,
        }):
            result = await b.list_capability(project_id="p1", device_name="my_dev")

        assert result == expected
        mock_tool.arun.assert_called_once_with(project_id="p1", device_name="my_dev")

    async def test_list_register_side_effect(self) -> None:
        b = PotpieRuntime()
        mock_rt = _make_runtime()
        expected = {
            "device_name": "my_dev",
            "banks": {"bank0": {"REG_A": {"write_side_effect": "sets flag"}}},
            "summary": {"total_banks": 1, "total_registers": 1, "total_done": 1},
        }
        mock_tool = AsyncMock()
        mock_tool.arun = AsyncMock(return_value=expected)
        mock_mod = MagicMock(ListRegisterSideEffectTool=MagicMock(return_value=mock_tool))

        with patch.dict("sys.modules", {
            **_potpie_modules(mock_rt),
            "app.modules.intelligence.tools.simics_device_tools.list_register_side_effect_tool": mock_mod,
        }):
            result = await b.list_register_side_effect(project_id="p1", device_name="my_dev")

        assert result == expected
        mock_tool.arun.assert_called_once_with(project_id="p1", device_name="my_dev")
