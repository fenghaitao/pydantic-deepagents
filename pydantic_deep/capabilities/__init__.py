"""Internal capabilities for pydantic-deep agents.

These wrap pydantic-deep's toolsets as pydantic-ai capabilities,
enabling clean composition via ``Agent(capabilities=[...])``.
"""

from pydantic_deep.capabilities.context import ContextFilesCapability
from pydantic_deep.capabilities.hooks import HooksCapability
from pydantic_deep.capabilities.memory import MemoryCapability
from pydantic_deep.capabilities.plan import PlanCapability
from pydantic_deep.capabilities.skills import SkillsCapability
from pydantic_deep.capabilities.teams import TeamCapability

__all__ = [
    "ContextFilesCapability",
    "HooksCapability",
    "MemoryCapability",
    "PlanCapability",
    "SkillsCapability",
    "TeamCapability",
]
