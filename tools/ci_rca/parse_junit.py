"""JUnit XML parser for CI RCA context collection.

Supports multiple JUnit XML files, tolerates malformed XML, and extracts
failing test names, stack traces, assertion messages, and durations.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestFailure:
    """A single failed or errored test case."""

    suite_name: str
    test_name: str
    classname: str
    duration: float
    failure_type: str  # "failure" | "error" | "skipped"
    message: str
    text: str  # Full stack trace / body text


@dataclass
class JUnitSummary:
    """Aggregated summary from one or more JUnit XML files."""

    total: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    duration: float = 0.0
    failed_tests: list[TestFailure] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)


def _truncate_text(text: str, max_chars: int) -> str:
    """Truncate long text, keeping head and tail for context."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n...[truncated]...\n" + text[-half:]


def _parse_suite(suite: ET.Element) -> list[TestFailure]:
    """Extract failures from a single <testsuite> element."""
    failures: list[TestFailure] = []
    suite_name = suite.get("name", "unknown")

    for testcase in suite.findall("testcase"):
        test_name = testcase.get("name", "unknown")
        classname = testcase.get("classname", "")
        duration = float(testcase.get("time", "0") or "0")

        for fail_type in ("failure", "error", "skipped"):
            elem = testcase.find(fail_type)
            if elem is not None:
                message = elem.get("message", "") or ""
                text = elem.text or ""
                failures.append(
                    TestFailure(
                        suite_name=suite_name,
                        test_name=test_name,
                        classname=classname,
                        duration=duration,
                        failure_type=fail_type,
                        message=_truncate_text(message, 500),
                        text=_truncate_text(text, 3000),
                    )
                )
                break  # Only record the first failure element per testcase

    return failures


def parse_junit_file(path: Path) -> list[TestFailure]:
    """Parse a single JUnit XML file and return failed test cases."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        print(f"WARNING: Failed to parse {path}: {exc}")
        return []
    except OSError as exc:
        print(f"WARNING: Could not read {path}: {exc}")
        return []

    root = tree.getroot()

    if root.tag == "testsuites":
        suites = root.findall("testsuite")
    elif root.tag == "testsuite":
        suites = [root]
    else:
        suites = root.findall(".//testsuite")

    failures: list[TestFailure] = []
    for suite in suites:
        failures.extend(_parse_suite(suite))
    return failures


def _extract_source_refs(stack_traces: list[str]) -> list[str]:
    """Extract Python file paths referenced in stack traces."""
    files: dict[str, None] = {}  # Ordered set via dict
    for trace in stack_traces:
        for line in trace.splitlines():
            line = line.strip()
            # Matches: File "/path/to/foo.py", line 42
            m = re.search(r'"([^"]+\.py)"', line)
            if m:
                files[m.group(1)] = None
                continue
            # Matches: /path/to/foo.py:42 or relative/foo.py:42
            m = re.search(r'([\w./][^\s"\']*\.py):\d+', line)
            if m:
                files[m.group(1)] = None
    return list(files)


def collect_junit_failures(junit_dirs: list[Path]) -> JUnitSummary:
    """Collect and aggregate all JUnit failures from the given directories."""
    summary = JUnitSummary()
    seen: set[Path] = set()

    for junit_dir in junit_dirs:
        if not junit_dir.exists():
            continue
        for xml_file in sorted(junit_dir.glob("**/*.xml")):
            if xml_file in seen:
                continue
            seen.add(xml_file)

            # Aggregate suite-level counts
            try:
                tree = ET.parse(xml_file)
                root = tree.getroot()
                suites = (
                    root.findall(".//testsuite")
                    if root.tag == "testsuites"
                    else [root]
                    if root.tag == "testsuite"
                    else root.findall(".//testsuite")
                )
                for suite in suites:
                    summary.total += int(suite.get("tests", "0") or "0")
                    summary.failures += int(suite.get("failures", "0") or "0")
                    summary.errors += int(suite.get("errors", "0") or "0")
                    summary.skipped += int(suite.get("skipped", "0") or "0")
                    summary.duration += float(suite.get("time", "0") or "0")
            except (ET.ParseError, ValueError, OSError):
                pass

            summary.failed_tests.extend(parse_junit_file(xml_file))

    # Deduplicate source files referenced in all stack traces
    summary.source_files = _extract_source_refs(
        [ft.text for ft in summary.failed_tests]
    )
    return summary
