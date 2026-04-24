"""Tests for SimicsDeviceCapability (Simics DML device analysis capability).

Covers construction, before_run, get_toolset, and get_instructions methods.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from pydantic_deep.capabilities.code_graph.simics_device import SimicsDeviceCapability
from pydantic_deep.toolsets.code_graph.potpie.context import PotpieContext
from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime
from pydantic_ai import RunContext

@pytest.mark.asyncio
async def test_before_run_sets_kg_context():
    runtime = MagicMock(spec=PotpieRuntime)
    context = MagicMock(spec=PotpieContext)
    cap = SimicsDeviceCapability(runtime=runtime, context=context)
    ctx = MagicMock(spec=RunContext)
    ctx.deps = MagicMock()
    await cap.before_run(ctx)
    assert ctx.deps.kg_context is context


def test_get_toolset_returns_toolset():
    runtime = MagicMock(spec=PotpieRuntime)
    cap = SimicsDeviceCapability(runtime=runtime)
    toolset = MagicMock()
    cap._toolset = toolset
    assert cap.get_toolset() is toolset
    cap._toolset = None
    assert cap.get_toolset() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("project_id,expected_in", [
    ("proj-123", "Default project ID: `proj-123`"),
    (None, "You have access to Simics DML device analysis tools"),
])
async def test_get_instructions(project_id, expected_in):
    runtime = MagicMock(spec=PotpieRuntime)
    context = MagicMock(spec=PotpieContext)
    context.project_id = project_id
    cap = SimicsDeviceCapability(runtime=runtime, context=context)
    ctx = MagicMock(spec=RunContext)
    ctx.deps = MagicMock()
    ctx.deps.kg_context = context
    instructions_fn = cap.get_instructions()
    result = await instructions_fn(ctx)
    assert expected_in in result
