"""Code-graph capabilities sub-package.

Provides four capability classes:
  - :class:`PotpieCapability` — Potpie HTTP-based code-graph integration
  - :class:`CGCCapability` — CodeGraphContext in-process integration
  - :class:`GraphifyCapability` — Graphify in-process knowledge-graph integration
  - :class:`SimicsDeviceCapability` — Simics DML device register/capability analysis
"""

from pydantic_deep.capabilities.code_graph.cgc import CGCCapability
from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability
from pydantic_deep.capabilities.code_graph.potpie import PotpieCapability
from pydantic_deep.capabilities.code_graph.simics_device import SimicsDeviceCapability

__all__ = [
    "CGCCapability",
    "GraphifyCapability",
    "PotpieCapability",
    "SimicsDeviceCapability",
]
