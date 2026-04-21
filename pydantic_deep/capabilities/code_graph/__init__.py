"""Code-graph capabilities sub-package.

Provides two capability classes:
  - :class:`PotpieCapability` — Potpie HTTP-based code-graph integration
  - :class:`CGCCapability` — CodeGraphContext in-process integration
"""

from pydantic_deep.capabilities.code_graph.cgc import CGCCapability
from pydantic_deep.capabilities.code_graph.potpie import PotpieCapability

__all__ = ["CGCCapability", "PotpieCapability"]
