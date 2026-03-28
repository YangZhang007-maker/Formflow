"""
Session management for RepWise workouts.

Tracks workout sessions in-memory during active use,
persists to Firestore on session end.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RepEvent:
    rep_number: int
    timestamp: float
    form_quality: str  # "good", "leaning_forward", "not_deep_enough", etc.

    def to_dict(self):
        return {
            "rep_number": self.rep_number,
            "timestamp": self.timestamp,
            "form_quality": self.form_quality,
        }


@dataclass
class WorkoutSession:
    session_id: str
    user_id: str
    exercise: str
    start_time: float
    end_time: Optional[float] = None
    rep_events: list = field(default_factory=list)
    coaching_summary: Optional[str] = None
    current_exercise_index: int = 0
    workout_plan: Optional[list] = None  # list of exercise dicts

    @property
    def total_reps(self) -> int:
        return len(self.rep_events)

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or time.time()
        return round(end - self.start_time, 1)

    @property
    def form_score(self) -> float:
        """Score 0-10 based on percentage of reps with good form."""
        if not self.rep_events:
            return 0.0
        good_reps = sum(1 for r in self.rep_events if r.form_quality == "good")
        return round((good_reps / len(self.rep_events)) * 10, 1)

    @property
    def is_active(self) -> bool:
        return self.end_time is None

    def add_rep(self, form_quality: str = "good") -> RepEvent:
        """Record a new rep event."""
        rep = RepEvent(
            rep_number=self.total_reps + 1,
            timestamp=time.time(),
            form_quality=form_quality,
        )
        self.rep_events.append(rep)
        return rep

    def end(self) -> dict:
        """End the session and return summary."""
        self.end_time = time.time()
        return self.summary()

    def summary(self) -> dict:
        """Generate workout summary."""
        form_issues = {}
        for r in self.rep_events:
            if r.form_quality != "good":
                form_issues[r.form_quality] = form_issues.get(r.form_quality, 0) + 1

        return {
            "session_id": self.session_id,
            "exercise": self.exercise,
            "total_reps": self.total_reps,
            "duration_seconds": self.duration_seconds,
            "form_score": self.form_score,
            "form_issues": form_issues,
            "coaching_summary": self.coaching_summary,
        }

    def to_firestore_dict(self) -> dict:
        """Serialize for Firestore storage."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "exercise": self.exercise,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_reps": self.total_reps,
            "duration_seconds": self.duration_seconds,
            "form_score": self.form_score,
            "rep_events": [r.to_dict() for r in self.rep_events],
            "coaching_summary": self.coaching_summary,
        }

    def set_workout_plan(self, exercises: list[dict]) -> None:
        """Set the workout plan and reset exercise index."""
        self.workout_plan = exercises
        self.current_exercise_index = 0

    def current_exercise(self) -> Optional[dict]:
        """Get the current exercise from the workout plan."""
        if not self.workout_plan:
            return None
        if self.current_exercise_index >= len(self.workout_plan):
            return None
        return self.workout_plan[self.current_exercise_index]

    def next_exercise(self) -> Optional[dict]:
        """Peek at the next exercise without advancing."""
        if not self.workout_plan:
            return None
        next_idx = self.current_exercise_index + 1
        if next_idx >= len(self.workout_plan):
            return None
        return self.workout_plan[next_idx]

    def advance_to_next_exercise(self) -> Optional[dict]:
        """Advance to the next exercise and return it."""
        if not self.workout_plan:
            return None
        self.current_exercise_index += 1
        if self.current_exercise_index >= len(self.workout_plan):
            return None
        return self.workout_plan[self.current_exercise_index]

    def context_for_agent(self) -> str:
        """Generate context string for Gemini agent."""
        form_issues = {}
        for r in self.rep_events:
            if r.form_quality != "good":
                form_issues[r.form_quality] = form_issues.get(r.form_quality, 0) + 1

        latest_form = self.rep_events[-1].form_quality if self.rep_events else "none"
        issue_summary = ", ".join(f"{k}: {v}x" for k, v in form_issues.items()) if form_issues else "none"

        return (
            f"Exercise: {self.exercise} | "
            f"Reps: {self.total_reps} | "
            f"Duration: {self.duration_seconds}s | "
            f"Form score: {self.form_score}/10 | "
            f"Latest form: {latest_form} | "
            f"Issues: {issue_summary}"
        )


class SessionManager:
    """In-memory session store. Active sessions live here, completed ones go to Firestore."""

    def __init__(self):
        self._sessions: dict[str, WorkoutSession] = {}

    def start_session(self, user_id: str, exercise: str) -> WorkoutSession:
        session_id = str(uuid.uuid4())[:8]
        session = WorkoutSession(
            session_id=session_id,
            user_id=user_id,
            exercise=exercise,
            start_time=time.time(),
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[WorkoutSession]:
        return self._sessions.get(session_id)

    def add_rep(self, session_id: str, form_quality: str = "good") -> Optional[RepEvent]:
        session = self._sessions.get(session_id)
        if session and session.is_active:
            return session.add_rep(form_quality)
        return None

    def end_session(self, session_id: str) -> Optional[dict]:
        session = self._sessions.get(session_id)
        if session and session.is_active:
            return session.end()
        return None

    def get_active_sessions(self) -> list[WorkoutSession]:
        return [s for s in self._sessions.values() if s.is_active]
