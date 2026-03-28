"""
Workout planning module for RepWise.

Uses Gemini 2.5 Flash to generate structured workout plans based on
pre-workout check-in data. Falls back to sensible defaults when Gemini
is unavailable.
"""

import json
import logging
from dataclasses import dataclass, field

from google import genai

from backend.config import GOOGLE_API_KEY

logger = logging.getLogger(__name__)

client = genai.Client(api_key=GOOGLE_API_KEY)

PLANNING_MODEL = "gemini-1.5-flash-002"

# Body part to exercise mapping for soreness filtering
SORENESS_EXERCISE_MAP = {
    "knees": ["lunges", "jump squats", "box jumps", "pistol squats"],
    "shoulders": ["overhead press", "military press", "lateral raises", "arnold press"],
    "back": ["deadlifts", "bent-over rows", "good mornings"],
    "wrists": ["push-ups", "handstand", "wrist curls"],
    "ankles": ["jump squats", "box jumps", "calf raises", "jump rope"],
    "hips": ["lunges", "hip thrusts", "sumo squats"],
    "elbows": ["bicep curls", "tricep extensions", "skull crushers"],
    "neck": ["overhead press", "shrugs"],
}

# Fallback swap table for adapt_exercise
SWAP_TABLE = {
    "lunges": {"replacement": "step-ups", "reason": "lower knee stress", "sets": 3, "reps": 10},
    "squats": {"replacement": "wall sits", "reason": "static hold is gentler on joints", "sets": 3, "reps": 30},
    "jump squats": {"replacement": "bodyweight squats", "reason": "removes impact", "sets": 3, "reps": 12},
    "push-ups": {"replacement": "incline push-ups", "reason": "reduces wrist and shoulder load", "sets": 3, "reps": 10},
    "overhead press": {"replacement": "lateral raises", "reason": "less shoulder impingement risk", "sets": 3, "reps": 12},
    "deadlifts": {"replacement": "glute bridges", "reason": "easier on the lower back", "sets": 3, "reps": 12},
    "burpees": {"replacement": "mountain climbers", "reason": "lower impact alternative", "sets": 3, "reps": 15},
    "pull-ups": {"replacement": "resistance band rows", "reason": "easier progression", "sets": 3, "reps": 10},
    "plank": {"replacement": "dead bug", "reason": "less wrist strain", "sets": 3, "reps": 10},
    "bent-over rows": {"replacement": "seated rows", "reason": "less lower back stress", "sets": 3, "reps": 10},
}


@dataclass
class CheckInData:
    goal: str  # strength, endurance, flexibility, general, quick
    time_minutes: int
    equipment: str  # none, dumbbells, barbell, resistance_bands, kettlebell
    energy: str  # low, medium, high
    soreness: list[str] = field(default_factory=list)  # body parts
    target_muscles: list[str] = field(default_factory=list)  # Target muscle groups
    level: str = "beginner"  # beginner / intermediate
    crowded_gym: bool = False
    low_confidence: bool = False
    user_context: str = ""  # from UserProfile.context_for_generation()

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "time_minutes": self.time_minutes,
            "equipment": self.equipment,
            "energy": self.energy,
            "soreness": self.soreness,
            "target_muscles": self.target_muscles,
            "level": self.level,
            "crowded_gym": self.crowded_gym,
            "low_confidence": self.low_confidence,
        }


@dataclass
class ExercisePlan:
    exercise: str
    sets: int
    reps: int  # or duration_seconds for timed exercises
    cue: str  # one coaching tip
    is_timed: bool = False  # False for reps, True for plank/holds

    def to_dict(self) -> dict:
        result = {
            "exercise": self.exercise,
            "sets": self.sets,
            "cue": self.cue,
            "is_timed": self.is_timed,
        }
        if self.is_timed:
            result["duration_seconds"] = self.reps
        else:
            result["reps"] = self.reps
        return result


@dataclass
class WorkoutPlan:
    exercises: list[ExercisePlan]
    warmup: list[str]
    estimated_minutes: int
    focus: str  # brief description
    env_scan_result: str = ""  # AI environment analysis (optional)

    def to_dict(self) -> dict:
        result = {
            "exercises": [e.to_dict() for e in self.exercises],
            "warmup": self.warmup,
            "estimated_minutes": self.estimated_minutes,
            "focus": self.focus,
        }
        if self.env_scan_result:
            result["env_scan_result"] = self.env_scan_result
        return result


def _exercise_count_for_time(time_minutes: int) -> int:
    """Determine number of exercises based on available time."""
    if time_minutes <= 15:
        return 3
    elif time_minutes <= 25:
        return 4
    elif time_minutes <= 35:
        return 5
    elif time_minutes <= 45:
        return 6
    else:
        return 7


def _is_exercise_safe(exercise_name: str, soreness: list[str]) -> bool:
    """Check if an exercise is safe given sore body parts."""
    exercise_lower = exercise_name.lower()
    for sore_part in soreness:
        sore_lower = sore_part.lower()
        blocked = SORENESS_EXERCISE_MAP.get(sore_lower, [])
        for blocked_ex in blocked:
            if blocked_ex.lower() in exercise_lower or exercise_lower in blocked_ex.lower():
                return False
    return True


def _filter_for_soreness(exercises: list[ExercisePlan], soreness: list[str]) -> list[ExercisePlan]:
    """Remove exercises that stress sore body parts."""
    if not soreness:
        return exercises
    return [e for e in exercises if _is_exercise_safe(e.exercise, soreness)]


def _fallback_workout(checkin: CheckInData, env_scan_result: str = "") -> WorkoutPlan:
    """Generate a sensible fallback workout when Gemini is unavailable."""
    num_exercises = _exercise_count_for_time(checkin.time_minutes)

    # Beginner caps: max 3 exercises, simpler movements
    if checkin.level == "beginner":
        num_exercises = min(num_exercises, 3)

    # Low confidence: further restrict
    if checkin.low_confidence:
        num_exercises = min(num_exercises, 3)

    # Quick session goal
    if checkin.goal == "quick":
        num_exercises = min(num_exercises, 3)

    # Build exercise pools by equipment and goal
    pool: list[ExercisePlan] = []

    if checkin.equipment == "none":
        if checkin.goal == "strength":
            pool = [
                ExercisePlan("Bodyweight squats", 3, 15, "Keep chest up and weight in heels"),
                ExercisePlan("Push-ups", 3, 12, "Elbows at 45 degrees, full range of motion"),
                ExercisePlan("Plank", 3, 30, "Keep hips level, engage your core", is_timed=True),
                ExercisePlan("Lunges", 3, 12, "Step far enough that both knees hit 90 degrees"),
                ExercisePlan("Glute bridges", 3, 15, "Squeeze at the top for a full second"),
                ExercisePlan("Tricep dips", 3, 10, "Keep elbows pointing straight back"),
                ExercisePlan("Superman holds", 3, 20, "Lift arms and legs simultaneously", is_timed=True),
            ]
        elif checkin.goal == "endurance":
            pool = [
                ExercisePlan("Jumping jacks", 3, 30, "Land softly on the balls of your feet"),
                ExercisePlan("High knees", 3, 30, "Drive knees above hip height", is_timed=True),
                ExercisePlan("Mountain climbers", 3, 30, "Keep hips low and move quickly", is_timed=True),
                ExercisePlan("Burpees", 3, 10, "Explode up from the bottom"),
                ExercisePlan("Squat jumps", 3, 12, "Land softly with bent knees"),
                ExercisePlan("Plank jacks", 3, 20, "Keep your core tight throughout"),
                ExercisePlan("Running in place", 3, 45, "Pump your arms to keep momentum", is_timed=True),
            ]
        elif checkin.goal == "flexibility":
            pool = [
                ExercisePlan("Deep squat hold", 3, 30, "Push knees out with your elbows", is_timed=True),
                ExercisePlan("Standing forward fold", 3, 30, "Bend from hips, not lower back", is_timed=True),
                ExercisePlan("Pigeon stretch", 3, 30, "Keep hips square to the ground", is_timed=True),
                ExercisePlan("Cat-cow stretches", 3, 10, "Move slowly through full range"),
                ExercisePlan("World's greatest stretch", 3, 8, "Open chest toward the ceiling"),
                ExercisePlan("Seated hamstring stretch", 3, 30, "Hinge at hips, reach for toes", is_timed=True),
            ]
        else:  # general
            pool = [
                ExercisePlan("Bodyweight squats", 3, 15, "Keep chest up and weight in heels"),
                ExercisePlan("Push-ups", 3, 10, "Full range of motion, elbows at 45 degrees"),
                ExercisePlan("Plank", 3, 30, "Engage core, keep body in a straight line", is_timed=True),
                ExercisePlan("Lunges", 3, 10, "Step far enough for 90-degree angles"),
                ExercisePlan("Mountain climbers", 3, 20, "Keep hips level with shoulders"),
                ExercisePlan("Glute bridges", 3, 12, "Squeeze glutes at the top"),
                ExercisePlan("Jumping jacks", 3, 20, "Stay light on your feet"),
            ]

    elif checkin.equipment == "dumbbells":
        if checkin.goal == "strength":
            pool = [
                ExercisePlan("Goblet squats", 3, 12, "Hold dumbbell close to chest, sit deep"),
                ExercisePlan("Dumbbell bench press", 3, 10, "Lower slowly, press explosively"),
                ExercisePlan("Dumbbell rows", 3, 10, "Pull elbow past your torso"),
                ExercisePlan("Dumbbell lunges", 3, 10, "Keep torso upright throughout"),
                ExercisePlan("Dumbbell shoulder press", 3, 10, "Press straight up, don't arch back"),
                ExercisePlan("Dumbbell Romanian deadlift", 3, 10, "Hinge at hips, slight knee bend"),
                ExercisePlan("Dumbbell bicep curls", 3, 12, "No swinging, control the movement"),
            ]
        elif checkin.goal == "endurance":
            pool = [
                ExercisePlan("Dumbbell thrusters", 3, 15, "One fluid movement from squat to press"),
                ExercisePlan("Dumbbell swings", 3, 15, "Drive with your hips, not arms"),
                ExercisePlan("Renegade rows", 3, 10, "Minimize hip rotation"),
                ExercisePlan("Dumbbell snatch", 3, 10, "Explosive hip extension"),
                ExercisePlan("Dumbbell step-ups", 3, 12, "Drive through the front heel"),
                ExercisePlan("Dumbbell clean and press", 3, 10, "Catch at shoulder height"),
            ]
        else:  # general or flexibility
            pool = [
                ExercisePlan("Goblet squats", 3, 12, "Hold dumbbell close to chest"),
                ExercisePlan("Dumbbell rows", 3, 10, "Squeeze shoulder blades together"),
                ExercisePlan("Dumbbell shoulder press", 3, 10, "Full lockout at the top"),
                ExercisePlan("Dumbbell Romanian deadlift", 3, 10, "Feel the hamstring stretch"),
                ExercisePlan("Dumbbell lateral raises", 3, 12, "Slight bend in elbows"),
                ExercisePlan("Dumbbell lunges", 3, 10, "Alternate legs each rep"),
            ]

    elif checkin.equipment == "barbell":
        pool = [
            ExercisePlan("Barbell squats", 4, 8, "Break at hips first, then knees"),
            ExercisePlan("Barbell bench press", 4, 8, "Retract shoulder blades, arch slightly"),
            ExercisePlan("Barbell deadlift", 4, 6, "Push the floor away with your feet"),
            ExercisePlan("Barbell overhead press", 3, 8, "Squeeze glutes for stability"),
            ExercisePlan("Barbell rows", 3, 8, "Pull to lower chest"),
            ExercisePlan("Barbell hip thrust", 3, 10, "Full lockout at the top"),
            ExercisePlan("Barbell lunges", 3, 8, "Control the descent"),
        ]

    elif checkin.equipment == "resistance_bands":
        pool = [
            ExercisePlan("Banded squats", 3, 15, "Push knees out against the band"),
            ExercisePlan("Banded rows", 3, 12, "Squeeze shoulder blades at the end"),
            ExercisePlan("Banded press", 3, 12, "Controlled movement both ways"),
            ExercisePlan("Banded pull-aparts", 3, 15, "Keep arms straight"),
            ExercisePlan("Banded lateral walks", 3, 12, "Stay in a half-squat position"),
            ExercisePlan("Banded glute bridges", 3, 15, "Push knees apart at the top"),
            ExercisePlan("Banded bicep curls", 3, 12, "Control the eccentric"),
        ]

    elif checkin.equipment == "full_gym":
        if checkin.goal in ("strength", "general"):
            pool = [
                ExercisePlan("Barbell squats", 4, 8, "Break at hips first, then knees"),
                ExercisePlan("Bench press", 4, 8, "Retract shoulder blades, controlled descent"),
                ExercisePlan("Lat pulldown", 3, 10, "Pull to upper chest, squeeze lats"),
                ExercisePlan("Leg press", 3, 12, "Full range, don't lock knees"),
                ExercisePlan("Cable rows", 3, 10, "Squeeze shoulder blades together"),
                ExercisePlan("Dumbbell shoulder press", 3, 10, "Press straight up, don't arch"),
                ExercisePlan("Leg curls", 3, 12, "Control the eccentric"),
                ExercisePlan("Cable flyes", 3, 12, "Slight bend in elbows throughout"),
            ]
        else:  # endurance / flexibility
            pool = [
                ExercisePlan("Treadmill incline walk", 3, 60, "3-4% incline, brisk pace", is_timed=True),
                ExercisePlan("Rowing machine", 3, 45, "Drive with legs first", is_timed=True),
                ExercisePlan("Leg press", 3, 15, "Lighter weight, higher reps"),
                ExercisePlan("Cable rows", 3, 15, "Smooth, controlled rhythm"),
                ExercisePlan("Lat pulldown", 3, 12, "Full stretch at the top"),
                ExercisePlan("Step-ups", 3, 12, "Alternate legs, steady pace"),
                ExercisePlan("Plank", 3, 45, "Engage everything", is_timed=True),
            ]

    elif checkin.equipment == "minimal":
        # Minimal = a few dumbbells + a bench or similar
        pool = [
            ExercisePlan("Goblet squats", 3, 12, "Hold weight close to chest"),
            ExercisePlan("Dumbbell rows", 3, 10, "One arm at a time, brace on bench"),
            ExercisePlan("Push-ups", 3, 12, "Hands shoulder-width, full range"),
            ExercisePlan("Dumbbell lunges", 3, 10, "Step far, torso upright"),
            ExercisePlan("Dumbbell shoulder press", 3, 10, "Seated or standing"),
            ExercisePlan("Plank", 3, 30, "Core tight, body straight", is_timed=True),
            ExercisePlan("Dumbbell Romanian deadlift", 3, 10, "Hinge at hips, feel hamstrings"),
        ]

    elif checkin.equipment == "kettlebell":
        pool = [
            ExercisePlan("Kettlebell swings", 3, 15, "Snap hips forward, don't squat"),
            ExercisePlan("Kettlebell goblet squats", 3, 12, "Keep elbows inside knees"),
            ExercisePlan("Kettlebell Turkish get-up", 3, 3, "Move slowly through each position"),
            ExercisePlan("Kettlebell clean and press", 3, 8, "Smooth transition at the rack"),
            ExercisePlan("Kettlebell rows", 3, 10, "Pull to hip, not chest"),
            ExercisePlan("Kettlebell deadlift", 3, 10, "Hinge at hips, flat back"),
            ExercisePlan("Kettlebell halo", 3, 10, "Keep the bell close to your head"),
        ]

    else:
        # Default bodyweight
        pool = [
            ExercisePlan("Bodyweight squats", 3, 15, "Keep chest up"),
            ExercisePlan("Push-ups", 3, 10, "Full range of motion"),
            ExercisePlan("Plank", 3, 30, "Hold strong", is_timed=True),
            ExercisePlan("Lunges", 3, 10, "Alternate legs"),
            ExercisePlan("Glute bridges", 3, 12, "Squeeze at the top"),
        ]

    # Filter for soreness
    safe_pool = _filter_for_soreness(pool, checkin.soreness)
    if len(safe_pool) < num_exercises:
        safe_pool = pool[:num_exercises]  # fallback to original if too filtered

    # Adjust for energy level
    selected = safe_pool[:num_exercises]
    if checkin.energy == "low":
        for ex in selected:
            if not ex.is_timed:
                ex.reps = max(5, ex.reps - 4)
            else:
                ex.reps = max(15, ex.reps - 10)
            ex.sets = max(2, ex.sets - 1)
    elif checkin.energy == "high":
        for ex in selected:
            if not ex.is_timed:
                ex.reps = ex.reps + 3
            else:
                ex.reps = ex.reps + 10
            ex.sets = min(5, ex.sets + 1)

    # Beginner volume reduction
    if checkin.level == "beginner":
        for ex in selected:
            if not ex.is_timed:
                ex.reps = max(5, ex.reps - 2)
            ex.sets = max(2, ex.sets)

    # Build focus description
    focus = f"{checkin.goal.capitalize()} workout"
    if checkin.equipment != "none":
        focus += f" with {checkin.equipment.replace('_', ' ')}"
    if checkin.soreness:
        focus += f", avoiding {', '.join(checkin.soreness)}"

    warmup = _fallback_warmup(selected)

    return WorkoutPlan(
        exercises=selected,
        warmup=warmup,
        estimated_minutes=checkin.time_minutes,
        focus=focus,
        env_scan_result=env_scan_result,
    )


def _fallback_warmup(exercises: list[ExercisePlan] | None = None) -> list[str]:
    """Generate a generic warmup based on exercises."""
    warmup = ["10 arm circles (each direction)", "20 seconds of light jogging in place"]

    if not exercises:
        warmup.extend(["10 bodyweight squats", "10 leg swings each side"])
        return warmup

    exercise_names = [e.exercise.lower() for e in exercises]
    has_lower = any(
        w in name
        for name in exercise_names
        for w in ["squat", "lunge", "deadlift", "swing", "step", "bridge", "thrust"]
    )
    has_upper = any(
        w in name
        for name in exercise_names
        for w in ["press", "push", "row", "curl", "raise", "pull"]
    )

    if has_lower:
        warmup.append("10 bodyweight squats")
    if has_upper:
        warmup.append("10 arm circles and shoulder rolls")
    if not has_lower and not has_upper:
        warmup.append("10 bodyweight squats")

    return warmup


def _fallback_adapt(exercise: str, reason: str = "general") -> dict:
    """Fallback exercise adaptation using a simple swap table."""
    exercise_lower = exercise.lower()

    # Reason-specific logic
    if reason == "low_energy" or reason == "easier":
        return {
            "replacement": "Wall Sit" if "squat" in exercise_lower else "Incline Push-ups",
            "reason": "easier variation to conserve energy",
            "sets": 2,
            "reps": 10 if "squat" not in exercise_lower else 20,
        }

    if reason == "discomfort":
        return {
            "replacement": "Glute Bridges" if "squat" in exercise_lower or "lunge" in exercise_lower else "Dead Bug",
            "reason": "low-impact alternative to avoid discomfort",
            "sets": 3,
            "reps": 10,
        }

    if reason == "dont_know":
        return {
            "replacement": "Bodyweight Squats" if "squat" not in exercise_lower else "Push-ups",
            "reason": "simple, familiar movement",
            "sets": 3,
            "reps": 10,
        }

    if reason == "running_out_of_time":
        return {
            "replacement": exercise,
            "reason": "keeping current exercise, reducing volume",
            "sets": 2,
            "reps": 8,
        }

    # Default: check swap table
    for key, swap in SWAP_TABLE.items():
        if key in exercise_lower or exercise_lower in key:
            return swap

    # Generic fallback
    return {
        "replacement": "Bodyweight Squats",
        "reason": "safe general alternative",
        "sets": 3,
        "reps": 12,
    }


def _get_prompt_parts(checkin: CheckInData):
    """Build shared prompt components from check-in data."""
    num_exercises = _exercise_count_for_time(checkin.time_minutes)

    level_guide = ""
    if checkin.level == "beginner":
        level_guide = "This is a BEGINNER user. Use simple, familiar exercises. Max 3 exercises. Lower volume. More explanation in cues. Avoid complex movements."
    else:
        level_guide = "This is an INTERMEDIATE user. Use performance-oriented exercises. Good volume. Concise coaching cues."

    context_line = f"\nUser context: {checkin.user_context}" if checkin.user_context else ""
    crowded_line = "\nGym is CROWDED — prefer exercises that don't need shared equipment/stations." if checkin.crowded_gym else ""
    confidence_line = "\nUser has LOW CONFIDENCE — choose simple, well-known exercises only." if checkin.low_confidence else ""
    target_line = f"\nTarget Muscles: Focus heavily on {', '.join(checkin.target_muscles)}." if checkin.target_muscles else ""
    return num_exercises, level_guide, context_line, crowded_line, confidence_line, target_line


async def _analyze_environment(image_paths: list[str]) -> str:
    """Stage 1: Use Gemini Vision to identify equipment and space from multiple snapshots."""
    logging.info(f"Stage 1: Analyzing environment gallery ({len(image_paths)} images)")
    try:
        # Upload all images concurrently
        upload_tasks = [client.aio.files.upload(file=path) for path in image_paths]
        uploaded_images = await asyncio.gather(*upload_tasks)

        prompt = """Analyze these sequential snapshots of a workout space. 
        List ALL exercise equipment you see (dumbbells, kettlebells, mats, chairs, pull-up bars, gym machines, etc.). 
        If you see no equipment, say 'Bodyweight only'. 
        Be concise and list only the equipment names."""

        # Combine items for content: [img1, img2, ..., prompt]
        contents = list(uploaded_images) + [prompt]

        response = await client.aio.models.generate_content(
            model=PLANNING_MODEL,
            contents=contents,
        )
        result = response.text.strip()
        logging.info(f"Stage 1 Result: {result}")
        return result
    except Exception as e:
        logger.error(f"Stage 1 Vision error: {e}")
        return "Bodyweight"


async def generate_workout(checkin: CheckInData, image_paths: list[str] = None) -> WorkoutPlan:
    """Generate a structured workout plan using Gemini based on checkin data and optional image gallery."""
    num_exercises, level_guide, context_line, crowded_line, confidence_line, target_line = _get_prompt_parts(checkin)
    
    env_summary = ""
    if image_paths and len(image_paths) > 0:
        env_summary = await _analyze_environment(image_paths)
        logging.info(f"Stage 1 Result: {env_summary}")
        logging.info(f"Stage 1 Result: {env_summary}")

    vision_context = f"\nENVIRONMENT SCAN RESULT: {env_summary}\n(Priority: Use the equipment seen in the scan above over any other setting!)" if env_summary else ""

    prompt = f"""Generate a {checkin.time_minutes}-minute {checkin.goal} workout plan based on the user's criteria.

{level_guide}

CRITICAL: Return ONLY a valid JSON object. No conversational text.
Equipment setting: {checkin.equipment}{vision_context}
Energy level: {checkin.energy}
Sore body parts to avoid: {', '.join(checkin.soreness) if checkin.soreness else 'none'}
Number of exercises: {num_exercises}{target_line}{context_line}{crowded_line}{confidence_line}

Return ONLY valid JSON with this exact structure:
{{
  "exercises": [
    {{
      "exercise": "Exercise Name",
      "sets": 3,
      "reps": 12,
      "cue": "One short coaching tip",
      "is_timed": false
    }}
  ],
  "warmup": ["warmup move 1", "warmup move 2", "warmup move 3"],
  "estimated_minutes": {checkin.time_minutes},
  "focus": "Brief workout description"
}}

For timed exercises (planks, holds), set is_timed to true and use reps as duration_seconds.
Do NOT include exercises that stress these body parts: {', '.join(checkin.soreness) if checkin.soreness else 'none'}.
Adjust intensity based on energy level ({checkin.energy}).
"""

    try:
        response = await client.aio.models.generate_content(
            model=PLANNING_MODEL,
            contents=prompt,
        )
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)

        exercises = []
        for ex in data.get("exercises", []):
            # Robust key mapping for common Gemini variations
            name = ex.get("exercise") or ex.get("name") or ex.get("exercise_name") or "Unknown Exercise"
            sets = ex.get("sets") or ex.get("set_count") or 3
            reps = ex.get("reps") or ex.get("reps_count") or ex.get("duration_seconds") or ex.get("duration") or 12
            cue = ex.get("cue") or ex.get("tip") or ex.get("coaching_tip") or "Maintain good form"
            
            exercises.append(ExercisePlan(
                exercise=str(name),
                sets=int(sets),
                reps=int(reps),
                cue=str(cue),
                is_timed=bool(ex.get("is_timed", False)),
            ))
            
        if not exercises:
             logger.warning("Gemini returned empty exercise list, using fallback")
             return _fallback_workout(checkin)

        return WorkoutPlan(
            exercises=exercises,
            warmup=data.get("warmup", _fallback_warmup(exercises)),
            estimated_minutes=data.get("estimated_minutes", checkin.time_minutes),
            focus=data.get("focus", f"{checkin.goal} workout"),
            env_scan_result=env_summary if env_summary else "",
        )

    except Exception as e:
        logger.warning(f"Gemini workout generation failed, using fallback: {e}")
        return _fallback_workout(checkin, env_scan_result=env_summary)


async def generate_warmup(exercises: list[ExercisePlan]) -> list[str]:
    """Generate warmup moves based on the exercises using Gemini."""
    exercise_names = [e.exercise for e in exercises]

    prompt = f"""Generate 3-4 warmup moves to prepare for these exercises: {', '.join(exercise_names)}.

Return ONLY a JSON array of strings, e.g.:
["10 arm circles each direction", "10 bodyweight squats", "20 second jog in place"]
"""

    try:
        response = await client.aio.models.generate_content(
            model=PLANNING_MODEL,
            contents=prompt,
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        warmup = json.loads(text)
        if isinstance(warmup, list) and all(isinstance(w, str) for w in warmup):
            return warmup
        raise ValueError("Invalid warmup format from Gemini")

    except Exception as e:
        logger.warning(f"Gemini warmup generation failed, using fallback: {e}")
        return _fallback_warmup(exercises)


async def adapt_exercise(current_exercise: str, reason: str, context: str) -> dict:
    """Suggest a replacement exercise using Gemini."""
    prompt = f"""The user needs to replace "{current_exercise}" because: {reason}.
Workout context: {context}

Return ONLY valid JSON:
{{
  "replacement": "exercise name",
  "reason": "brief explanation",
  "sets": 3,
  "reps": 10
}}
"""

    try:
        response = await client.aio.models.generate_content(
            model=PLANNING_MODEL,
            contents=prompt,
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)
        required_keys = {"replacement", "reason", "sets", "reps"}
        if required_keys.issubset(result.keys()):
            return result
        raise ValueError("Missing keys in Gemini adapt response")

    except Exception as e:
        logger.warning(f"Gemini adapt failed, using fallback: {e}")
        return _fallback_adapt(current_exercise, reason)
