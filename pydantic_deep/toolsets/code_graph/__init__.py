"""Code-graph integration package for pydantic-deep.

Provides:
  - PotpieBackend  — shared Protocol (backend.py)
  - RestBackend    — HTTP REST implementation (rest_backend.py)
  - RuntimeBackend — direct PotpieRuntime implementation (runtime_backend.py)
  - CodeGraphToolset — pydantic-ai FunctionToolset (toolset.py)
  - make_backend() — factory that selects the right backend from CliConfig

Usage (in apps/cli/agent.py)::

    from pydantic_deep.toolsets.code_graph import make_backend, CodeGraphToolset

    if config.potpie_api_key or config.potpie_mode == "local":
        backend = make_backend(config)
        toolsets_extra.append(CodeGraphToolset(backend=backend,
                                               project_id=config.potpie_project_id))

Usage (standalone)::

    from pydantic_deep.toolsets.code_graph import CodeGraphToolset
    from pydantic_deep.toolsets.code_graph.rest_backend import RestBackend

    toolset = CodeGraphToolset(
        backend=RestBackend(base_url="http://localhost:8001", api_key="mykey"),
        project_id="<uuid>",
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_deep.toolsets.code_graph.backend import PotpieBackend
from pydantic_deep.toolsets.code_graph.toolset import CodeGraphToolset

if TYPE_CHECKING:
    # Avoid importing CliConfig at module level to prevent circular imports
    # when this package is used outside the CLI context.
    from apps.cli.config import CliConfig


def make_backend(config: CliConfig) -> PotpieBackend:
    """Construct the appropriate PotpieBackend from CLI config.

    Selection logic:
      - ``potpie_mode == "local"``  → RuntimeBackend (direct PotpieRuntime)
      - otherwise (default "rest")  → RestBackend (HTTP, auto-discovers URL)

    Args:
        config: Loaded CliConfig instance.

    Returns:
        A PotpieBackend implementation ready for use.

    Raises:
        ValueError: If REST mode is selected but no URL can be discovered
            and no API key is configured.
    """
    if config.potpie_mode == "local":
        from pydantic_deep.toolsets.code_graph.runtime_backend import RuntimeBackend

        return RuntimeBackend()

    # REST mode — resolve URL
    url = config.potpie_url
    if not url:
        from apps.cli.potpie_discovery import discover_potpie_url

        url = discover_potpie_url()
    if not url:
        raise ValueError(
            "Cannot connect to potpie: no URL configured and discovery failed.\n"
            "Either start the potpie service (via singularity/start.sh) or set:\n"
            "  pydantic-deep config set potpie_url http://localhost:<port>\n"
            "Or use local mode:\n"
            "  pydantic-deep config set potpie_mode local"
        )

    from pydantic_deep.toolsets.code_graph.rest_backend import RestBackend

    return RestBackend(base_url=url, api_key=config.potpie_api_key or "")


__all__ = [
    "PotpieBackend",
    "CodeGraphToolset",
    "make_backend",
]
