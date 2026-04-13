"""Tests for pydantic_deep.subagents_potpie."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydantic_deep.subagents_potpie import (
    _BLAST_RADIUS_INSTRUCTIONS,
    _BLAST_RADIUS_TOOL_NAMES,
    _QNA_INSTRUCTIONS,
    _QNA_TOOL_NAMES,
    make_potpie_subagents,
)


class TestToolNameLists:
    def test_qna_tool_names_contains_expected_tools(self) -> None:
        assert "ask_knowledge_graph_queries" in _QNA_TOOL_NAMES
        assert "get_code_from_multiple_node_ids" in _QNA_TOOL_NAMES
        assert "get_code_file_structure" in _QNA_TOOL_NAMES

    def test_blast_radius_tool_names_contains_change_detection(self) -> None:
        assert "change_detection" in _BLAST_RADIUS_TOOL_NAMES

    def test_blast_radius_tool_names_contains_graph_tools(self) -> None:
        assert "ask_knowledge_graph_queries" in _BLAST_RADIUS_TOOL_NAMES
        assert "get_code_from_multiple_node_ids" in _BLAST_RADIUS_TOOL_NAMES

    def test_all_tool_name_lists_are_non_empty(self) -> None:
        from pydantic_deep.subagents_potpie import (
            _CODE_GEN_TOOL_NAMES,
            _DEBUG_TOOL_NAMES,
            _INTEGRATION_TEST_TOOL_NAMES,
            _LLD_TOOL_NAMES,
            _UNIT_TEST_TOOL_NAMES,
        )
        for names in [
            _QNA_TOOL_NAMES,
            _DEBUG_TOOL_NAMES,
            _CODE_GEN_TOOL_NAMES,
            _LLD_TOOL_NAMES,
            _UNIT_TEST_TOOL_NAMES,
            _INTEGRATION_TEST_TOOL_NAMES,
            _BLAST_RADIUS_TOOL_NAMES,
        ]:
            assert len(names) > 0


class TestInstructions:
    def test_qna_instructions_mention_role(self) -> None:
        assert "Codebase Q&A Specialist" in _QNA_INSTRUCTIONS

    def test_blast_radius_instructions_mention_role(self) -> None:
        assert "Blast Radius Analyzer" in _BLAST_RADIUS_INSTRUCTIONS

    def test_blast_radius_instructions_mention_change_detection(self) -> None:
        assert "change_detection" in _BLAST_RADIUS_INSTRUCTIONS


class TestMakePotpieSubagents:
    def _patch_ctx(self) -> dict:
        """Common sys.modules patches for make_potpie_subagents."""
        mock_rt = AsyncMock()
        mock_rt.db.get_session.return_value = MagicMock()
        return {
            "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils": MagicMock(
                wrap_structured_tools=MagicMock(return_value=[])
            ),
        }

    async def test_returns_two_active_subagent_configs(self) -> None:
        mock_backend = MagicMock()

        with patch(
            "pydantic_deep.toolsets.code_graph.toolset.CodeGraphToolset.from_runtime",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await make_potpie_subagents(mock_backend, "user-1")

        assert len(result) == 2

    async def test_subagent_names(self) -> None:
        mock_backend = MagicMock()

        with patch(
            "pydantic_deep.toolsets.code_graph.toolset.CodeGraphToolset.from_runtime",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await make_potpie_subagents(mock_backend, "user-1")

        names = [s["name"] for s in result]
        assert set(names) == {"codebase_qna", "blast_radius"}

    async def test_all_configs_have_preferred_mode_async(self) -> None:
        mock_backend = MagicMock()

        with patch(
            "pydantic_deep.toolsets.code_graph.toolset.CodeGraphToolset.from_runtime",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await make_potpie_subagents(mock_backend, "user-1")

        for config in result:
            assert config.get("preferred_mode") == "async", (
                f"{config['name']} should have preferred_mode='async'"
            )

    async def test_no_project_id_parameter(self) -> None:
        """make_potpie_subagents should not accept project_id."""
        import inspect
        sig = inspect.signature(make_potpie_subagents)
        assert "project_id" not in sig.parameters
