"""Deterministic checks for evidence citations and computed fit metrics."""

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from app.services.agent_tools import calculate_fit_metrics


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def audit_analysis_quality(
    analysis: Mapping[str, Any],
    profile_skills: str,
    experience_evidence: str,
) -> dict[str, Any]:
    """Check verbatim evidence citations and recompute the displayed score without an LLM call."""
    result = dict(analysis)
    findings = [dict(item) for item in result.get("skills", [])]
    source = _normalize(experience_evidence)
    checked_quotes = 0
    verified_quotes = 0
    unverified_skills: list[str] = []
    matched_without_verified_evidence: list[str] = []

    for finding in findings:
        verified_for_finding = 0
        for quote in finding.get("evidence", []):
            checked_quotes += 1
            if _normalize(str(quote)) and _normalize(str(quote)) in source:
                verified_quotes += 1
                verified_for_finding += 1
            else:
                unverified_skills.append(str(finding.get("skill", "Unlabeled requirement")))
        if finding.get("match") == "matched" and verified_for_finding == 0:
            matched_without_verified_evidence.append(str(finding.get("skill", "Unlabeled requirement")))

    expected_metrics = calculate_fit_metrics(findings)
    metric_fields = ("score", "recognized_requirements", "matched", "partial", "gaps")
    supplied_metric_fields = [field for field in metric_fields if field in result]
    metrics_were_consistent = not supplied_metric_fields or all(
        result[field] == expected_metrics[field] for field in supplied_metric_fields
    )
    result.update(expected_metrics)
    result["skills"] = findings

    warnings = []
    if unverified_skills:
        warnings.append("Some evidence excerpts could not be matched verbatim to the saved experience.")
    if matched_without_verified_evidence:
        warnings.append("Some requirements are marked matched without a verifiable experience excerpt.")
    if not metrics_were_consistent:
        warnings.append("Fit totals did not match the requirement labels and were corrected.")

    result["quality_checks"] = {
        "status": "review" if warnings else "checked",
        "evidence_quotes_checked": checked_quotes,
        "evidence_quotes_verified": verified_quotes,
        "evidence_quotes_unverified": checked_quotes - verified_quotes,
        "matched_without_verified_evidence": len(matched_without_verified_evidence),
        "score_recalculated": not metrics_were_consistent,
        "warnings": warnings,
        "scope": "Checks exact evidence quotes and score arithmetic; it does not prove semantic relevance or predict hiring outcomes.",
    }
    return result
