"""Tests for session REST APIs."""

import pytest
from fastapi.testclient import TestClient

# Patch Firestore and ADK before importing app
import sys
from unittest.mock import MagicMock, AsyncMock

# Mock google.cloud.firestore so it doesn't try to connect
mock_firestore = MagicMock()
sys.modules["google.cloud.firestore"] = mock_firestore

from backend.main import app, session_mgr


@pytest.fixture(autouse=True)
def reset_sessions():
    """Reset session manager between tests."""
    session_mgr._sessions.clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


class TestStartSession:
    def test_start_session(self, client):
        resp = client.post("/session/start", json={
            "user_id": "user-1",
            "exercise": "squat",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["exercise"] == "squat"
        assert "start_time" in data

    def test_start_session_pushup(self, client):
        resp = client.post("/session/start", json={
            "user_id": "user-1",
            "exercise": "pushup",
        })
        assert resp.status_code == 200
        assert resp.json()["exercise"] == "pushup"

    def test_start_session_missing_fields(self, client):
        resp = client.post("/session/start", json={"user_id": "user-1"})
        assert resp.status_code == 422  # validation error


class TestRecordRep:
    def test_record_rep(self, client):
        # Start session first
        start = client.post("/session/start", json={
            "user_id": "user-1", "exercise": "squat"
        }).json()

        resp = client.post("/session/rep", json={
            "session_id": start["session_id"],
            "form_quality": "good",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["rep_number"] == 1
        assert data["total_reps"] == 1
        assert data["form_score"] == 10.0

    def test_record_multiple_reps(self, client):
        start = client.post("/session/start", json={
            "user_id": "user-1", "exercise": "squat"
        }).json()
        sid = start["session_id"]

        client.post("/session/rep", json={"session_id": sid, "form_quality": "good"})
        client.post("/session/rep", json={"session_id": sid, "form_quality": "leaning_forward"})
        resp = client.post("/session/rep", json={"session_id": sid, "form_quality": "good"})

        data = resp.json()
        assert data["rep_number"] == 3
        assert data["total_reps"] == 3
        assert data["form_score"] == 6.7  # 2/3 good

    def test_record_rep_invalid_session(self, client):
        resp = client.post("/session/rep", json={
            "session_id": "nonexistent",
            "form_quality": "good",
        })
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestEndSession:
    def test_end_session(self, client):
        start = client.post("/session/start", json={
            "user_id": "user-1", "exercise": "squat"
        }).json()
        sid = start["session_id"]

        client.post("/session/rep", json={"session_id": sid, "form_quality": "good"})
        client.post("/session/rep", json={"session_id": sid, "form_quality": "good"})

        resp = client.post("/session/end", json={"session_id": sid})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_reps"] == 2
        assert data["form_score"] == 10.0
        assert data["exercise"] == "squat"
        assert "duration_seconds" in data
        assert "form_issues" in data

    def test_end_session_with_issues(self, client):
        start = client.post("/session/start", json={
            "user_id": "user-1", "exercise": "squat"
        }).json()
        sid = start["session_id"]

        client.post("/session/rep", json={"session_id": sid, "form_quality": "good"})
        client.post("/session/rep", json={"session_id": sid, "form_quality": "leaning_forward"})
        client.post("/session/rep", json={"session_id": sid, "form_quality": "leaning_forward"})

        data = client.post("/session/end", json={"session_id": sid}).json()
        assert data["form_issues"] == {"leaning_forward": 2}
        assert data["form_score"] == 3.3  # 1/3

    def test_end_nonexistent_session(self, client):
        resp = client.post("/session/end", json={"session_id": "nope"})
        assert "error" in resp.json()

    def test_end_session_twice(self, client):
        start = client.post("/session/start", json={
            "user_id": "user-1", "exercise": "squat"
        }).json()
        sid = start["session_id"]

        client.post("/session/end", json={"session_id": sid})
        resp = client.post("/session/end", json={"session_id": sid})
        assert "error" in resp.json()


class TestGetSession:
    def test_get_active_session(self, client):
        start = client.post("/session/start", json={
            "user_id": "user-1", "exercise": "plank"
        }).json()

        resp = client.get(f"/session/{start['session_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["exercise"] == "plank"
        assert data["is_active"] is True
        assert data["total_reps"] == 0

    def test_get_nonexistent_session(self, client):
        resp = client.get("/session/nope")
        assert "error" in resp.json()
