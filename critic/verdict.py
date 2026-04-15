"""
6-level VERDICT → DECISION mapping for PCC critic pipeline.

Verdicts:
  PASS           - Output meets all criteria with evidence
  REVIEW         - Output needs human review but may be acceptable
  NEEDS_EVIDENCE - Output claims completion but lacks proof
  NO_OP          - Output made no meaningful changes
  SYCOPHANTIC    - Output is flattery/agreement without substance
  FAIL           - Output has clear errors or violations

Decisions:
  allow  - Accept the output
  review - Queue for human review
  reject - Discard the output
  retry  - Re-run with same or modified prompt
"""

from enum import Enum
from typing import Optional
import re


class Verdict(Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    NO_OP = "NO_OP"
    SYCOPHANTIC = "SYCOPHANTIC"
    FAIL = "FAIL"


class Decision(Enum):
    allow = "allow"
    review = "review"
    reject = "reject"
    retry = "retry"


# Core mapping: verdict → decision
VERDICT_TO_DECISION: dict[Verdict, Decision] = {
    Verdict.PASS: Decision.allow,
    Verdict.REVIEW: Decision.review,
    Verdict.NEEDS_EVIDENCE: Decision.review,
    Verdict.NO_OP: Decision.reject,
    Verdict.SYCOPHANTIC: Decision.reject,
    Verdict.FAIL: Decision.reject,
}

# Error mapping: error type → decision
ERROR_TO_DECISION: dict[str, Decision] = {
    "TIMEOUT": Decision.retry,
    "NOT_FOUND": Decision.reject,
    "RUNTIME_NOT_CONFIGURED": Decision.reject,
    "empty-output": Decision.reject,
    "rate-limited": Decision.retry,
    "context-overflow": Decision.retry,
}

# Sycophantic patterns - if these dominate the output, it's flattery
SYCOPHANTIC_PATTERNS = [
    r"\b(great|excellent|perfect|wonderful|amazing)\s+(job|work|code|implementation)\b",
    r"\blooks?\s+(great|good|perfect|fine)\b",
    r"\bno\s+(issues?|problems?|concerns?)\s+(found|detected|identified)\b",
    r"\beverything\s+(looks?|seems?|appears?)\s+(good|correct|fine)\b",
    r"\bwell[\s-]?(done|written|implemented|structured)\b",
]

# No-op patterns - output acknowledges task but does nothing
NO_OP_PATTERNS = [
    r"\b(no\s+changes?\s+(needed|required|made|necessary))\b",
    r"\b(nothing\s+to\s+(do|change|fix|update))\b",
    r"\b(already\s+(correct|implemented|done|complete))\b",
]


def classify_verdict(raw_output: str) -> tuple[Verdict, float]:
    """
    Classify raw critic output into a Verdict with confidence score.
    
    Returns:
        (Verdict, confidence) where confidence is 0.0-1.0
    """
    if not raw_output or not raw_output.strip():
        return Verdict.FAIL, 1.0
    
    text = raw_output.lower()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    if len(lines) == 0:
        return Verdict.FAIL, 1.0
    
    # Check for sycophantic patterns
    syco_matches = sum(
        1 for pattern in SYCOPHANTIC_PATTERNS
        if re.search(pattern, text, re.IGNORECASE)
    )
    if syco_matches >= 2:
        return Verdict.SYCOPHANTIC, min(0.5 + syco_matches * 0.15, 1.0)
    
    # Check for no-op patterns
    noop_matches = sum(
        1 for pattern in NO_OP_PATTERNS
        if re.search(pattern, text, re.IGNORECASE)
    )
    if noop_matches >= 1 and len(lines) < 5:
        return Verdict.NO_OP, min(0.6 + noop_matches * 0.2, 1.0)
    
    # Check for explicit PASS/FAIL markers
    if re.search(r"\b(PASS|APPROVED|ACCEPTED)\b", raw_output):
        # But verify it has evidence
        has_evidence = (
            re.search(r"\b(test|assert|verify|confirm|check)\b", text) or
            re.search(r"\b(line|file|function|class|method)\b", text)
        )
        if has_evidence:
            return Verdict.PASS, 0.85
        else:
            return Verdict.NEEDS_EVIDENCE, 0.7
    
    if re.search(r"\b(FAIL|REJECT|ERROR|CRITICAL)\b", raw_output):
        return Verdict.FAIL, 0.9
    
    # Check for evidence indicators
    has_specific_refs = bool(re.search(r"(line\s+\d+|file\s+\S+|function\s+\S+)", text))
    has_code_blocks = "```" in raw_output
    has_actionable = bool(re.search(r"\b(should|must|need|fix|change|add|remove)\b", text))
    
    evidence_score = sum([has_specific_refs, has_code_blocks, has_actionable])
    
    if evidence_score >= 2:
        return Verdict.REVIEW, 0.7
    elif evidence_score == 1:
        return Verdict.NEEDS_EVIDENCE, 0.6
    else:
        return Verdict.NEEDS_EVIDENCE, 0.5


def decide(verdict: Verdict) -> Decision:
    """Map a Verdict to its corresponding Decision."""
    return VERDICT_TO_DECISION[verdict]


def decide_error(error_type: str) -> Decision:
    """Map an error type to a Decision."""
    return ERROR_TO_DECISION.get(error_type, Decision.reject)


def process_critic_output(raw_output: str, error_type: Optional[str] = None) -> dict:
    """
    Process raw critic output into a structured result.
    
    Returns:
        {
            "verdict": str,
            "decision": str, 
            "confidence": float,
            "error": str | None
        }
    """
    if error_type:
        decision = decide_error(error_type)
        return {
            "verdict": "ERROR",
            "decision": decision.value,
            "confidence": 1.0,
            "error": error_type,
        }
    
    verdict, confidence = classify_verdict(raw_output)
    decision = decide(verdict)
    
    return {
        "verdict": verdict.value,
        "decision": decision.value,
        "confidence": confidence,
        "error": None,
    }
