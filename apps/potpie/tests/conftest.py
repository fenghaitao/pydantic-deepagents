"""Pytest configuration for apps/potpie tests.

Adds the workspace root (parent of pydantic-deepagents/) to sys.path so that
`app.*` modules (potpie backend) are importable during testing.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Workspace root is two levels above pydantic-deepagents/
_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))
