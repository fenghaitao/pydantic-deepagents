"""Runtime backend — queries a Graphify knowledge graph in-process.

Graphify indexes a codebase (and docs, PDFs, images, …) into a single
``graphify-out/graph.json`` file. Unlike Potpie (HTTP service) or CGC
(graph database), Graphify queries run entirely in-process against that
JSON graph using the helper functions in :mod:`graphify.serve`.

The graph is loaded lazily on the first call and cached for the lifetime of
the runtime instance. Call ``close()`` to drop the cached graph (or use
``async with GraphifyRuntime(...) as r:``).

Requires:
  - the ``graphifyy`` package installed (provides the ``graphify`` module)
  - a ``graphify-out/graph.json`` produced by ``graphify .`` (or an explicit
    ``graph_path`` pointing at any Graphify ``graph.json``)
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Standard sub-directory Graphify writes its output into.
GRAPHIFY_OUT_DIRNAME = "graphify-out"
#: Standard graph filename inside ``graphify-out/``.
GRAPH_FILENAME = "graph.json"


class GraphifyRuntime:
    """Runtime that queries a Graphify ``graph.json`` directly in-process.

    Instantiation is cheap; the graph is parsed on the first call and reused.
    All public query methods are async and delegate to synchronous helpers
    via :func:`asyncio.to_thread`.

    Args:
        repo_path: Path to the indexed repository (the directory containing
            ``graphify-out/``). Used to locate the graph and for status text.
        graph_path: Explicit path to a ``graph.json`` file. Takes precedence
            over ``repo_path`` when both are given.
    """

    def __init__(
        self, repo_path: str | None = None, graph_path: str | None = None
    ) -> None:
        self._repo_path = repo_path
        self._graph_path = graph_path
        self._graph: Any | None = None

    # ── Graph loading / lifecycle ──────────────────────────────────────────

    def resolve_graph_path(self) -> Path:
        """Return the resolved path to the ``graph.json`` file.

        Uses ``graph_path`` when supplied, otherwise
        ``{repo_path or cwd}/graphify-out/graph.json``.
        """
        if self._graph_path:
            return Path(self._graph_path).expanduser().resolve()
        base = Path(self._repo_path) if self._repo_path else Path.cwd()
        return (base / GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME).resolve()

    def _load_graph(self) -> Any:
        """Lazily parse and cache the graph as a directed ``networkx`` graph.

        Mirrors the loading logic Graphify's CLI uses (``edges``/``links``
        compatibility, forced directed), but raises instead of exiting so
        callers can handle errors.

        Raises:
            FileNotFoundError: If the graph file does not exist.
        """
        if self._graph is None:
            from networkx.readwrite import json_graph

            gp = self.resolve_graph_path()
            if not gp.exists():
                raise FileNotFoundError(
                    f"Graphify graph not found at {gp}. "
                    "Run `graphify .` in the repository to build it."
                )
            raw = json.loads(gp.read_text(encoding="utf-8"))
            if "links" not in raw and "edges" in raw:
                raw = dict(raw, links=raw["edges"])
            raw = {**raw, "directed": True}
            try:
                self._graph = json_graph.node_link_graph(raw, edges="links")
            except TypeError:  # pragma: no cover - older networkx signature
                self._graph = json_graph.node_link_graph(raw)
            logger.debug("GraphifyRuntime: loaded graph from %s", gp)
        return self._graph

    def close(self) -> None:
        """Drop the cached graph so it is re-read on the next call."""
        self._graph = None

    async def __aenter__(self) -> GraphifyRuntime:
        return self

    async def __aexit__(self, *_: Any) -> None:
        self.close()

    # ── Query ──────────────────────────────────────────────────────────────

    async def query(
        self,
        question: str,
        mode: str = "bfs",
        depth: int = 2,
        token_budget: int = 2000,
        context_filters: list[str] | None = None,
    ) -> str:
        """Answer a natural-language question against the graph.

        Returns a scoped, token-budgeted subgraph rendered as text — the same
        output as ``graphify query "<question>"``.

        Args:
            question: Natural-language question about the codebase.
            mode: Traversal strategy — ``"bfs"`` (default) or ``"dfs"``.
            depth: Traversal depth from the seed nodes.
            token_budget: Approximate token budget for the rendered subgraph.
            context_filters: Optional list of context labels to restrict the
                search to (e.g. file-type or community filters).
        """
        return await asyncio.to_thread(
            self._query_sync, question, mode, depth, token_budget, context_filters
        )

    def _query_sync(
        self,
        question: str,
        mode: str,
        depth: int,
        token_budget: int,
        context_filters: list[str] | None,
    ) -> str:
        from graphify.serve import _query_graph_text

        graph = self._load_graph()
        return _query_graph_text(
            graph,
            question,
            mode=mode,
            depth=depth,
            token_budget=token_budget,
            context_filters=context_filters or [],
        )

    # ── Explain ────────────────────────────────────────────────────────────

    async def explain(self, label: str) -> dict[str, Any]:
        """Describe a single node and its connections.

        Args:
            label: Node label, concept, or symbol name to look up.

        Returns:
            Dict with node metadata and up to 20 connections, or
            ``{"found": False}`` when no node matches.
        """
        return await asyncio.to_thread(self._explain_sync, label)

    def _explain_sync(self, label: str) -> dict[str, Any]:
        from graphify.build import edge_data
        from graphify.serve import _find_node

        graph = self._load_graph()
        matches = _find_node(graph, label)
        if not matches:
            return {"found": False, "label": label}
        nid = matches[0]
        data = graph.nodes[nid]
        # (neighbor_degree, connection) pairs so we can sort by hub-ness using
        # the neighbor's node id, then drop the degree before returning.
        scored: list[tuple[int, dict[str, str]]] = []
        for nb in graph.successors(nid):
            ed = edge_data(graph, nid, nb)
            scored.append(
                (
                    graph.degree(nb),
                    {
                        "direction": "out",
                        "neighbor": graph.nodes[nb].get("label", nb),
                        "relation": ed.get("relation", ""),
                        "confidence": ed.get("confidence", ""),
                    },
                )
            )
        for nb in graph.predecessors(nid):
            ed = edge_data(graph, nb, nid)
            scored.append(
                (
                    graph.degree(nb),
                    {
                        "direction": "in",
                        "neighbor": graph.nodes[nb].get("label", nb),
                        "relation": ed.get("relation", ""),
                        "confidence": ed.get("confidence", ""),
                    },
                )
            )
        scored.sort(key=lambda c: c[0], reverse=True)
        connections = [c[1] for c in scored]
        return {
            "found": True,
            "id": nid,
            "label": data.get("label", nid),
            "source_file": data.get("source_file", ""),
            "source_location": data.get("source_location", ""),
            "file_type": data.get("file_type", ""),
            "community": data.get("community_name") or data.get("community", ""),
            "degree": graph.degree(nid),
            "connections": connections[:20],
            "total_connections": len(connections),
        }

    # ── Path ───────────────────────────────────────────────────────────────

    async def path(self, source: str, target: str) -> str:
        """Find and render the shortest path between two nodes.

        Args:
            source: Label or symbol name of the start node.
            target: Label or symbol name of the end node.

        Returns:
            A human-readable description of the shortest path, or a message
            explaining why no path could be found.
        """
        return await asyncio.to_thread(self._path_sync, source, target)

    def _path_sync(self, source: str, target: str) -> str:
        import networkx as nx

        from graphify.build import edge_data
        from graphify.serve import _score_nodes

        graph = self._load_graph()
        src_scored = _score_nodes(graph, [t.lower() for t in source.split()])
        tgt_scored = _score_nodes(graph, [t.lower() for t in target.split()])
        if not src_scored:
            return f"No node matching '{source}' found."
        if not tgt_scored:
            return f"No node matching '{target}' found."
        src_nid, tgt_nid = src_scored[0][1], tgt_scored[0][1]
        if src_nid == tgt_nid:
            return (
                f"'{source}' and '{target}' both resolved to the same node "
                f"'{src_nid}'. Use a more specific label or the exact node ID."
            )
        try:
            path_nodes = nx.shortest_path(
                graph.to_undirected(as_view=True), src_nid, tgt_nid
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return f"No path found between '{source}' and '{target}'."
        hops = len(path_nodes) - 1
        segments: list[str] = []
        for i in range(len(path_nodes) - 1):
            u, v = path_nodes[i], path_nodes[i + 1]
            if graph.has_edge(u, v):
                ed = edge_data(graph, u, v)
                forward = True
            else:
                ed = edge_data(graph, v, u)
                forward = False
            rel = ed.get("relation", "")
            conf = ed.get("confidence", "")
            conf_str = f" [{conf}]" if conf else ""
            if i == 0:
                segments.append(graph.nodes[u].get("label", u))
            label_v = graph.nodes[v].get("label", v)
            if forward:
                segments.append(f"--{rel}{conf_str}--> {label_v}")
            else:
                segments.append(f"<--{rel}{conf_str}-- {label_v}")
        return f"Shortest path ({hops} hops):\n  " + " ".join(segments)

    # ── God nodes / stats ──────────────────────────────────────────────────

    async def god_nodes(self, top_n: int = 10) -> list[dict[str, Any]]:
        """Return the most connected ("god") nodes in the graph.

        Args:
            top_n: Number of top nodes to return.
        """
        return await asyncio.to_thread(self._god_nodes_sync, top_n)

    def _god_nodes_sync(self, top_n: int) -> list[dict[str, Any]]:
        from graphify.analyze import god_nodes as _god_nodes

        graph = self._load_graph()
        return list(_god_nodes(graph, top_n=top_n))

    async def stats(self) -> dict[str, Any]:
        """Return summary statistics for the graph (nodes, edges, communities)."""
        return await asyncio.to_thread(self._stats_sync)

    def _stats_sync(self) -> dict[str, Any]:
        graph = self._load_graph()
        communities: set[Any] = set()
        for _, data in graph.nodes(data=True):
            cid = data.get("community")
            if cid is not None:
                communities.add(cid)
        return {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "communities": len(communities),
            "graph_path": str(self.resolve_graph_path()),
        }

    # ── Provider protocol (project management) ─────────────────────────────

    async def list_projects(self) -> list[dict[str, Any]]:
        """List indexed Graphify projects (the resolved graph, if it exists).

        Each Graphify ``graph.json`` corresponds to one project. Returns a
        single-entry list when the graph exists, or an empty list otherwise.
        """
        return await asyncio.to_thread(self._list_projects_sync)

    def _list_projects_sync(self) -> list[dict[str, Any]]:
        gp = self.resolve_graph_path()
        if not gp.exists():
            return []
        repo_name = self._repo_path or str(gp.parent.parent)
        return [
            {
                "id": str(gp),
                "repo_name": Path(repo_name).name or repo_name,
                "branch_name": "",
                "status": "ready",
            }
        ]

    async def delete_project(self, project_id: str) -> dict[str, Any]:
        """Delete a Graphify project by removing its ``graphify-out`` directory.

        Args:
            project_id: Path to the ``graph.json`` (as returned by
                :meth:`list_projects`).

        Returns:
            Dict describing the deletion outcome.
        """
        return await asyncio.to_thread(self._delete_project_sync, project_id)

    def _delete_project_sync(self, project_id: str) -> dict[str, Any]:
        gp = Path(project_id)
        out_dir = gp.parent
        if out_dir.name == GRAPHIFY_OUT_DIRNAME and out_dir.exists():
            shutil.rmtree(out_dir)
            self.close()
            return {"deleted": True, "id": project_id, "removed": str(out_dir)}
        if gp.exists():
            gp.unlink()
            self.close()
            return {"deleted": True, "id": project_id, "removed": str(gp)}
        return {"deleted": False, "id": project_id, "error": "not found"}

    async def delete_all_projects(self) -> dict[str, Any]:
        """Delete all known Graphify projects.

        Returns a dict with at minimum ``{"deleted": <count>}``.
        """
        projects = await self.list_projects()
        deleted = 0
        errors: list[str] = []
        for p in projects:
            result = await self.delete_project(p["id"])
            if result.get("deleted"):
                deleted += 1
            else:
                errors.append(f"{p['id']}: {result.get('error', 'unknown error')}")
        out: dict[str, Any] = {"deleted": deleted}
        if errors:
            out["errors"] = errors
        return out


__all__ = ["GraphifyRuntime", "GRAPHIFY_OUT_DIRNAME", "GRAPH_FILENAME"]
