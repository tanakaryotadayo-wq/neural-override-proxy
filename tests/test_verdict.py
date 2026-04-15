"""Tests for critic/verdict.py — 6-level VERDICT classification."""

import pytest
from critic.verdict import (
    Verdict,
    Decision,
    VERDICT_TO_DECISION,
    ERROR_TO_DECISION,
    classify_verdict,
    decide,
    decide_error,
    process_critic_output,
)


class TestVerdictMapping:
    """Test VERDICT → DECISION mapping completeness."""

    def test_all_verdicts_mapped(self):
        for v in Verdict:
            assert v in VERDICT_TO_DECISION, f"Verdict {v} not in mapping"

    def test_pass_allows(self):
        assert decide(Verdict.PASS) == Decision.allow

    def test_review_reviews(self):
        assert decide(Verdict.REVIEW) == Decision.review

    def test_needs_evidence_reviews(self):
        assert decide(Verdict.NEEDS_EVIDENCE) == Decision.review

    def test_no_op_rejects(self):
        assert decide(Verdict.NO_OP) == Decision.reject

    def test_sycophantic_rejects(self):
        assert decide(Verdict.SYCOPHANTIC) == Decision.reject

    def test_fail_rejects(self):
        assert decide(Verdict.FAIL) == Decision.reject


class TestErrorMapping:
    """Test error → decision mapping."""

    def test_timeout_retries(self):
        assert decide_error("TIMEOUT") == Decision.retry

    def test_not_found_rejects(self):
        assert decide_error("NOT_FOUND") == Decision.reject

    def test_runtime_not_configured_rejects(self):
        assert decide_error("RUNTIME_NOT_CONFIGURED") == Decision.reject

    def test_empty_output_rejects(self):
        assert decide_error("empty-output") == Decision.reject

    def test_unknown_error_rejects(self):
        assert decide_error("UNKNOWN_ERROR") == Decision.reject


class TestClassifyVerdict:
    """Test automatic verdict classification from raw output."""

    def test_empty_output_fails(self):
        verdict, conf = classify_verdict("")
        assert verdict == Verdict.FAIL
        assert conf == 1.0

    def test_none_output_fails(self):
        verdict, conf = classify_verdict("")
        assert verdict == Verdict.FAIL

    def test_sycophantic_detection(self):
        output = "Great job! The code looks perfect. Well done, excellent implementation!"
        verdict, conf = classify_verdict(output)
        assert verdict == Verdict.SYCOPHANTIC

    def test_sycophantic_needs_multiple_patterns(self):
        output = "The code looks good but there are issues on line 42."
        verdict, _ = classify_verdict(output)
        assert verdict != Verdict.SYCOPHANTIC

    def test_no_op_detection(self):
        output = "No changes needed."
        verdict, _ = classify_verdict(output)
        assert verdict == Verdict.NO_OP

    def test_pass_with_evidence(self):
        output = "PASS. Tests verified on line 42. Function compute_hash works correctly."
        verdict, _ = classify_verdict(output)
        assert verdict == Verdict.PASS

    def test_pass_without_evidence_needs_evidence(self):
        output = "PASS. Everything is fine."
        verdict, _ = classify_verdict(output)
        assert verdict == Verdict.NEEDS_EVIDENCE

    def test_fail_detection(self):
        output = "FAIL: Critical error in authentication logic."
        verdict, _ = classify_verdict(output)
        assert verdict == Verdict.FAIL

    def test_review_with_specifics(self):
        output = "Found potential issue on line 55. The function should handle null input. ```python\ndef fix(): pass\n```"
        verdict, _ = classify_verdict(output)
        assert verdict == Verdict.REVIEW

    def test_confidence_between_0_and_1(self):
        test_cases = [
            "",
            "Great job! Looks perfect! Well done!",
            "No changes needed.",
            "PASS with test verification on line 10",
            "FAIL: broken",
        ]
        for case in test_cases:
            _, conf = classify_verdict(case)
            assert 0.0 <= conf <= 1.0, f"Confidence {conf} out of range for: {case!r}"


class TestProcessCriticOutput:
    """Test the full processing pipeline."""

    def test_normal_output(self):
        result = process_critic_output("PASS. Tests verified on line 42.")
        assert result["verdict"] in [v.value for v in Verdict]
        assert result["decision"] in [d.value for d in Decision]
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["error"] is None

    def test_error_overrides(self):
        result = process_critic_output("some output", error_type="TIMEOUT")
        assert result["decision"] == "retry"
        assert result["error"] == "TIMEOUT"

    def test_empty_output_error(self):
        result = process_critic_output("", error_type="empty-output")
        assert result["decision"] == "reject"

    def test_result_structure(self):
        result = process_critic_output("Review needed: file utils.py has issues")
        assert "verdict" in result
        assert "decision" in result
        assert "confidence" in result
        assert "error" in result
