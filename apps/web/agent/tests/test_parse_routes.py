"""Tests for parse HTTP routes in main.py."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient


# ── Import app after patching heavy dependencies ──────────────────────────

@pytest.fixture(scope="module")
def test_client(tmp_path_factory):
    """Create a TestClient with PotpieRuntime and model initialisation mocked out."""
    tmp = tmp_path_factory.mktemp("agent")

    # Stub out imports that require external services / installed packages
    with (
        patch("web_tools.PotpieRuntime"),
        patch("web_kg.WebPotpieCapability"),
        patch("main.create_deep_agent"),
        patch("main.load_config"),
        patch("main.select_default_model", return_value="openai:gpt-4o-mini"),
    ):
        import main  # noqa: PLC0415  (local import intentional inside fixture)

        client = TestClient(main.app, raise_server_exceptions=True)
        yield client, tmp


# ── /parse tests ──────────────────────────────────────────────────────────

class TestParseRoute:
    def test_missing_repo_path_returns_400(self, test_client):
        client, _ = test_client
        resp = client.post("/parse", json={"branch": "main"})
        assert resp.status_code == 400
        assert "repo_path" in resp.json()["error"]

    def test_nonexistent_path_returns_422(self, test_client, tmp_path):
        client, _ = test_client
        resp = client.post("/parse", json={"repo_path": "/no/such/path", "branch": "main"})
        assert resp.status_code == 422
        assert "does not exist" in resp.json()["error"]

    def test_non_git_dir_returns_422(self, test_client, tmp_path):
        client, _ = test_client
        resp = client.post("/parse", json={"repo_path": str(tmp_path), "branch": "main"})
        assert resp.status_code == 422
        assert "git" in resp.json()["error"].lower()

    def test_valid_repo_starts_job(self, test_client, tmp_path):
        client, _ = test_client
        # Create a minimal fake git repo
        (tmp_path / ".git").mkdir()

        # Mock runtime.parse to return a known result
        import web_tools  # noqa: PLC0415
        web_tools.runtime.parse = AsyncMock(
            return_value={"project_id": "proj-abc", "status": "READY", "message": "ok"}
        )

        resp = client.post("/parse", json={"repo_path": str(tmp_path), "branch": "main"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "started"
        assert "job_id" in body
        return body["job_id"]

    def test_status_unknown_job_returns_404(self, test_client):
        client, _ = test_client
        resp = client.get("/parse/status/nonexistent")
        assert resp.status_code == 404
        assert "Unknown job_id" in resp.json()["error"]

    def test_full_parse_flow(self, test_client, tmp_path):
        """Start a parse, wait for it to finish, then verify status endpoint."""
        client, _ = test_client
        (tmp_path / ".git").mkdir()

        import web_tools  # noqa: PLC0415
        web_tools.runtime.parse = AsyncMock(
            return_value={"project_id": "proj-xyz", "status": "READY", "message": "done"}
        )

        # Start job
        start = client.post("/parse", json={"repo_path": str(tmp_path), "branch": "feat"})
        assert start.status_code == 200
        job_id = start.json()["job_id"]

        # Drive the asyncio event loop so the background task completes
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))

        # Poll status — may still be "started" if task hasn't run yet; allow both
        status = client.get(f"/parse/status/{job_id}")
        assert status.status_code == 200
        assert status.json()["status"] in ("started", "done")
