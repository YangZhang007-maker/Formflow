"""Tests for workout planner fallback functions (no Gemini needed)."""

from backend.workout_planner import (
    CheckInData,
    ExercisePlan,
    WorkoutPlan,
    _fallback_workout,
    _fallback_warmup,
    _fallback_adapt,
)


class TestCheckInData:
    def test_checkin_data_creation(self):
        checkin = CheckInData(
            goal="strength",
            time_minutes=25,
            equipment="dumbbells",
            energy="medium",
            soreness=["knees"],
        )
        assert checkin.goal == "strength"
        assert checkin.time_minutes == 25
        assert checkin.equipment == "dumbbells"
        assert checkin.energy == "medium"
        assert checkin.soreness == ["knees"]
        d = checkin.to_dict()
        assert d["goal"] == "strength"
        assert d["soreness"] == ["knees"]


class TestFallbackWorkout:
    def test_fallback_workout_no_equipment(self):
        checkin = CheckInData(
            goal="strength",
            time_minutes=25,
            equipment="none",
            energy="medium",
        )
        plan = _fallback_workout(checkin)
        assert isinstance(plan, WorkoutPlan)
        assert len(plan.exercises) >= 3
        assert plan.estimated_minutes == 25
        # Should contain bodyweight exercises
        exercise_names = [e.exercise.lower() for e in plan.exercises]
        assert any("squat" in name for name in exercise_names)
        assert any("push" in name for name in exercise_names)

    def test_fallback_workout_with_dumbbells(self):
        checkin = CheckInData(
            goal="strength",
            time_minutes=30,
            equipment="dumbbells",
            energy="medium",
        )
        plan = _fallback_workout(checkin)
        assert isinstance(plan, WorkoutPlan)
        exercise_names = [e.exercise.lower() for e in plan.exercises]
        assert any("dumbbell" in name or "goblet" in name for name in exercise_names)

    def test_fallback_workout_respects_time(self):
        short = CheckInData(goal="general", time_minutes=15, equipment="none", energy="medium", level="intermediate")
        long = CheckInData(goal="general", time_minutes=45, equipment="none", energy="medium", level="intermediate")

        short_plan = _fallback_workout(short)
        long_plan = _fallback_workout(long)

        assert len(short_plan.exercises) == 3
        assert len(long_plan.exercises) >= 6

    def test_fallback_workout_respects_soreness(self):
        checkin = CheckInData(
            goal="strength",
            time_minutes=25,
            equipment="none",
            energy="medium",
            soreness=["knees"],
        )
        plan = _fallback_workout(checkin)
        exercise_names = [e.exercise.lower() for e in plan.exercises]
        # Should not include lunges (stresses knees)
        assert not any("lunge" in name for name in exercise_names)

    def test_fallback_workout_low_energy(self):
        checkin = CheckInData(
            goal="strength",
            time_minutes=25,
            equipment="none",
            energy="low",
        )
        plan = _fallback_workout(checkin)
        # Low energy should reduce sets/reps
        for ex in plan.exercises:
            assert ex.sets <= 3

    def test_fallback_workout_high_energy(self):
        checkin = CheckInData(
            goal="strength",
            time_minutes=25,
            equipment="none",
            energy="high",
        )
        plan = _fallback_workout(checkin)
        # High energy should increase sets
        for ex in plan.exercises:
            assert ex.sets >= 3


class TestFallbackWarmup:
    def test_fallback_warmup(self):
        warmup = _fallback_warmup()
        assert isinstance(warmup, list)
        assert len(warmup) >= 3
        # Should include generic warmup moves
        warmup_text = " ".join(warmup).lower()
        assert "arm" in warmup_text or "jog" in warmup_text

    def test_fallback_warmup_with_exercises(self):
        exercises = [
            ExercisePlan("Squats", 3, 12, "Keep chest up"),
            ExercisePlan("Push-ups", 3, 10, "Full ROM"),
        ]
        warmup = _fallback_warmup(exercises)
        assert isinstance(warmup, list)
        assert len(warmup) >= 3


class TestExercisePlan:
    def test_exercise_plan_to_dict(self):
        ex = ExercisePlan(
            exercise="Push-ups",
            sets=3,
            reps=12,
            cue="Keep elbows in",
            is_timed=False,
        )
        d = ex.to_dict()
        assert d["exercise"] == "Push-ups"
        assert d["sets"] == 3
        assert d["reps"] == 12
        assert d["cue"] == "Keep elbows in"
        assert d["is_timed"] is False
        assert "duration_seconds" not in d

    def test_exercise_plan_timed_to_dict(self):
        ex = ExercisePlan(
            exercise="Plank",
            sets=3,
            reps=30,
            cue="Hold strong",
            is_timed=True,
        )
        d = ex.to_dict()
        assert d["duration_seconds"] == 30
        assert "reps" not in d
        assert d["is_timed"] is True


class TestWorkoutPlan:
    def test_workout_plan_to_dict(self):
        exercises = [
            ExercisePlan("Squats", 3, 12, "Keep chest up"),
            ExercisePlan("Plank", 3, 30, "Hold tight", is_timed=True),
        ]
        plan = WorkoutPlan(
            exercises=exercises,
            warmup=["Arm circles", "Light jog"],
            estimated_minutes=20,
            focus="General strength",
        )
        d = plan.to_dict()
        assert len(d["exercises"]) == 2
        assert d["warmup"] == ["Arm circles", "Light jog"]
        assert d["estimated_minutes"] == 20
        assert d["focus"] == "General strength"
        # Check nested serialization
        assert d["exercises"][0]["reps"] == 12
        assert d["exercises"][1]["duration_seconds"] == 30


class TestAdaptFallback:
    def test_adapt_fallback(self):
        result = _fallback_adapt("lunges")
        assert "replacement" in result
        assert "reason" in result
        assert "sets" in result
        assert "reps" in result
        assert result["replacement"] == "step-ups"

    def test_adapt_fallback_unknown_exercise(self):
        result = _fallback_adapt("totally_unknown_exercise")
        assert "replacement" in result
        assert "reason" in result
        assert "sets" in result
        assert "reps" in result

    def test_adapt_fallback_push_ups(self):
        result = _fallback_adapt("push-ups")
        assert result["replacement"] == "incline push-ups"

    def test_adapt_fallback_squats(self):
        result = _fallback_adapt("squats")
        assert result["replacement"] == "wall sits"
