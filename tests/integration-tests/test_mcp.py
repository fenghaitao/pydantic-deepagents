"""Integration tests for MCP server connections (potpie SSE + CGC stdio).

These tests verify that ``pydantic-deep run --mcp`` correctly discovers and
lists tools from each code-graph MCP provider.

Prerequisites:
- Potpie test: the potpie backend must be running (``make potpie-start``).
- CGC test: no external service needed (stdio transport, in-process).
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYDANTIC_DEEP = str(_REPO_ROOT / ".venv" / "bin" / "pydantic-deep")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(
    *args: str,
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    """Run ``pydantic-deep`` with the given args and return the result."""
    cmd = [_PYDANTIC_DEEP, *args]
    merged_env = {**os.environ, **(env or {})}
    print(f"\n  Running: {' '.join(cmd)}", flush=True)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=merged_env,
        timeout=timeout,
    )
    print(f"  Exit code: {result.returncode}", flush=True)
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            print(f"  [stderr] {line}", flush=True)
    # Always print stdout so CI logs show the agent's actual response.
    if result.stdout:
        preview = result.stdout[:3000]
        suffix = f"\n  ...(truncated, {len(result.stdout)} chars total)" if len(result.stdout) > 3000 else ""
        for line in (preview + suffix).splitlines():
            print(f"  [stdout] {line}", flush=True)
    return result


def _extract_tool_names(output: str, prefix: str) -> list[str]:
    """Extract tool names with the given prefix from LLM output.

    Matches patterns like:
        **prefix_tool_name**
        `prefix_tool_name`
        prefix_tool_name:
        prefix_tool_name —
    """
    pattern = rf"\b({re.escape(prefix)}_[a-z_]+)\b"
    return sorted(set(re.findall(pattern, output)))


# ── Expected tool lists ────────────────────────────────────────────────────────

EXPECTED_POTPIE_TOOLS = sorted([
    "potpie_verify_connections",
    "potpie_get_code_from_probable_node_name",
    "potpie_get_code_from_node_id",
    "potpie_get_code_from_multiple_node_ids",
    "potpie_ask_knowledge_graph_queries",
    "potpie_neo4j_graph_rag_query",
    "potpie_nl_cypher_query",
    "potpie_get_nodes_from_tags",
    "potpie_get_code_graph_from_node_id",
    "potpie_change_detection",
    "potpie_get_code_file_structure",
    "potpie_get_node_neighbours_from_node_id",
    "potpie_get_linear_issue",
    "potpie_update_linear_issue",
    "potpie_get_jira_issue",
    "potpie_search_jira_issues",
    "potpie_create_jira_issue",
    "potpie_update_jira_issue",
    "potpie_add_jira_comment",
    "potpie_transition_jira_issue",
    "potpie_get_jira_projects",
    "potpie_get_jira_project_details",
    "potpie_get_jira_project_users",
    "potpie_link_jira_issues",
    "potpie_get_confluence_spaces",
    "potpie_get_confluence_page",
    "potpie_search_confluence_pages",
    "potpie_get_confluence_space_pages",
    "potpie_create_confluence_page",
    "potpie_update_confluence_page",
    "potpie_add_confluence_comment",
    "potpie_intelligent_code_graph",
    "potpie_fetch_file",
    "potpie_fetch_files_batch",
    "potpie_analyze_code_structure",
    "potpie_read_todos",
    "potpie_write_todos",
    "potpie_add_todo",
    "potpie_update_todo_status",
    "potpie_remove_todo",
    "potpie_add_subtask",
    "potpie_set_dependency",
    "potpie_get_available_tasks",
    "potpie_add_file_to_changes",
    "potpie_update_file_in_changes",
    "potpie_update_file_lines",
    "potpie_replace_in_file",
    "potpie_insert_lines",
    "potpie_delete_lines",
    "potpie_delete_file_in_changes",
    "potpie_revert_file",
    "potpie_get_file_from_changes",
    "potpie_list_files_in_changes",
    "potpie_search_content_in_changes",
    "potpie_clear_file_from_changes",
    "potpie_clear_all_changes",
    "potpie_get_changes_summary",
    "potpie_export_changes",
    "potpie_show_updated_file",
    "potpie_show_diff",
    "potpie_get_file_diff",
    "potpie_get_session_metadata",
    "potpie_execute_terminal_command",
    "potpie_terminal_session_output",
    "potpie_terminal_session_signal",
    "potpie_add_requirements",
    "potpie_delete_requirements",
    "potpie_get_requirements",
    "potpie_write_wiki_page",
    "potpie_simics_device_list_banks",
    "potpie_analyze_register_side_effect",
    "potpie_list_simics_device_feature",
    "potpie_get_register_side_effect",
    "potpie_get_capability_keywords",
    "potpie_analyze_capability",
    "potpie_list_capability",
    "potpie_web_search_tool",
])

EXPECTED_CGC_TOOLS = sorted([
    "cgc_add_code_to_graph",
    "cgc_check_job_status",
    "cgc_list_jobs",
    "cgc_find_code",
    "cgc_analyze_code_relationships",
    "cgc_watch_directory",
    "cgc_execute_cypher_query",
    "cgc_add_package_to_graph",
    "cgc_find_dead_code",
    "cgc_calculate_cyclomatic_complexity",
    "cgc_find_most_complex_functions",
    "cgc_list_indexed_repositories",
    "cgc_delete_repository",
    "cgc_visualize_graph_query",
    "cgc_list_watched_paths",
    "cgc_unwatch_directory",
    "cgc_load_bundle",
    "cgc_search_registry_bundles",
    "cgc_get_repository_stats",
    "cgc_discover_codegraph_contexts",
    "cgc_switch_context",
])


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestPotpieMCP:
    """Test potpie MCP server connection via streamable-http transport."""

    @pytest.fixture(scope="class", autouse=True)
    def potpie_mcp_server(self):
        """Start potpie-mcp in background via Makefile, yield, then stop it."""
        # Start potpie-mcp (allocates port automatically via ports_allocator)
        start_result = subprocess.run(
            ["make", "potpie-mcp-start"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert start_result.returncode == 0, (
            f"make potpie-mcp-start failed:\n{start_result.stderr}"
        )
        print(f"\n  potpie-mcp-start output: {start_result.stdout.strip()}", flush=True)

        # Read back the allocated port from PortManager
        port_result = subprocess.run(
            [
                str(_REPO_ROOT / ".venv" / "bin" / "python"),
                "-c",
                "from ports_allocator import PortManager; print(PortManager().get('potpie.mcp'))",
            ],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert port_result.returncode == 0, f"Port lookup failed: {port_result.stderr}"
        port = port_result.stdout.strip()
        print(f"  Potpie MCP port: {port}", flush=True)

        # Wait for server to be ready (poll until the SSE endpoint responds)
        import socket

        _deadline = time.time() + 60
        _host = "127.0.0.1"
        _port = int(port)
        while time.time() < _deadline:
            try:
                with socket.create_connection((_host, _port), timeout=2):
                    break
            except (ConnectionRefusedError, OSError):
                time.sleep(2)
        else:
            # Dump the server log if available
            _log = _REPO_ROOT / "code-graph-providers" / "potpie" / ".mcp_server.log"
            _log_tail = ""
            if _log.exists():
                _log_tail = _log.read_text()[-2000:]
            pytest.fail(
                f"Potpie MCP server did not become reachable on {_host}:{_port} "
                f"within 60s.\nServer log tail:\n{_log_tail}"
            )
        print(f"  Potpie MCP server is accepting connections on port {port}", flush=True)

        # Wait for the background server to finish initializing ToolService tools.
        # The server log (stdout+stderr redirected) shows either
        # "Registered N ToolService tools." or "Warning: ToolService init failed:".
        _log = _REPO_ROOT / "code-graph-providers" / "potpie" / ".mcp_server.log"
        _log_deadline = time.time() + 30
        while time.time() < _log_deadline:
            if _log.exists():
                _log_text = _log.read_text()
                if "Registered" in _log_text or "ToolService init failed" in _log_text:
                    break
            time.sleep(1)
        if _log.exists():
            _log_text = _log.read_text()
            _match = re.search(r"Registered (\d+) ToolService tools", _log_text)
            if _match:
                _n = int(_match.group(1))
                print(f"  potpie-mcp registered {_n} ToolService tools.", flush=True)
                if _n == 0:
                    print("  WARNING: potpie-mcp has 0 tools — ToolService may have failed.", flush=True)
            elif "ToolService init failed" in _log_text:
                print("  WARNING: ToolService init failed — agent will have no potpie tools.", flush=True)
            # Show the last few lines of the log for context.
            for _line in _log_text.splitlines()[-10:]:
                print(f"  [mcp-server-log] {_line}", flush=True)

        # Set kg.provider to potpie
        _run("config", "set", "kg.provider", "potpie")

        # Export port for the test
        os.environ["POTPIE_MCP_PORT"] = port

        yield port

        # Stop potpie-mcp and release port
        subprocess.run(
            ["make", "potpie-mcp-stop"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )

    def test_potpie_mcp_tools(self, potpie_mcp_server: str):
        """Verify all expected potpie-prefixed tools are available via MCP."""
        result = _run(
            "run",
            # Ask the agent to list tools by their exact full name, including the
            # potpie_ prefix, so the regex extractor can find them in stdout.
            "List every tool available to you whose name begins with 'potpie_'. "
            "Output each tool's complete name exactly as defined "
            "(for example: potpie_verify_connections, potpie_get_code_from_node_id). "
            "Do not omit the potpie_ prefix.",
            "--mcp", "--no-browser",
            env={"POTPIE_MCP_PORT": potpie_mcp_server},
            timeout=300,
        )
        assert result.returncode == 0, (
            f"pydantic-deep run failed (exit={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        found_tools = _extract_tool_names(result.stdout, "potpie")
        matched = set(EXPECTED_POTPIE_TOOLS) & set(found_tools)
        assert len(matched) >= 10, (
            f"Expected at least 10 potpie tools, found {len(matched)}:\n"
            + "\n".join(f"  + {t}" for t in sorted(matched))
            + f"\n\nAll found ({len(found_tools)}):\n"
            + "\n".join(f"  {t}" for t in found_tools)
            + f"\n\nFull stdout ({len(result.stdout)} chars):\n"
            + result.stdout[:5000]
        )


class TestCGCMCP:
    """Test CGC MCP server connection via stdio transport."""

    @pytest.fixture(scope="class", autouse=True)
    def cgc_config(self):
        """Set kg.provider to cgc for this test class."""
        # FalkorDB Lite requires Unix sockets which don't work on NFS.
        # Create a local .codegraphcontext with database=kuzudb so resolve_context()
        # picks it up and the server uses KùzuDB instead.
        cgc_dir = _REPO_ROOT / ".codegraphcontext"
        cgc_dir.mkdir(exist_ok=True)
        (cgc_dir / "db").mkdir(exist_ok=True)
        config_yaml = cgc_dir / "config.yaml"
        _had_config = config_yaml.exists()
        _old_config = config_yaml.read_text() if _had_config else None
        config_yaml.write_text("database: kuzudb\n")

        os.environ["CGC_RUNTIME_DB_TYPE"] = "kuzudb"
        _run("config", "set", "kg.provider", "cgc")
        yield
        # Restore to potpie (default)
        _run("config", "set", "kg.provider", "potpie")
        os.environ.pop("CGC_RUNTIME_DB_TYPE", None)
        if _old_config is not None:
            config_yaml.write_text(_old_config)
        else:
            import shutil
            shutil.rmtree(cgc_dir, ignore_errors=True)

    def test_cgc_mcp_tools(self):
        """Verify all expected cgc-prefixed tools are available via MCP."""
        result = _run(
            "run",
            # Ask the agent to list tools by their exact full name, including the
            # cgc_ prefix, so the regex extractor can find them in stdout.
            "List every tool available to you whose name begins with 'cgc_'. "
            "Output each tool's complete name exactly as defined "
            "(for example: cgc_find_code, cgc_add_code_to_graph). "
            "Do not omit the cgc_ prefix.",
            "--mcp", "--no-browser",
            timeout=300,
        )
        assert result.returncode == 0, (
            f"pydantic-deep run failed (exit={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        found_tools = _extract_tool_names(result.stdout, "cgc")
        matched = set(EXPECTED_CGC_TOOLS) & set(found_tools)
        assert len(matched) >= 10, (
            f"Expected at least 10 CGC tools, found {len(matched)}:\n"
            + "\n".join(f"  + {t}" for t in sorted(matched))
            + f"\n\nAll found ({len(found_tools)}):\n"
            + "\n".join(f"  {t}" for t in found_tools)
        )
