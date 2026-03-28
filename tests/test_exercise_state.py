"""Tests for the exercise state model used during live sessions.

This model runs in the frontend (JS), but we test the logic here
as a Python mirror to validate correctness before porting.
"""

import pytest


def get_rest_duration(level: str, goal: str) -> int:
    """Heuristic rest duration in seconds."""
    if goal == "quick":
        return 20
    if level == "beginner":
        return 45 if goal != "strength" else 60
    # intermediate
    if goal == "strength":
        return 90
    return 60


class ExerciseState:
    """Mirror of the frontend exercise state tracker for testing."""

    def __init__(self, exercise: str, target_sets: int, target_reps: int, is_timed: bool = False):
        self.exercise = exercise
        self.target_sets = target_sets
        self.target_reps = target_reps
        self.is_timed = is_timed
        self.current_set = 1
        self.reps_in_set = 0
        self.completed_sets = 0
        self.total_reps = 0
        self.form_issues = []

    def add_rep(self, form_quality: str = "good") -> dict:
        """Record a rep. Returns state change info."""
        result = {"set_complete": False, "exercise_complete": False}

        # Don't accept reps after exercise is fully complete
        if self.completed_sets >= self.target_sets:
            result["exercise_complete"] = True
            return result

        self.reps_in_set += 1
        self.total_reps += 1
        if form_quality != "good":
            self.form_issues.append(form_quality)

        if self.reps_in_set >= self.target_reps:
            self.completed_sets += 1
            result["set_complete"] = True

            if self.completed_sets >= self.target_sets:
                result["exercise_complete"] = True
            else:
                self.current_set += 1
                self.reps_in_set = 0

        return result

    def reset(self, exercise: str, target_sets: int, target_reps: int, is_timed: bool = False):
        """Full reset for new exercise (rescue or next)."""
        self.exercise = exercise
        self.target_sets = target_sets
        self.target_reps = target_reps
        self.is_timed = is_timed
        self.current_set = 1
        self.reps_in_set = 0
        self.completed_sets = 0
        self.total_reps = 0
        self.form_issues = []

    def to_summary(self) -> dict:
        return {
            "exercise": self.exercise,
            "sets_completed": self.completed_sets,
            "total_reps": self.total_reps,
            "form_issues": list(set(self.form_issues)),
        }


class TestSetProgression:
    def test_reps_increment_within_set(self):
        state = ExerciseState("Squats", target_sets=3, target_reps=10)
        for _ in range(5):
            state.add_rep()
        assert state.reps_in_set == 5
        assert state.current_set == 1
        assert state.completed_sets == 0

    def test_set_completes_at_target(self):
        state = ExerciseState("Squats", target_sets=3, target_reps=10)
        for i in range(10):
            result = state.add_rep()
        assert result["set_complete"] is True
        assert result["exercise_complete"] is False
        assert state.completed_sets == 1
        assert state.current_set == 2
        assert state.reps_in_set == 0  # reset for next set

    def test_full_exercise_completion(self):
        state = ExerciseState("Push-ups", target_sets=3, target_reps=12)
        for set_num in range(3):
            for rep in range(12):
                result = state.add_rep()
        assert result["exercise_complete"] is True
        assert state.completed_sets == 3
        assert state.total_reps == 36

    def test_reps_reset_per_set(self):
        state = ExerciseState("Squats", target_sets=3, target_reps=5)
        for _ in range(5):
            state.add_rep()
        assert state.reps_in_set == 0  # reset after set 1
        assert state.current_set == 2
        state.add_rep()
        assert state.reps_in_set == 1
        assert state.current_set == 2

    def test_never_exceeds_target_sets(self):
        state = ExerciseState("Squats", target_sets=2, target_reps=5)
        for _ in range(10):
            state.add_rep()
        assert state.completed_sets == 2
        # After completion, further reps don't advance sets
        result = state.add_rep()
        assert state.completed_sets == 2


class TestExerciseCompletion:
    def test_single_set_exercise(self):
        state = ExerciseState("Plank", target_sets=1, target_reps=30, is_timed=True)
        for _ in range(30):
            result = state.add_rep()
        assert result["set_complete"] is True
        assert result["exercise_complete"] is True

    def test_form_issues_tracked(self):
        state = ExerciseState("Squats", target_sets=3, target_reps=5)
        state.add_rep("good")
        state.add_rep("leaning_forward")
        state.add_rep("good")
        state.add_rep("leaning_forward")
        assert state.form_issues == ["leaning_forward", "leaning_forward"]
        assert state.total_reps == 4


class TestRescueReset:
    def test_reset_clears_all_state(self):
        state = ExerciseState("Squats", target_sets=3, target_reps=10)
        for _ in range(15):
            state.add_rep()
        assert state.total_reps == 15

        state.reset("Wall Sit", target_sets=2, target_reps=20, is_timed=True)
        assert state.exercise == "Wall Sit"
        assert state.current_set == 1
        assert state.reps_in_set == 0
        assert state.completed_sets == 0
        assert state.total_reps == 0
        assert state.form_issues == []
        assert state.is_timed is True

    def test_reset_preserves_nothing_from_old(self):
        state = ExerciseState("Squats", target_sets=3, target_reps=10)
        state.add_rep("leaning_forward")
        state.reset("Push-ups", 3, 12)
        assert len(state.form_issues) == 0
        assert state.total_reps == 0


class TestRestState:
    def test_set_complete_blocks_reps(self):
        """After set complete, if we mark resting, addRep should be guarded by caller."""
        state = ExerciseState("Squats", target_sets=3, target_reps=5)
        for _ in range(5):
            state.add_rep()
        # Set 1 complete, reps reset
        assert state.completed_sets == 1
        assert state.reps_in_set == 0
        # Caller should check phase before calling addRep

    def test_rest_duration_beginner(self):
        """Beginner rest should be 45-60s."""
        rest = get_rest_duration("beginner", "general")
        assert 45 <= rest <= 60

    def test_rest_duration_intermediate_strength(self):
        rest = get_rest_duration("intermediate", "strength")
        assert 75 <= rest <= 120

    def test_rest_duration_quick(self):
        rest = get_rest_duration("beginner", "quick")
        assert rest <= 30


class TestSummaryGrounding:
    def test_summary_after_partial_exercise(self):
        state = ExerciseState("Squats", target_sets=3, target_reps=10)
        for _ in range(7):
            state.add_rep("good")
        summary = state.to_summary()
        assert summary["exercise"] == "Squats"
        assert summary["sets_completed"] == 0
        assert summary["total_reps"] == 7
        assert summary["form_issues"] == []

    def test_summary_after_full_exercise(self):
        state = ExerciseState("Push-ups", target_sets=3, target_reps=5)
        for _ in range(15):
            state.add_rep("good")
        summary = state.to_summary()
        assert summary["sets_completed"] == 3
        assert summary["total_reps"] == 15

    def test_summary_with_form_issues(self):
        state = ExerciseState("Squats", target_sets=2, target_reps=5)
        state.add_rep("good")
        state.add_rep("leaning_forward")
        state.add_rep("good")
        summary = state.to_summary()
        assert "leaning_forward" in summary["form_issues"]
        assert summary["total_reps"] == 3
