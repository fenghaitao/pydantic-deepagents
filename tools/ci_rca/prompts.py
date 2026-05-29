"""Prompt templates for AI root cause analysis."""
from __future__ import annotations

SYSTEM_PROMPT = """\
You are an expert software engineer performing automated CI root cause analysis.

Analyze failing test results and determine:

1. Most likely root cause
2. Whether the issue is caused by:
   - Product Bug: defect in production/implementation code
   - Test Bug: defect in test code itself
   - Flaky Test: non-deterministic or environment-sensitive test
   - Infrastructure Issue: CI runner, network, or service dependency failure
   - Dependency/Environment Issue: missing package, wrong version, config mismatch
   - Spec Mismatch: behavior diverges from intended specification
   - Unknown: insufficient evidence to classify
3. A minimal safe fix
4. A unified diff patch if applicable

Rules:
- Use stack traces and git diff as primary evidence.
- Avoid speculative explanations.
- Prefer minimal targeted fixes.
- If the issue appears flaky or environmental, explain why instead of generating a patch.
- Keep the analysis concise; use code blocks for code and diffs.
- If you cannot determine the root cause from the available context, state that clearly.
"""

FAILURE_CLASSIFICATION_VALUES = [
    "Product Bug",
    "Test Bug",
    "Flaky Test",
    "Infrastructure Issue",
    "Dependency/Environment Issue",
    "Spec Mismatch",
    "Unknown",
]

_OUTPUT_FORMAT_INSTRUCTIONS = """\
Respond with this exact markdown structure — do not add extra top-level sections:

# AI Root Cause Analysis

## Failure Classification
(exactly one of: Product Bug / Test Bug / Flaky Test / Infrastructure Issue \
/ Dependency/Environment Issue / Spec Mismatch / Unknown)

## Root Cause
(1–3 sentences)

## Technical Analysis
(detailed explanation with references to the specific code or trace lines that \
support your conclusion)

## Suggested Fix
(concrete steps or code explanation; if the issue is environmental/flaky, \
explain what to monitor instead)

## Unified Diff
```diff
(minimal unified diff patch, or "N/A — no code change needed" if not applicable)
```
"""


def build_user_prompt(
    junit_summary_text: str,
    git_diff: str,
    source_snippets: dict[str, str],
    changed_files: list[str],
) -> str:
    """Assemble the user prompt from all gathered context."""
    parts: list[str] = []

    parts.append(
        "## Failing Tests\n\n"
        + (junit_summary_text or "(no JUnit data available)")
    )

    if changed_files:
        file_list = "\n".join(f"- {f}" for f in changed_files[:20])
        parts.append(f"## Changed Files\n\n{file_list}")

    if git_diff:
        parts.append(f"## Git Diff\n\n```diff\n{git_diff}\n```")

    if source_snippets:
        snippets: list[str] = []
        for path, content in list(source_snippets.items())[:8]:
            # Guess language for syntax highlighting
            ext = path.rsplit(".", 1)[-1] if "." in path else ""
            lang = ext if ext in {"py", "ts", "js", "rs", "go", "c", "cpp", "h"} else ""
            snippets.append(f"### `{path}`\n\n```{lang}\n{content}\n```")
        parts.append("## Relevant Source Files\n\n" + "\n\n".join(snippets))

    parts.append(_OUTPUT_FORMAT_INSTRUCTIONS)

    return "\n\n---\n\n".join(parts)
