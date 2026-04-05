"""Loop detection capability — breaks infinite tool call retries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from pydantic_deep.deps import DeepAgentDeps


def _hash_args(args: dict[str, Any]) -> str:
    """Create a stable hash of tool arguments."""
    try:
        serialized = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover — default=str handles all types
        serialized = str(args)
    return hashlib.md5(serialized.encode()).hexdigest()


@dataclass
class LoopDetectionMiddleware(AbstractCapability[DeepAgentDeps]):
    """Capability that detects repeated tool calls with identical arguments.

    When the same tool is called with the same arguments more than
    ``max_repeats`` times within the recent history window, the call
    is denied with a ModelRetry asking the agent to try a different approach.

    Args:
        max_repeats: Number of identical calls before blocking. Default 3.
        window_size: Number of recent calls to track. Default 15.
    """

    max_repeats: int = 3
    window_size: int = 15
    _call_history: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)

    async def before_tool_execute(
        self,
        ctx: RunContext[DeepAgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Check for repeated tool calls and deny if loop detected."""
        key = (call.tool_name, _hash_args(args))
        recent = self._call_history[-self.window_size :]
        repeat_count = sum(1 for k in recent if k == key)

        if repeat_count >= self.max_repeats:
            raise ModelRetry(
                f"Loop detected: '{call.tool_name}' called {repeat_count + 1} times "
                f"with the same arguments. Stop retrying and try a completely "
                f"different approach to solve this problem."
            )

        self._call_history.append(key)
        if len(self._call_history) > self.window_size * 2:
            self._call_history = self._call_history[-self.window_size :]

        return args


__all__ = ["LoopDetectionMiddleware"]
