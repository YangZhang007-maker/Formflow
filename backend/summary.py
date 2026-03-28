"""
Post-workout summary generation using Gemini.
"""

import logging
from google import genai
from backend.config import GOOGLE_API_KEY

logger = logging.getLogger(__name__)


async def generate_coaching_summary(session_summary: dict) -> str:
    """Generate a coaching summary using Gemini (non-streaming, text-only)."""
    if not GOOGLE_API_KEY:
        return _fallback_summary(session_summary)

    prompt = f"""You are Formflow, an AI fitness coach. Generate a brief post-workout debrief.

Workout data:
- Exercise: {session_summary.get('exercise', 'unknown')}
- Total reps: {session_summary.get('total_reps', 0)}
- Duration: {session_summary.get('duration_seconds', 0):.0f} seconds
- Form score: {session_summary.get('form_score', 0)}/10
- Form issues: {session_summary.get('form_issues', {})}

Write 2-3 sentences:
1. Acknowledge the workout (be encouraging)
2. One specific form tip based on the issues (if any)
3. Brief suggestion for next time

Keep it conversational and under 50 words. No bullet points."""

    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        response = await client.aio.models.generate_content(
            model="gemini-1.5-flash-002",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini summary generation failed: {e}")
        return _fallback_summary(session_summary)


def _fallback_summary(session_summary: dict) -> str:
    """Simple fallback when Gemini is unavailable."""
    exercise = session_summary.get("exercise", "workout")
    reps = session_summary.get("total_reps", 0)
    score = session_summary.get("form_score", 0)
    issues = session_summary.get("form_issues", {})

    parts = [f"Great {exercise} session — {reps} reps completed!"]

    if score >= 8:
        parts.append("Your form was solid.")
    elif issues:
        top_issue = max(issues, key=issues.get)
        tip_map = {
            "leaning_forward": "Focus on keeping your chest upright.",
            "not_deep_enough": "Try to get a bit deeper on each rep.",
            "hips_sagging": "Engage your core to keep your hips level.",
            "hips_dropping": "Keep your hips raised throughout.",
            "hips_too_high": "Lower your hips slightly for better form.",
        }
        parts.append(tip_map.get(top_issue, "Keep working on your form!"))

    return " ".join(parts)
