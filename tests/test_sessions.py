"""Tests for session management."""

import time
from backend.sessions import WorkoutSession, SessionManager, RepEvent


class TestRepEvent:
    def test_rep_event_creation(self):
        rep = RepEvent(rep_number=1, timestamp=time.time(), form_quality="good")
        assert rep.rep_number == 1
        assert rep.form_quality == "good"

    def test_rep_event_to_dict(self):
        ts = time.time()
        rep = RepEvent(rep_number=3, timestamp=ts, form_quality="leaning_forward")
        d = rep.to_dict()
        assert d["rep_number"] == 3
        assert d["timestamp"] == ts
        assert d["form_quality"] == "leaning_forward"


class TestWorkoutSession:
    def _make_session(self, exercise="squat"):
        return WorkoutSession(
            session_id="test-123",
            user_id="user-1",
            exercise=exercise,
            start_time=time.time(),
        )

    def test_session_creation(self):
        s = self._make_session()
        assert s.session_id == "test-123"
        assert s.exercise == "squat"
        assert s.total_reps == 0
        assert s.is_active is True

    def test_add_rep(self):
        s = self._make_session()
        rep = s.add_rep("good")
        assert rep.rep_number == 1
        assert s.total_reps == 1

    def test_add_multiple_reps(self):
        s = self._make_session()
        s.add_rep("good")
        s.add_rep("leaning_forward")
        s.add_rep("good")
        assert s.total_reps == 3

    def test_form_score_all_good(self):
        s = self._make_session()
        for _ in range(5):
            s.add_rep("good")
        assert s.form_score == 10.0

    def test_form_score_mixed(self):
        s = self._make_session()
        s.add_rep("good")
        s.add_rep("good")
        s.add_rep("leaning_forward")
        s.add_rep("good")
        # 3/4 good = 7.5
        assert s.form_score == 7.5

    def test_form_score_all_bad(self):
        s = self._make_session()
        s.add_rep("leaning_forward")
        s.add_rep("not_deep_enough")
        assert s.form_score == 0.0

    def test_form_score_no_reps(self):
        s = self._make_session()
        assert s.form_score == 0.0

    def test_duration(self):
        s = self._make_session()
        s.start_time = time.time() - 30  # started 30s ago
        assert s.duration_seconds >= 29.0

    def test_end_session(self):
        s = self._make_session()
        s.add_rep("good")
        s.add_rep("good")
        summary = s.end()
        assert s.is_active is False
        assert summary["total_reps"] == 2
        assert summary["form_score"] == 10.0
        assert "session_id" in summary

    def test_summary_with_form_issues(self):
        s = self._make_session()
        s.add_rep("good")
        s.add_rep("leaning_forward")
        s.add_rep("leaning_forward")
        s.add_rep("good")
        summary = s.end()
        assert summary["form_issues"] == {"leaning_forward": 2}

    def test_firestore_dict(self):
        s = self._make_session()
        s.add_rep("good")
        d = s.to_firestore_dict()
        assert d["session_id"] == "test-123"
        assert d["user_id"] == "user-1"
        assert d["exercise"] == "squat"
        assert len(d["rep_events"]) == 1
        assert d["total_reps"] == 1

    def test_context_for_agent(self):
        s = self._make_session()
        s.add_rep("good")
        s.add_rep("leaning_forward")
        ctx = s.context_for_agent()
        assert "squat" in ctx
        assert "Reps: 2" in ctx
        assert "leaning_forward" in ctx

    def test_context_for_agent_no_reps(self):
        s = self._make_session()
        ctx = s.context_for_agent()
        assert "Reps: 0" in ctx
        assert "Latest form: none" in ctx


class TestWorkoutPlanMethods:
    def _make_session(self, exercise="squat"):
        return WorkoutSession(
            session_id="test-wp",
            user_id="user-1",
            exercise=exercise,
            start_time=time.time(),
        )

    def test_set_workout_plan(self):
        s = self._make_session()
        exercises = [
            {"exercise": "squats", "sets": 3, "reps": 12},
            {"exercise": "push-ups", "sets": 3, "reps": 10},
            {"exercise": "plank", "sets": 3, "duration_seconds": 30},
        ]
        s.set_workout_plan(exercises)
        assert s.workout_plan == exercises
        assert s.current_exercise_index == 0

    def test_current_exercise(self):
        s = self._make_session()
        s.set_workout_plan([
            {"exercise": "squats", "sets": 3, "reps": 12},
            {"exercise": "push-ups", "sets": 3, "reps": 10},
        ])
        current = s.current_exercise()
        assert current is not None
        assert current["exercise"] == "squats"

    def test_current_exercise_no_plan(self):
        s = self._make_session()
        assert s.current_exercise() is None

    def test_next_exercise(self):
        s = self._make_session()
        s.set_workout_plan([
            {"exercise": "squats", "sets": 3, "reps": 12},
            {"exercise": "push-ups", "sets": 3, "reps": 10},
        ])
        nxt = s.next_exercise()
        assert nxt is not None
        assert nxt["exercise"] == "push-ups"
        # Should not have advanced
        assert s.current_exercise_index == 0

    def test_next_exercise_at_end(self):
        s = self._make_session()
        s.set_workout_plan([{"exercise": "squats", "sets": 3, "reps": 12}])
        assert s.next_exercise() is None

    def test_advance_exercise(self):
        s = self._make_session()
        s.set_workout_plan([
            {"exercise": "squats", "sets": 3, "reps": 12},
            {"exercise": "push-ups", "sets": 3, "reps": 10},
            {"exercise": "plank", "sets": 3, "duration_seconds": 30},
        ])
        advanced = s.advance_to_next_exercise()
        assert advanced is not None
        assert advanced["exercise"] == "push-ups"
        assert s.current_exercise_index == 1

    def test_advance_past_end(self):
        s = self._make_session()
        s.set_workout_plan([
            {"exercise": "squats", "sets": 3, "reps": 12},
        ])
        result = s.advance_to_next_exercise()
        assert result is None
        assert s.current_exercise_index == 1
        # Advancing again should still return None
        result2 = s.advance_to_next_exercise()
        assert result2 is None


class TestSessionManager:
    def test_start_session(self):
        mgr = SessionManager()
        session = mgr.start_session("user-1", "squat")
        assert session.is_active
        assert session.exercise == "squat"
        assert session.user_id == "user-1"

    def test_get_session(self):
        mgr = SessionManager()
        session = mgr.start_session("user-1", "pushup")
        found = mgr.get_session(session.session_id)
        assert found is session

    def test_get_nonexistent_session(self):
        mgr = SessionManager()
        assert mgr.get_session("nope") is None

    def test_add_rep(self):
        mgr = SessionManager()
        session = mgr.start_session("user-1", "squat")
        rep = mgr.add_rep(session.session_id, "good")
        assert rep is not None
        assert rep.rep_number == 1
        assert session.total_reps == 1

    def test_add_rep_nonexistent_session(self):
        mgr = SessionManager()
        assert mgr.add_rep("nope", "good") is None

    def test_end_session(self):
        mgr = SessionManager()
        session = mgr.start_session("user-1", "squat")
        mgr.add_rep(session.session_id, "good")
        mgr.add_rep(session.session_id, "good")
        summary = mgr.end_session(session.session_id)
        assert summary is not None
        assert summary["total_reps"] == 2
        assert not session.is_active

    def test_end_session_twice(self):
        mgr = SessionManager()
        session = mgr.start_session("user-1", "squat")
        mgr.end_session(session.session_id)
        assert mgr.end_session(session.session_id) is None

    def test_add_rep_to_ended_session(self):
        mgr = SessionManager()
        session = mgr.start_session("user-1", "squat")
        mgr.end_session(session.session_id)
        assert mgr.add_rep(session.session_id, "good") is None

    def test_active_sessions(self):
        mgr = SessionManager()
        s1 = mgr.start_session("user-1", "squat")
        s2 = mgr.start_session("user-1", "pushup")
        mgr.end_session(s1.session_id)
        active = mgr.get_active_sessions()
        assert len(active) == 1
        assert active[0].session_id == s2.session_id
