"""Tests for anonymous user profile and preferences."""

import pytest
from backend.user_profile import UserProfile, create_anonymous_id


class TestAnonymousId:
    def test_create_anonymous_id(self):
        uid = create_anonymous_id()
        assert isinstance(uid, str)
        assert len(uid) >= 8

    def test_create_unique_ids(self):
        ids = {create_anonymous_id() for _ in range(50)}
        assert len(ids) == 50  # all unique


class TestUserProfile:
    def test_default_profile(self):
        p = UserProfile(user_id="test-123")
        assert p.user_id == "test-123"
        assert p.level == "beginner"
        assert p.preferred_goal is None
        assert p.preferred_equipment is None
        assert p.crowded_gym is False
        assert p.low_confidence is False
        assert p.session_count == 0
        assert p.prior_issues == []

    def test_profile_to_dict(self):
        p = UserProfile(user_id="u1", level="intermediate", preferred_goal="strength")
        d = p.to_dict()
        assert d["user_id"] == "u1"
        assert d["level"] == "intermediate"
        assert d["preferred_goal"] == "strength"

    def test_profile_from_dict(self):
        d = {
            "user_id": "u1",
            "level": "intermediate",
            "preferred_goal": "strength",
            "preferred_equipment": "dumbbells",
            "crowded_gym": True,
            "low_confidence": False,
            "session_count": 5,
            "prior_issues": ["leaning_forward"],
        }
        p = UserProfile.from_dict(d)
        assert p.level == "intermediate"
        assert p.preferred_goal == "strength"
        assert p.crowded_gym is True
        assert p.session_count == 5
        assert p.prior_issues == ["leaning_forward"]

    def test_profile_from_dict_missing_fields(self):
        """Handles partial data gracefully (e.g., old stored profiles)."""
        d = {"user_id": "u1"}
        p = UserProfile.from_dict(d)
        assert p.level == "beginner"
        assert p.session_count == 0

    def test_update_after_session(self):
        p = UserProfile(user_id="u1", session_count=2)
        p.update_after_session(
            exercise="squat",
            form_issues=["leaning_forward", "leaning_forward", "not_deep_enough"],
            goal="strength",
            equipment="none",
        )
        assert p.session_count == 3
        assert "leaning_forward" in p.prior_issues
        assert "not_deep_enough" in p.prior_issues
        assert p.preferred_goal == "strength"
        assert p.preferred_equipment == "none"

    def test_update_keeps_unique_issues(self):
        p = UserProfile(user_id="u1", prior_issues=["leaning_forward"])
        p.update_after_session(
            exercise="squat",
            form_issues=["leaning_forward", "leaning_forward"],
            goal="strength",
            equipment="none",
        )
        # Should not duplicate
        assert p.prior_issues.count("leaning_forward") == 1

    def test_context_for_generation(self):
        p = UserProfile(
            user_id="u1",
            level="beginner",
            session_count=3,
            prior_issues=["leaning_forward"],
        )
        ctx = p.context_for_generation()
        assert "beginner" in ctx.lower()
        assert "3" in ctx
        assert "leaning_forward" in ctx

    def test_context_for_generation_new_user(self):
        p = UserProfile(user_id="u1")
        ctx = p.context_for_generation()
        assert "new user" in ctx.lower() or "0 sessions" in ctx
