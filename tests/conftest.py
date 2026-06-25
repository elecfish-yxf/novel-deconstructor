"""
Pytest fixtures for API integration tests.
Run against the running backend (default http://localhost:8000).
"""
import os
import pytest
import httpx
from typing import Generator

BASE_URL = os.environ.get("TEST_API_BASE", "http://localhost:8000")
WORKSPACE_ID = os.environ.get("TEST_WORKSPACE_ID", "anonymous")


@pytest.fixture(scope="session")
def client() -> Generator[httpx.Client, None, None]:
    """HTTP client connected to the backend."""
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


@pytest.fixture(scope="session")
def auth_headers(client: httpx.Client) -> dict[str, str]:
    """Auth headers for workspace-scoped requests."""
    # Try to register/login to get a token
    try:
        resp = client.post("/api/auth/register", json={
            "email": "test_ci@example.com",
            "password": "test_ci_12345678",
            "display_name": "CI Test User",
        })
        if resp.status_code == 200:
            data = resp.json()
            return {"Authorization": f"Bearer {data['access_token']}"}
    except Exception:
        pass

    # Fall back to workspace ID header
    return {"X-Workspace-Id": WORKSPACE_ID}


@pytest.fixture(scope="session")
def test_kb_id(client: httpx.Client, auth_headers: dict[str, str]) -> int:
    """Get or create a test knowledge base."""
    # List existing
    resp = client.get("/api/knowledge-bases", headers=auth_headers)
    if resp.status_code == 200:
        bases = resp.json()
        if bases:
            return bases[0]["id"]

    # Create new
    resp = client.post("/api/knowledge-bases", json={
        "name": "CI Test KB",
        "description": "Auto-created for integration tests",
    }, headers=auth_headers)
    assert resp.status_code == 200, f"Failed to create test KB: {resp.text}"
    return resp.json()["id"]
