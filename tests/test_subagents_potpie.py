"""Tests for pydantic_deep.subagents_potpie."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydantic_deep.subagents_potpie import (
    _BLAST_RADIUS_TOOL_NAMES,
    _QNA_TOOL_NAMES,
    _BLAST_RADIUS_INSTRUCTIONS,
    _QNA_INSTRUCTIONS,
    make_potpie_subagents,
)


class TestToolNameLists:
    def test_qna_tool_names_contains_expected_tools(self) -> None:
        assert "ask_knowledge_graph_queries" in _QNA_TOOL_NAMES
        assert "get_code_from_multiple_node_ids" in _QNA_TOOL_NAMES
        assert "nl_cypher_query" in _QNA_TOOL_NAMES

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
    async def test_returns_seven_subagent_configs(self) -> None:
        mock_backend = MagicMock()

        mock_rt = AsyncMock()
        mock_rt.db.get_session.return_value = MagicMock()
        mock_svc = MagicMock()
        mock_svc.get_tools.return_value = []

        with (
            patch.dict("sys.modules", {
                "potpie": MagicMock(PotpieRuntime=MagicMock(from_env=MagicMock(return_value=mock_rt))),
                "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils": MagicMock(
                    wrap_structured_tools=MagicMock(return_value=[])
                ),
                "app.modules.intelligence.tools.tool_service": MagicMock(
                    ToolService=MagicMock(return_value=mock_svc)
                ),
                "apps.potpie.toolset": MagicMock(_inject_project_id=lambda t: t),
                "pydantic_ai.toolsets": MagicMock(FunctionToolset=MagicMock()),
            }),
        ):
            result = await make_potpie_subagents(mock_backend, "proj-123", "user-1")

        assert len(result) == 7

    async def test_subagent_names(self) -> None:
        mock_backend = MagicMock()
        mock_rt = AsyncMock()
        mock_rt.db.get_session.return_value = MagicMock()
        mock_svc = MagicMock()
        mock_svc.get_tools.return_value = []

        with patch.dict("sys.modules", {
            "potpie": MagicMock(PotpieRuntime=MagicMock(from_env=MagicMock(return_value=mock_rt))),
            "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils": MagicMock(
                wrap_structured_tools=MagicMock(return_value=[])
            ),
            "app.modules.intelligence.tools.tool_service": MagicMock(
                ToolService=MagicMock(return_value=mock_svc)
            ),
            "apps.potpie.toolset": MagicMock(_inject_project_id=lambda t: t),
            "pydantic_ai.toolsets": MagicMock(FunctionToolset=MagicMock()),
        }):
            result = await make_potpie_subagents(mock_backend, "proj-123", "user-1")

        names = [s["name"] for s in result]
        assert set(names) == {
            "codebase_qna", "blast_radius", "debugging",
            "code_generation", "lld", "unit_test", "integration_test",
        }

    async def test_all_configs_have_no_preferred_mode(self) -> None:
        mock_backend = MagicMock()
        mock_rt = AsyncMock()
        mock_rt.db.get_session.return_value = MagicMock()
        mock_svc = MagicMock()
        mock_svc.get_tools.return_value = []

        with patch.dict("sys.modules", {
            "potpie": MagicMock(PotpieRuntime=MagicMock(from_env=MagicMock(return_value=mock_rt))),
            "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils": MagicMock(
                wrap_structured_tools=MagicMock(return_value=[])
            ),
            "app.modules.intelligence.tools.tool_service": MagicMock(
                ToolService=MagicMock(return_value=mock_svc)
            ),
            "apps.potpie.toolset": MagicMock(_inject_project_id=lambda t: t),
            "pydantic_ai.toolsets": MagicMock(FunctionToolset=MagicMock()),
        }):
            result = await make_potpie_subagents(mock_backend, "proj-123", "user-1")

        for config in result:
            assert "preferred_mode" not in config, f"{config['name']} should not have preferred_mode set"
