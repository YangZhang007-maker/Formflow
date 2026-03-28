"""
Anonymous user profile for RepWise.

No auth required — generates a local anonymous ID.
Persists preferences to Firestore for continuity across sessions.
"""

import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


def create_anonymous_id() -> str:
    """Generate a unique anonymous user ID."""
    return f"rw_{uuid.uuid4().hex[:12]}"


@dataclass
class UserProfile:
    user_id: str
    level: str = "beginner"  # beginner / intermediate
    preferred_goal: Optional[str] = None
    preferred_equipment: Optional[str] = None
    crowded_gym: bool = False
    low_confidence: bool = False
    session_count: int = 0
    prior_issues: list = field(default_factory=list)  # unique form issues from past sessions

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "level": self.level,
            "preferred_goal": self.preferred_goal,
            "preferred_equipment": self.preferred_equipment,
            "crowded_gym": self.crowded_gym,
            "low_confidence": self.low_confidence,
            "session_count": self.session_count,
            "prior_issues": self.prior_issues,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserProfile":
        return cls(
            user_id=d.get("user_id", "unknown"),
            level=d.get("level", "beginner"),
            preferred_goal=d.get("preferred_goal"),
            preferred_equipment=d.get("preferred_equipment"),
            crowded_gym=d.get("crowded_gym", False),
            low_confidence=d.get("low_confidence", False),
            session_count=d.get("session_count", 0),
            prior_issues=d.get("prior_issues", []),
        )

    def update_after_session(
        self,
        exercise: str,
        form_issues: list[str],
        goal: str,
        equipment: str,
    ):
        """Update profile after a completed workout session."""
        self.session_count += 1
        self.preferred_goal = goal
        self.preferred_equipment = equipment

        # Add unique form issues
        for issue in form_issues:
            if issue != "good" and issue not in self.prior_issues:
                self.prior_issues.append(issue)

        # Keep only last 10 issues
        self.prior_issues = self.prior_issues[-10:]

    def context_for_generation(self) -> str:
        """Generate context string for Gemini workout planning."""
        parts = [f"Level: {self.level}"]
        parts.append(f"Sessions completed: {self.session_count}")

        if self.session_count == 0:
            parts.append("New user — first session")

        if self.prior_issues:
            parts.append(f"Prior form issues: {', '.join(self.prior_issues)}")

        if self.crowded_gym:
            parts.append("Gym is crowded — prefer exercises that don't need stations")

        if self.low_confidence:
            parts.append("User has low confidence — choose simpler, familiar exercises")

        if self.preferred_goal:
            parts.append(f"Usually trains for: {self.preferred_goal}")

        return " | ".join(parts)
