"""Tests for pydantic_deep.toolsets.code_graph.cgc_runtime.CGCRuntime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pydantic_deep.toolsets.code_graph.cgc.runtime import CGCRuntime


# ── Test helpers ──────────────────────────────────────────────────────────────


def _inject_components(
    r: CGCRuntime,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Pre-inject mock components directly, bypassing _get_components() lazy init."""
    db_manager: MagicMock = MagicMock()
    code_finder: MagicMock = MagicMock()
    graph_builder: MagicMock = MagicMock()
    job_manager: MagicMock = MagicMock()
    r._db_manager = db_manager  # pyright: ignore[reportPrivateUsage]
    r._code_finder = code_finder  # pyright: ignore[reportPrivateUsage]
    r._graph_builder = graph_builder  # pyright: ignore[reportPrivateUsage]
    r._job_manager = job_manager  # pyright: ignore[reportPrivateUsage]
    r._loop = MagicMock(spec=asyncio.AbstractEventLoop)  # pyright: ignore[reportPrivateUsage]
    return db_manager, code_finder, graph_builder, job_manager


def _cgc_init_modules(
    ctx_database: str | None = None,
) -> tuple[dict, MagicMock, MagicMock]:
    """Return (sys.modules patch dict, mock_db_manager, mock_resolve_context).

    Patches all codegraphcontext submodules needed by _get_components().
    """
    mock_ctx = MagicMock()
    mock_ctx.database = ctx_database
    mock_ctx.db_path = "/tmp/cgc/db/falkordb"

    mock_db_manager = MagicMock()
    mock_resolve_context = MagicMock(return_value=mock_ctx)

    mock_config_mod = MagicMock()
    mock_config_mod.resolve_context = mock_resolve_context

    mock_core_mod = MagicMock()
    mock_core_mod.get_database_manager = MagicMock(return_value=mock_db_manager)

    mock_jobs_mod = MagicMock()
    mock_jobs_mod.JobManager = MagicMock(return_value=MagicMock())

    mock_cf_mod = MagicMock()
    mock_cf_mod.CodeFinder = MagicMock(return_value=MagicMock())

    mock_gb_mod = MagicMock()
    mock_gb_mod.GraphBuilder = MagicMock(return_value=MagicMock())

    modules = {
        "codegraphcontext": MagicMock(),
        "codegraphcontext.cli": MagicMock(),
        "codegraphcontext.cli.config_manager": mock_config_mod,
        "codegraphcontext.core": mock_core_mod,
        "codegraphcontext.core.jobs": mock_jobs_mod,
        "codegraphcontext.tools": MagicMock(),
        "codegraphcontext.tools.code_finder": mock_cf_mod,
        "codegraphcontext.tools.graph_builder": mock_gb_mod,
    }
    return modules, mock_db_manager, mock_resolve_context


def _cgc_handler_modules(
    analysis: MagicMock | None = None,
    query: MagicMock | None = None,
    management: MagicMock | None = None,
    indexing: MagicMock | None = None,
) -> dict:
    """Return sys.modules patches for codegraphcontext handler imports."""
    analysis = analysis or MagicMock()
    query = query or MagicMock()
    management = management or MagicMock()
    indexing = indexing or MagicMock()

    mock_handlers_pkg = MagicMock()
    mock_handlers_pkg.analysis_handlers = analysis
    mock_handlers_pkg.query_handlers = query
    mock_handlers_pkg.management_handlers = management
    mock_handlers_pkg.indexing_handlers = indexing

    return {
        "codegraphcontext.tools.handlers": mock_handlers_pkg,
        "codegraphcontext.tools.handlers.analysis_handlers": analysis,
        "codegraphcontext.tools.handlers.query_handlers": query,
        "codegraphcontext.tools.handlers.management_handlers": management,
        "codegraphcontext.tools.handlers.indexing_handlers": indexing,
    }


# ── Lifecycle ─────────────────────────────────────────────────────────────────


class TestCGCRuntimeLifecycle:
    def test_close_when_not_initialized(self) -> None:
        r = CGCRuntime()
        r.close()  # should not raise

    def test_default_repo_path_none(self) -> None:
        r = CGCRuntime()
        assert r._repo_path is None  # pyright: ignore[reportPrivateUsage]

    def test_custom_repo_path(self) -> None:
        r = CGCRuntime(repo_path="/my/repo")
        assert r._repo_path == "/my/repo"  # pyright: ignore[reportPrivateUsage]

    async def test_close_closes_db_manager(self) -> None:
        r = CGCRuntime()
        db_m, _, _, _ = _inject_components(r)
        r.close()
        db_m.close_driver.assert_called_once()

    async def test_close_nulls_components(self) -> None:
        r = CGCRuntime()
        _inject_components(r)
        r.close()
        assert r._db_manager is None  # pyright: ignore[reportPrivateUsage]
        assert r._code_finder is None  # pyright: ignore[reportPrivateUsage]
        assert r._graph_builder is None  # pyright: ignore[reportPrivateUsage]
        assert r._job_manager is None  # pyright: ignore[reportPrivateUsage]
        assert r._loop is None  # pyright: ignore[reportPrivateUsage]

    async def test_context_manager(self) -> None:
        r_ref: CGCRuntime | None = None
        db_m: MagicMock | None = None
        modules, _, _ = _cgc_init_modules()
        with patch.dict("sys.modules", modules):
            async with CGCRuntime() as r:
                r_ref = r
                db_m, _, _, _ = _inject_components(r)
        assert db_m is not None
        db_m.close_driver.assert_called_once()
        assert r_ref._db_manager is None  # pyright: ignore[reportPrivateUsage]

    async def test_get_components_reuses_instance(self) -> None:
        r = CGCRuntime()
        modules, _, _ = _cgc_init_modules()
        with patch.dict("sys.modules", modules):
            db1, cf1, gb1, jm1 = r._get_components()  # pyright: ignore[reportPrivateUsage]
            db2, cf2, gb2, jm2 = r._get_components()  # pyright: ignore[reportPrivateUsage]
        assert db1 is db2
        assert cf1 is cf2
        assert gb1 is gb2
        assert jm1 is jm2

    async def test_get_components_uses_repo_path(self) -> None:
        r = CGCRuntime(repo_path="/my/repo")
        modules, _, mock_resolve = _cgc_init_modules()
        with patch.dict("sys.modules", modules):
            r._get_components()  # pyright: ignore[reportPrivateUsage]
        mock_resolve.assert_called_once_with(cwd=Path("/my/repo"))

    async def test_get_components_uses_cwd_when_no_repo_path(self) -> None:
        r = CGCRuntime()
        modules, _, mock_resolve = _cgc_init_modules()
        with patch("pathlib.Path.cwd", return_value=Path("/cwd")):
            with patch.dict("sys.modules", modules):
                r._get_components()  # pyright: ignore[reportPrivateUsage]
        mock_resolve.assert_called_once_with(cwd=Path("/cwd"))

    async def test_get_components_sets_db_type_env(self) -> None:
        r = CGCRuntime()
        modules, _, _ = _cgc_init_modules(ctx_database="kuzudb")
        with patch.dict("sys.modules", modules):
            with patch.dict("os.environ", {}, clear=False) as env:
                r._get_components()  # pyright: ignore[reportPrivateUsage]
                assert env.get("CGC_RUNTIME_DB_TYPE") == "kuzudb"


# ── Search ────────────────────────────────────────────────────────────────────


class TestCGCRuntimeSearch:
    async def test_find_code_basic(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_analysis = MagicMock()
        mock_analysis.find_code.return_value = {"results": [{"file": "foo.py"}]}
        with patch.dict("sys.modules", _cgc_handler_modules(analysis=mock_analysis)):
            result = await r.find_code("foo")
        assert result == {"results": [{"file": "foo.py"}]}
        mock_analysis.find_code.assert_called_once_with(cf, query="foo")

    async def test_find_code_with_repo_path(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_analysis = MagicMock()
        with patch.dict("sys.modules", _cgc_handler_modules(analysis=mock_analysis)):
            await r.find_code("bar", repo_path="/my/repo")
        mock_analysis.find_code.assert_called_once_with(cf, query="bar", repo_path="/my/repo")

    async def test_find_code_with_fuzzy(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_analysis = MagicMock()
        with patch.dict("sys.modules", _cgc_handler_modules(analysis=mock_analysis)):
            await r.find_code("baz", fuzzy_search=True)
        mock_analysis.find_code.assert_called_once_with(cf, query="baz", fuzzy_search=True)

    async def test_find_code_repo_and_fuzzy(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_analysis = MagicMock()
        with patch.dict("sys.modules", _cgc_handler_modules(analysis=mock_analysis)):
            await r.find_code("x", repo_path="/r", fuzzy_search=True)
        mock_analysis.find_code.assert_called_once_with(
            cf, query="x", repo_path="/r", fuzzy_search=True
        )


# ── Analyze ───────────────────────────────────────────────────────────────────


class TestCGCRuntimeAnalyze:
    async def test_analyze_relationships_basic(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_analysis = MagicMock()
        mock_analysis.analyze_code_relationships.return_value = {"callers": ["f1"]}
        with patch.dict("sys.modules", _cgc_handler_modules(analysis=mock_analysis)):
            result = await r.analyze_relationships("find_callers", "my_func")
        assert result == {"callers": ["f1"]}
        mock_analysis.analyze_code_relationships.assert_called_once_with(
            cf, query_type="find_callers", target="my_func"
        )

    async def test_analyze_relationships_with_context(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_analysis = MagicMock()
        with patch.dict("sys.modules", _cgc_handler_modules(analysis=mock_analysis)):
            await r.analyze_relationships("find_callers", "f", context="src/foo.py")
        mock_analysis.analyze_code_relationships.assert_called_once_with(
            cf, query_type="find_callers", target="f", context="src/foo.py"
        )

    async def test_analyze_relationships_with_repo_path(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_analysis = MagicMock()
        with patch.dict("sys.modules", _cgc_handler_modules(analysis=mock_analysis)):
            await r.analyze_relationships("find_callees", "g", repo_path="/repo")
        mock_analysis.analyze_code_relationships.assert_called_once_with(
            cf, query_type="find_callees", target="g", repo_path="/repo"
        )

    async def test_analyze_relationships_with_all_args(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_analysis = MagicMock()
        with patch.dict("sys.modules", _cgc_handler_modules(analysis=mock_analysis)):
            await r.analyze_relationships(
                "class_hierarchy", "MyClass", context="src/m.py", repo_path="/r"
            )
        mock_analysis.analyze_code_relationships.assert_called_once_with(
            cf,
            query_type="class_hierarchy",
            target="MyClass",
            context="src/m.py",
            repo_path="/r",
        )


# ── Cypher ────────────────────────────────────────────────────────────────────


class TestCGCRuntimeCypher:
    async def test_execute_cypher(self) -> None:
        r = CGCRuntime()
        db_m, _, _, _ = _inject_components(r)
        mock_query = MagicMock()
        mock_query.execute_cypher_query.return_value = {"results": [1, 2]}
        with patch.dict("sys.modules", _cgc_handler_modules(query=mock_query)):
            result = await r.execute_cypher("MATCH (n) RETURN n LIMIT 5")
        assert result == {"results": [1, 2]}
        mock_query.execute_cypher_query.assert_called_once_with(
            db_m, cypher_query="MATCH (n) RETURN n LIMIT 5"
        )


# ── Repositories ──────────────────────────────────────────────────────────────


class TestCGCRuntimeRepositories:
    async def test_list_repositories(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_mgmt = MagicMock()
        mock_mgmt.list_indexed_repositories.return_value = {"repositories": [{"path": "/r"}]}
        with patch.dict("sys.modules", _cgc_handler_modules(management=mock_mgmt)):
            result = await r.list_repositories()
        assert result == {"repositories": [{"path": "/r"}]}
        mock_mgmt.list_indexed_repositories.assert_called_once_with(cf)

    async def test_add_code_to_graph_basic(self) -> None:
        r = CGCRuntime()
        _, cf, gb, jm = _inject_components(r)
        mock_idx = MagicMock()
        mock_idx.add_code_to_graph.return_value = {"job_id": "j1"}
        mock_mgmt = MagicMock()
        with patch.dict(
            "sys.modules", _cgc_handler_modules(management=mock_mgmt, indexing=mock_idx)
        ):
            result = await r.add_code_to_graph("/some/path")
        assert result == {"job_id": "j1"}
        ca = mock_idx.add_code_to_graph.call_args
        assert ca.args[0] is gb
        assert ca.args[1] is jm
        assert ca.args[2] is r._loop  # pyright: ignore[reportPrivateUsage]
        assert callable(ca.args[3])  # list_repos_func lambda
        assert ca.kwargs == {"path": "/some/path", "is_dependency": False}

    async def test_add_code_to_graph_lambda_calls_list_repos(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_idx = MagicMock()
        mock_mgmt = MagicMock()
        mock_mgmt.list_indexed_repositories.return_value = {"repositories": []}
        with patch.dict(
            "sys.modules", _cgc_handler_modules(management=mock_mgmt, indexing=mock_idx)
        ):
            await r.add_code_to_graph("/some/path")
        list_fn = mock_idx.add_code_to_graph.call_args.args[3]
        list_fn()
        mock_mgmt.list_indexed_repositories.assert_called_once_with(cf)

    async def test_add_code_to_graph_as_dependency(self) -> None:
        r = CGCRuntime()
        _, _, gb, jm = _inject_components(r)
        mock_idx = MagicMock()
        mock_mgmt = MagicMock()
        with patch.dict(
            "sys.modules", _cgc_handler_modules(management=mock_mgmt, indexing=mock_idx)
        ):
            await r.add_code_to_graph("/lib", is_dependency=True)
        ca = mock_idx.add_code_to_graph.call_args
        assert ca.kwargs == {"path": "/lib", "is_dependency": True}

    async def test_check_job_status(self) -> None:
        r = CGCRuntime()
        _, _, _, jm = _inject_components(r)
        mock_mgmt = MagicMock()
        mock_mgmt.check_job_status.return_value = {"status": "RUNNING"}
        with patch.dict("sys.modules", _cgc_handler_modules(management=mock_mgmt)):
            result = await r.check_job_status("job-123")
        assert result == {"status": "RUNNING"}
        mock_mgmt.check_job_status.assert_called_once_with(jm, job_id="job-123")

    async def test_delete_repository(self) -> None:
        r = CGCRuntime()
        _, _, gb, _ = _inject_components(r)
        mock_mgmt = MagicMock()
        mock_mgmt.delete_repository.return_value = {"deleted": True}
        with patch.dict("sys.modules", _cgc_handler_modules(management=mock_mgmt)):
            result = await r.delete_repository("/old/repo")
        assert result == {"deleted": True}
        mock_mgmt.delete_repository.assert_called_once_with(gb, repo_path="/old/repo")

    async def test_get_stats_without_repo_path(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_mgmt = MagicMock()
        mock_mgmt.get_repository_stats.return_value = {"files": 42}
        with patch.dict("sys.modules", _cgc_handler_modules(management=mock_mgmt)):
            result = await r.get_stats()
        assert result == {"files": 42}
        mock_mgmt.get_repository_stats.assert_called_once_with(cf)

    async def test_get_stats_with_repo_path(self) -> None:
        r = CGCRuntime()
        _, cf, _, _ = _inject_components(r)
        mock_mgmt = MagicMock()
        with patch.dict("sys.modules", _cgc_handler_modules(management=mock_mgmt)):
            await r.get_stats(repo_path="/my/repo")
        mock_mgmt.get_repository_stats.assert_called_once_with(cf, repo_path="/my/repo")
