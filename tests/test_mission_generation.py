"""Tests for level-aware, goal-based mission generation."""

from backend.workout_planner import (
    CheckInData, _fallback_workout, _fallback_warmup,
)


class TestBeginnerVsIntermediate:
    def test_beginner_plan_is_simpler(self):
        checkin = CheckInData(
            goal="strength", time_minutes=25, equipment="none",
            energy="medium", soreness=[], level="beginner",
        )
        plan = _fallback_workout(checkin)
        assert len(plan.exercises) <= 3
        # Beginner exercises should be basic
        names = [e.exercise.lower() for e in plan.exercises]
        for name in names:
            assert any(w in name for w in [
                "squat", "push", "plank", "lunge", "bridge",
                "wall", "step", "march", "hold",
            ]), f"'{name}' doesn't look beginner-friendly"

    def test_intermediate_plan_more_exercises(self):
        checkin = CheckInData(
            goal="strength", time_minutes=25, equipment="none",
            energy="medium", soreness=[], level="intermediate",
        )
        plan = _fallback_workout(checkin)
        assert len(plan.exercises) >= 3

    def test_beginner_lower_volume(self):
        beginner = CheckInData(
            goal="strength", time_minutes=25, equipment="none",
            energy="medium", soreness=[], level="beginner",
        )
        intermediate = CheckInData(
            goal="strength", time_minutes=25, equipment="none",
            energy="medium", soreness=[], level="intermediate",
        )
        b_plan = _fallback_workout(beginner)
        i_plan = _fallback_workout(intermediate)

        b_total = sum(e.sets * e.reps for e in b_plan.exercises if not e.is_timed)
        i_total = sum(e.sets * e.reps for e in i_plan.exercises if not e.is_timed)
        assert b_total <= i_total

    def test_low_confidence_simplifies(self):
        checkin = CheckInData(
            goal="strength", time_minutes=25, equipment="dumbbells",
            energy="medium", soreness=[], level="beginner",
            low_confidence=True,
        )
        plan = _fallback_workout(checkin)
        assert len(plan.exercises) <= 3


class TestGoalChanges:
    def test_goal_changes_plan_shape(self):
        strength = CheckInData(
            goal="strength", time_minutes=25, equipment="none",
            energy="medium", soreness=[], level="intermediate",
        )
        endurance = CheckInData(
            goal="endurance", time_minutes=25, equipment="none",
            energy="medium", soreness=[], level="intermediate",
        )
        s_plan = _fallback_workout(strength)
        e_plan = _fallback_workout(endurance)

        # Endurance should have higher reps per exercise on average
        s_avg_reps = sum(e.reps for e in s_plan.exercises if not e.is_timed) / max(1, len([e for e in s_plan.exercises if not e.is_timed]))
        e_avg_reps = sum(e.reps for e in e_plan.exercises if not e.is_timed) / max(1, len([e for e in e_plan.exercises if not e.is_timed]))
        assert e_avg_reps >= s_avg_reps

    def test_quick_session_goal(self):
        checkin = CheckInData(
            goal="quick", time_minutes=15, equipment="none",
            energy="medium", soreness=[], level="beginner",
        )
        plan = _fallback_workout(checkin)
        assert len(plan.exercises) <= 3
        assert plan.estimated_minutes <= 15


class TestContextFlags:
    def test_crowded_gym_avoids_stations(self):
        checkin = CheckInData(
            goal="strength", time_minutes=25, equipment="dumbbells",
            energy="medium", soreness=[], level="intermediate",
            crowded_gym=True,
        )
        plan = _fallback_workout(checkin)
        # Should have exercises — crowded gym shouldn't break generation
        assert len(plan.exercises) >= 2

    def test_equipment_constraints_respected(self):
        checkin = CheckInData(
            goal="strength", time_minutes=25, equipment="none",
            energy="medium", soreness=[], level="intermediate",
        )
        plan = _fallback_workout(checkin)
        # No equipment exercises shouldn't mention dumbbells/barbell
        for ex in plan.exercises:
            lower = ex.exercise.lower()
            assert "dumbbell" not in lower
            assert "barbell" not in lower

    def test_each_exercise_has_cue(self):
        checkin = CheckInData(
            goal="strength", time_minutes=25, equipment="none",
            energy="medium", soreness=[], level="beginner",
        )
        plan = _fallback_workout(checkin)
        for ex in plan.exercises:
            assert ex.cue and len(ex.cue) > 5, f"Exercise '{ex.exercise}' missing cue"


class TestRescue:
    def test_equipment_busy_rescue(self):
        from backend.workout_planner import _fallback_adapt
        result = _fallback_adapt("Dumbbell Press", "equipment_busy")
        assert "replacement" in result
        assert result["replacement"] != "Dumbbell Press"

    def test_low_energy_rescue(self):
        from backend.workout_planner import _fallback_adapt
        result = _fallback_adapt("Squats", "low_energy")
        assert "replacement" in result

    def test_discomfort_rescue(self):
        from backend.workout_planner import _fallback_adapt
        result = _fallback_adapt("Lunges", "discomfort")
        assert "replacement" in result

    def test_dont_know_rescue(self):
        from backend.workout_planner import _fallback_adapt
        result = _fallback_adapt("Bulgarian Split Squat", "dont_know")
        assert "replacement" in result

    def test_rescue_preserves_structure(self):
        from backend.workout_planner import _fallback_adapt
        result = _fallback_adapt("Squats", "equipment_busy")
        assert "sets" in result
        assert "reps" in result
        assert "reason" in result
