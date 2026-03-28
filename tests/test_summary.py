"""Tests for post-workout summary generation."""

import pytest
from backend.summary import _fallback_summary


class TestFallbackSummary:
    def test_good_form(self):
        summary = _fallback_summary({
            "exercise": "squat",
            "total_reps": 10,
            "form_score": 9.0,
            "form_issues": {},
        })
        assert "squat" in summary
        assert "10 reps" in summary
        assert "solid" in summary

    def test_with_leaning_forward(self):
        summary = _fallback_summary({
            "exercise": "squat",
            "total_reps": 8,
            "form_score": 5.0,
            "form_issues": {"leaning_forward": 3},
        })
        assert "chest upright" in summary

    def test_with_not_deep_enough(self):
        summary = _fallback_summary({
            "exercise": "squat",
            "total_reps": 12,
            "form_score": 6.0,
            "form_issues": {"not_deep_enough": 4},
        })
        assert "deeper" in summary

    def test_with_hips_sagging(self):
        summary = _fallback_summary({
            "exercise": "pushup",
            "total_reps": 15,
            "form_score": 4.0,
            "form_issues": {"hips_sagging": 8},
        })
        assert "core" in summary

    def test_multiple_issues_picks_most_common(self):
        summary = _fallback_summary({
            "exercise": "squat",
            "total_reps": 10,
            "form_score": 5.0,
            "form_issues": {"leaning_forward": 2, "not_deep_enough": 5},
        })
        # not_deep_enough has more occurrences
        assert "deeper" in summary

    def test_no_reps(self):
        summary = _fallback_summary({
            "exercise": "plank",
            "total_reps": 0,
            "form_score": 0,
            "form_issues": {},
        })
        assert "plank" in summary
