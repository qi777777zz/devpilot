from __future__ import annotations

from fastapi.testclient import TestClient

from devpilot.api import create_app
from devpilot.config import Settings


def test_task_runs_through_api(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tasks",
            json={
                "title": "Plan an observability improvement",
                "requirement": (
                    "Inspect the sample repository and produce a traceable implementation plan."
                ),
                "repository_path": ".",
            },
        )
        assert response.status_code == 201
        task_id = response.json()["id"]

        run_response = client.post(f"/api/v1/tasks/{task_id}/run")
        assert run_response.status_code == 202

        detail = client.get(f"/api/v1/tasks/{task_id}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["status"] == "completed"
        assert len(payload["artifacts"]) == 6
        assert payload["artifacts"][-1]["kind"] == "final_report"
        assert any(event["kind"] == "task.completed" for event in payload["events"])


def test_rejects_short_requirement(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/tasks",
            json={"title": "Too short", "requirement": "tiny", "repository_path": "."},
        )
        assert response.status_code == 422
