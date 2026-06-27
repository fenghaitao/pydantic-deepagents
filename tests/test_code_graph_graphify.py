"""Tests for the Graphify code-graph provider.

Covers:
  - ``GraphifyRuntime`` (in-process graph.json queries via networkx)
  - ``GraphifyToolset`` (agent-callable tools)
  - ``GraphifyCapability`` (pydantic-ai capability)

The graphify-specific helper functions (``_query_graph_text``, ``_find_node``,
``_score_nodes``, ``edge_data``, ``god_nodes``) are mocked via ``sys.modules``
so the heavy ``graphify`` package (tree-sitter wheels) is not required, while
the real ``networkx`` graph code paths are exercised against a small fixture
graph.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pydantic_deep.toolsets.code_graph.graphify.context import GraphifyContext
from pydantic_deep.toolsets.code_graph.graphify.runtime import (
    GRAPH_FILENAME,
    GRAPHIFY_OUT_DIRNAME,
    GraphifyRuntime,
)

# ── Fixture graph ──────────────────────────────────────────────────────────────

_GRAPH_DATA: dict[str, Any] = {
    "directed": True,
    "multigraph": False,
    "graph": {},
    "nodes": [
        {
            "id": "a",
            "label": "alpha",
            "community": 0,
            "community_name": "core",
            "source_file": "a.py",
            "source_location": "L1",
            "file_type": "code",
        },
        {"id": "b", "label": "beta", "community": 1},
        {"id": "c", "label": "gamma", "community": 0},
        {"id": "hub", "label": "hub", "community": 0},
        {"id": "lonely", "label": "lonely"},
    ],
    "links": [
        {"source": "a", "target": "b", "relation": "calls", "confidence": "EXTRACTED"},
        {"source": "c", "target": "b", "relation": "uses"},
        {"source": "a", "target": "hub", "relation": "imports", "confidence": "INFERRED"},
    ],
}


# ── Fake graphify helper modules ────────────────────────────────────────────────


def _fake_query_graph_text(
    G: Any,
    question: str,
    mode: str = "bfs",
    depth: int = 2,
    token_budget: int = 2000,
    context_filters: Any = None,
) -> str:
    return (
        f"[mode={mode} depth={depth} budget={token_budget} "
        f"filters={context_filters} nodes={G.number_of_nodes()}] {question}"
    )


def _fake_find_node(G: Any, label: str) -> list[str]:
    return [n for n, d in G.nodes(data=True) if d.get("label") == label or n == label]


def _fake_score_nodes(G: Any, terms: list[str]) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for n, d in G.nodes(data=True):
        lbl = str(d.get("label", n)).lower()
        if any(t in lbl or t == n.lower() for t in terms):
            out.append((1.0, n))
    return out


def _fake_edge_data(G: Any, u: str, v: str) -> dict[str, Any]:
    data = G.get_edge_data(u, v)
    return dict(data) if data else {}


def _fake_god_nodes(G: Any, top_n: int = 10) -> list[dict[str, Any]]:
    nodes = sorted(G.nodes(data=True), key=lambda x: G.degree(x[0]), reverse=True)
    return [{"label": d.get("label", n), "degree": G.degree(n)} for n, d in nodes[:top_n]]


@pytest.fixture
def graphify_mods(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install fake ``graphify.serve/build/analyze`` modules into ``sys.modules``."""
    pkg = ModuleType("graphify")
    pkg.__path__ = []  # type: ignore[attr-defined]  # mark as package

    serve = ModuleType("graphify.serve")
    serve._query_graph_text = _fake_query_graph_text  # type: ignore[attr-defined]
    serve._find_node = _fake_find_node  # type: ignore[attr-defined]
    serve._score_nodes = _fake_score_nodes  # type: ignore[attr-defined]

    build = ModuleType("graphify.build")
    build.edge_data = _fake_edge_data  # type: ignore[attr-defined]

    analyze = ModuleType("graphify.analyze")
    analyze.god_nodes = _fake_god_nodes  # type: ignore[attr-defined]

    pkg.serve = serve  # type: ignore[attr-defined]
    pkg.build = build  # type: ignore[attr-defined]
    pkg.analyze = analyze  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "graphify", pkg)
    monkeypatch.setitem(sys.modules, "graphify.serve", serve)
    monkeypatch.setitem(sys.modules, "graphify.build", build)
    monkeypatch.setitem(sys.modules, "graphify.analyze", analyze)


def _write_graph(root: Path, data: dict[str, Any] | None = None) -> Path:
    """Write the fixture graph under ``root/graphify-out/graph.json``."""
    out_dir = root / GRAPHIFY_OUT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    gp = out_dir / GRAPH_FILENAME
    gp.write_text(json.dumps(data or _GRAPH_DATA), encoding="utf-8")
    return gp


# ── resolve_graph_path ─────────────────────────────────────────────────────────


class TestResolveGraphPath:
    def test_explicit_graph_path(self) -> None:
        rt = GraphifyRuntime(graph_path="/g/graph.json")
        assert rt.resolve_graph_path() == Path("/g/graph.json").resolve()

    def test_repo_path(self, tmp_path: Path) -> None:
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        assert rt.resolve_graph_path() == (
            tmp_path / GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME
        ).resolve()

    def test_defaults_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        rt = GraphifyRuntime()
        assert rt.resolve_graph_path() == (
            tmp_path / GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME
        ).resolve()


class TestMakeGraphifyRuntime:
    def test_factory_returns_runtime(self) -> None:
        from pydantic_deep.toolsets.code_graph import make_graphify_runtime

        rt = make_graphify_runtime(repo_path="/repo", graph_path="/g/graph.json")
        assert isinstance(rt, GraphifyRuntime)
        assert rt.resolve_graph_path() == Path("/g/graph.json").resolve()

    def test_factory_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic_deep.toolsets.code_graph import make_graphify_runtime

        monkeypatch.chdir(tmp_path)
        rt = make_graphify_runtime()
        assert isinstance(rt, GraphifyRuntime)
        assert rt.resolve_graph_path() == (
            tmp_path / GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME
        ).resolve()


# ── _load_graph / lifecycle ────────────────────────────────────────────────────


class TestLoadGraph:
    def test_missing_graph_raises(self, graphify_mods: None, tmp_path: Path) -> None:
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        with pytest.raises(FileNotFoundError, match="Graphify graph not found"):
            rt._load_graph()  # pyright: ignore[reportPrivateUsage]

    def test_loads_and_caches(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        g1 = rt._load_graph()  # pyright: ignore[reportPrivateUsage]
        g2 = rt._load_graph()  # pyright: ignore[reportPrivateUsage]
        assert g1 is g2
        assert g1.number_of_nodes() == 5

    def test_edges_key_compat(self, graphify_mods: None, tmp_path: Path) -> None:
        data = {k: v for k, v in _GRAPH_DATA.items() if k != "links"}
        data["edges"] = _GRAPH_DATA["links"]
        _write_graph(tmp_path, data)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        g = rt._load_graph()  # pyright: ignore[reportPrivateUsage]
        assert g.number_of_edges() == 3

    def test_close_drops_cache(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        rt._load_graph()  # pyright: ignore[reportPrivateUsage]
        assert rt._graph is not None  # pyright: ignore[reportPrivateUsage]
        rt.close()
        assert rt._graph is None  # pyright: ignore[reportPrivateUsage]

    async def test_async_context_manager(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        async with GraphifyRuntime(repo_path=str(tmp_path)) as rt:
            await rt.query("hi")
            assert rt._graph is not None  # pyright: ignore[reportPrivateUsage]
        assert rt._graph is None  # pyright: ignore[reportPrivateUsage]


# ── query ──────────────────────────────────────────────────────────────────────


class TestQuery:
    async def test_query_defaults(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        result = await rt.query("how does auth work?")
        assert "how does auth work?" in result
        assert "mode=bfs" in result
        assert "filters=[]" in result

    async def test_query_with_filters_and_mode(
        self, graphify_mods: None, tmp_path: Path
    ) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        result = await rt.query(
            "q", mode="dfs", depth=3, token_budget=500, context_filters=["x"]
        )
        assert "mode=dfs" in result
        assert "depth=3" in result
        assert "budget=500" in result
        assert "filters=['x']" in result


# ── explain ────────────────────────────────────────────────────────────────────


class TestExplain:
    async def test_explain_not_found(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        result = await rt.explain("nope")
        assert result == {"found": False, "label": "nope"}

    async def test_explain_with_community_name(
        self, graphify_mods: None, tmp_path: Path
    ) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        result = await rt.explain("alpha")
        assert result["found"] is True
        assert result["id"] == "a"
        assert result["community"] == "core"
        assert result["source_file"] == "a.py"
        # alpha has two outgoing connections (b, hub)
        assert result["total_connections"] == 2
        directions = {c["direction"] for c in result["connections"]}
        assert directions == {"out"}

    async def test_explain_community_fallback_and_predecessors(
        self, graphify_mods: None, tmp_path: Path
    ) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        result = await rt.explain("beta")
        # beta has no community_name → falls back to community id (1)
        assert result["community"] == 1
        # beta has two incoming connections (from a and c)
        assert result["total_connections"] == 2
        assert {c["direction"] for c in result["connections"]} == {"in"}


# ── path ───────────────────────────────────────────────────────────────────────


class TestPath:
    async def test_path_forward_and_backward(
        self, graphify_mods: None, tmp_path: Path
    ) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        result = await rt.path("alpha", "gamma")
        assert "Shortest path (2 hops)" in result
        # a --calls [EXTRACTED]--> beta  (forward, with confidence)
        assert "--calls [EXTRACTED]-->" in result
        # beta <--uses-- gamma  (backward, no confidence)
        assert "<--uses--" in result

    async def test_path_no_source(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        assert "No node matching 'zzz'" in await rt.path("zzz", "alpha")

    async def test_path_no_target(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        assert "No node matching 'zzz'" in await rt.path("alpha", "zzz")

    async def test_path_same_node(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        result = await rt.path("alpha", "alpha")
        assert "both resolved to the same node" in result

    async def test_path_no_path(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        result = await rt.path("alpha", "lonely")
        assert "No path found" in result


# ── god_nodes / stats ──────────────────────────────────────────────────────────


class TestGodNodesAndStats:
    async def test_god_nodes(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        nodes = await rt.god_nodes(top_n=2)
        assert len(nodes) == 2
        assert all("label" in n and "degree" in n for n in nodes)

    async def test_stats(self, graphify_mods: None, tmp_path: Path) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        stats = await rt.stats()
        assert stats["nodes"] == 5
        assert stats["edges"] == 3
        # communities {0, 1}; "lonely" has no community and is skipped
        assert stats["communities"] == 2
        assert stats["graph_path"].endswith(GRAPH_FILENAME)


# ── list / delete projects ──────────────────────────────────────────────────────


class TestProjectManagement:
    async def test_list_projects_with_repo_path(
        self, graphify_mods: None, tmp_path: Path
    ) -> None:
        _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        projects = await rt.list_projects()
        assert len(projects) == 1
        assert projects[0]["repo_name"] == tmp_path.name
        assert projects[0]["status"] == "ready"

    async def test_list_projects_graph_path_only(
        self, graphify_mods: None, tmp_path: Path
    ) -> None:
        gp = _write_graph(tmp_path)
        rt = GraphifyRuntime(graph_path=str(gp))
        projects = await rt.list_projects()
        # repo_name falls back to gp.parent.parent's name
        assert projects[0]["repo_name"] == tmp_path.name

    async def test_list_projects_root_repo_path(
        self, graphify_mods: None, tmp_path: Path
    ) -> None:
        gp = _write_graph(tmp_path)
        rt = GraphifyRuntime(repo_path="/", graph_path=str(gp))
        projects = await rt.list_projects()
        # Path("/").name == "" → falls back to repo_path itself
        assert projects[0]["repo_name"] == "/"

    async def test_list_projects_missing(self, tmp_path: Path) -> None:
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        assert await rt.list_projects() == []

    async def test_delete_project_graphify_out(self, tmp_path: Path) -> None:
        gp = _write_graph(tmp_path)
        rt = GraphifyRuntime(graph_path=str(gp))
        result = await rt.delete_project(str(gp))
        assert result["deleted"] is True
        assert not (tmp_path / GRAPHIFY_OUT_DIRNAME).exists()

    async def test_delete_project_bare_graph_file(self, tmp_path: Path) -> None:
        gp = tmp_path / "graph.json"
        gp.write_text("{}", encoding="utf-8")
        rt = GraphifyRuntime(graph_path=str(gp))
        result = await rt.delete_project(str(gp))
        assert result["deleted"] is True
        assert not gp.exists()

    async def test_delete_project_not_found(self, tmp_path: Path) -> None:
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        result = await rt.delete_project(str(tmp_path / "missing" / "graph.json"))
        assert result["deleted"] is False
        assert result["error"] == "not found"

    async def test_delete_all_projects_success(self, tmp_path: Path) -> None:
        gp = _write_graph(tmp_path)
        rt = GraphifyRuntime(graph_path=str(gp))
        result = await rt.delete_all_projects()
        assert result == {"deleted": 1}

    async def test_delete_all_projects_empty(self, tmp_path: Path) -> None:
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        assert await rt.delete_all_projects() == {"deleted": 0}

    async def test_delete_all_projects_with_errors(self, tmp_path: Path) -> None:
        rt = GraphifyRuntime(repo_path=str(tmp_path))
        rt.list_projects = AsyncMock(  # type: ignore[method-assign]
            return_value=[{"id": str(tmp_path / "graphify-out" / "graph.json")}]
        )
        result = await rt.delete_all_projects()
        assert result["deleted"] == 0
        assert len(result["errors"]) == 1


# ── GraphifyToolset ─────────────────────────────────────────────────────────────


def _mock_runtime() -> MagicMock:
    rt = MagicMock(spec=GraphifyRuntime)
    rt.list_projects = AsyncMock(return_value=[{"id": "g", "status": "ready"}])
    rt.query = AsyncMock(return_value="query-answer")
    rt.explain = AsyncMock(return_value={"found": True, "label": "alpha"})
    rt.path = AsyncMock(return_value="Shortest path (1 hops):\n  a --calls--> b")
    rt.god_nodes = AsyncMock(return_value=[{"label": "hub", "degree": 5}])
    rt.stats = AsyncMock(return_value={"nodes": 5, "edges": 3, "communities": 2})
    return rt


def _toolset_ctx(graphify_context: GraphifyContext | None = None) -> Any:
    from pydantic_ai import RunContext

    ctx = MagicMock(spec=RunContext)
    ctx.deps = MagicMock()
    ctx.deps.graphify_context = graphify_context
    return ctx


class TestGraphifyToolset:
    def test_creates_expected_tools(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        ts = GraphifyToolset(runtime=_mock_runtime())
        for name in (
            "list_code_projects",
            "query_code_graph",
            "explain_code_node",
            "find_code_path",
            "code_graph_god_nodes",
            "code_graph_stats",
        ):
            assert name in ts.tools

    async def test_list_code_projects(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        ts = GraphifyToolset(runtime=_mock_runtime())
        result = await ts.tools["list_code_projects"].function(_toolset_ctx())
        assert json.loads(result)[0]["id"] == "g"

    async def test_query_code_graph(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        rt = _mock_runtime()
        ts = GraphifyToolset(runtime=rt)
        result = await ts.tools["query_code_graph"].function(
            _toolset_ctx(), question="q", mode="dfs", depth=3, token_budget=42
        )
        assert result == "query-answer"
        rt.query.assert_awaited_once_with("q", mode="dfs", depth=3, token_budget=42)

    async def test_explain_code_node(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        ts = GraphifyToolset(runtime=_mock_runtime())
        result = await ts.tools["explain_code_node"].function(
            _toolset_ctx(), label="alpha"
        )
        assert json.loads(result)["label"] == "alpha"

    async def test_find_code_path(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        rt = _mock_runtime()
        ts = GraphifyToolset(runtime=rt)
        result = await ts.tools["find_code_path"].function(
            _toolset_ctx(), source="a", target="b"
        )
        assert "Shortest path" in result
        rt.path.assert_awaited_once_with("a", "b")

    async def test_god_nodes(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        ts = GraphifyToolset(runtime=_mock_runtime())
        result = await ts.tools["code_graph_god_nodes"].function(
            _toolset_ctx(), top_n=3
        )
        assert json.loads(result)[0]["label"] == "hub"

    async def test_stats(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        ts = GraphifyToolset(runtime=_mock_runtime())
        result = await ts.tools["code_graph_stats"].function(_toolset_ctx())
        assert json.loads(result)["nodes"] == 5

    async def test_instructions_with_toolset_repo_path(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        ts = GraphifyToolset(runtime=_mock_runtime(), repo_path="/my/repo")
        parts = await ts.get_instructions(_toolset_ctx())
        assert parts is not None
        assert "/my/repo" in parts[0]
        assert "query_code_graph" in parts[0]

    async def test_instructions_without_repo_path(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        ts = GraphifyToolset(runtime=_mock_runtime())
        parts = await ts.get_instructions(_toolset_ctx())
        assert parts is not None
        assert "Graphify" in parts[0]

    async def test_instructions_uses_context(self) -> None:
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        ts = GraphifyToolset(runtime=_mock_runtime())
        ctx = _toolset_ctx(GraphifyContext(repo_path="/from/context"))
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "/from/context" in parts[0]


# ── GraphifyCapability ──────────────────────────────────────────────────────────


def _cap_ctx(graphify_context: GraphifyContext | None = None) -> Any:
    from pydantic_ai import RunContext

    from pydantic_deep.deps import DeepAgentDeps

    ctx = MagicMock(spec=RunContext)
    ctx.deps = MagicMock(spec=DeepAgentDeps)
    ctx.deps.graphify_context = graphify_context
    return ctx


class TestGraphifyCapability:
    def test_construction(self) -> None:
        from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability

        rt = MagicMock(spec=GraphifyRuntime)
        cap = GraphifyCapability(runtime=rt)
        assert cap.runtime is rt
        assert cap.context is None
        assert cap.get_toolset() is None

    def test_get_toolset_after_set(self) -> None:
        from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability

        cap = GraphifyCapability(runtime=MagicMock(spec=GraphifyRuntime))
        ts = MagicMock()
        object.__setattr__(cap, "_toolset", ts)
        assert cap.get_toolset() is ts

    async def test_before_run_injects_context(self) -> None:
        from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability

        gctx = GraphifyContext(repo_path="/repo")
        cap = GraphifyCapability(runtime=MagicMock(spec=GraphifyRuntime), context=gctx)
        run_ctx = _cap_ctx()
        await cap.before_run(run_ctx)
        assert run_ctx.deps.graphify_context is gctx

    async def test_instructions_with_context(self) -> None:
        from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability

        gctx = GraphifyContext(repo_path="/my/repo")
        cap = GraphifyCapability(runtime=MagicMock(spec=GraphifyRuntime), context=gctx)
        fn = cap.get_instructions()
        result = await fn(_cap_ctx(graphify_context=gctx))
        assert result is not None
        assert "/my/repo" in result

    async def test_instructions_without_context(self) -> None:
        from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability

        cap = GraphifyCapability(runtime=MagicMock(spec=GraphifyRuntime))
        fn = cap.get_instructions()
        result = await fn(_cap_ctx())
        assert result is not None
        assert "Graphify" in result

    async def test_instructions_falls_back_to_cap_context(self) -> None:
        from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability

        gctx = GraphifyContext(repo_path="/fallback/repo")
        cap = GraphifyCapability(runtime=MagicMock(spec=GraphifyRuntime), context=gctx)
        fn = cap.get_instructions()
        result = await fn(_cap_ctx(graphify_context=None))
        assert result is not None
        assert "/fallback/repo" in result
