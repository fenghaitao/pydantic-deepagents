"""Code-graph capabilities sub-package.

Provides three capability classes:
  - :class:`PotpieCapability` — Potpie HTTP-based code-graph integration
  - :class:`CGCCapability` — CodeGraphContext in-process integration
  - :class:`SimicsDeviceCapability` — Simics DML device register/capability analysis
"""

from pydantic_deep.capabilities.code_graph.cgc import CGCCapability
from pydantic_deep.capabilities.code_graph.potpie import PotpieCapability
from pydantic_deep.capabilities.code_graph.simics_device import SimicsDeviceCapability

__all__ = ["CGCCapability", "PotpieCapability", "SimicsDeviceCapability"]
