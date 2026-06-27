"""Code-graph setup helpers for the CLI (Potpie, CGC, and Graphify providers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


async def build_code_graph_capabilities(
    provider: str,
    *,
    project_id: str | None = None,
    user_id: str | None = None,
    root: Path | None = None,
    on_status: Any | None = None,
) -> tuple[Any, Any, list[Any], str | None]:
    """Build code-graph capabilities for the configured provider.

    Dispatches on *provider* so ``--code-graph`` works with any backend:

    - ``potpie`` (default): returns ``PotpieCapability`` + ``SimicsDeviceCapability``
      in the dedicated ``kg``/``simics`` slots (Potpie integrates subagents and a
      project_id, which the agent factory consumes specially).
    - ``cgc`` / ``graphify``: returns the in-process capability via the
      ``extra_capabilities`` list (no project_id/subagent integration needed).

    Returns:
        ``(kg_capability, simics_dev_capability, extra_capabilities, project_id)``.
        For non-potpie providers, ``kg_capability`` and ``simics_dev_capability``
        are ``None`` and the capability (if any) is in ``extra_capabilities``.
        ``project_id`` is echoed back (possibly updated by Potpie auto-discovery).
    """
    if provider == "cgc":
        from apps.cli.code_graph.cgc_setup import build_cgc_capability

        cap = await build_cgc_capability(None, root=root, on_status=on_status)
        return None, None, ([cap] if cap is not None else []), project_id

    if provider == "graphify":
        from apps.cli.code_graph.graphify_setup import build_graphify_capability

        cap = await build_graphify_capability(None, root=root, on_status=on_status)
        return None, None, ([cap] if cap is not None else []), project_id

    # potpie (default)
    from apps.cli.code_graph.potpie_setup import (
        build_kg_capability,
        build_simics_dev_capability,
    )

    kg_cap = await build_kg_capability(
        project_id, user_id, root=root, on_status=on_status
    )
    if kg_cap is not None and kg_cap.context is not None and kg_cap.context.project_id:
        project_id = kg_cap.context.project_id
    simics_cap = await build_simics_dev_capability(
        project_id, user_id, root=root, on_status=on_status
    )
    return kg_cap, simics_cap, [], project_id


__all__ = ["build_code_graph_capabilities"]
