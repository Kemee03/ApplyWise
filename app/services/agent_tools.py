from collections.abc import Sequence


def calculate_fit_metrics(findings: Sequence[dict[str, str]]) -> dict[str, int | None]:
    """Compute match counts and a transparent fit score from model findings."""
    matched = sum(item["match"] == "matched" for item in findings)
    partial = sum(item["match"] == "partial" for item in findings)
    gaps = sum(item["match"] == "gap" for item in findings)
    recognized = len(findings)
    score = None
    if recognized:
        weighted_matches = matched + 0.5 * partial
        score = int((100 * weighted_matches / recognized) + 0.5)
    return {
        "score": score,
        "recognized_requirements": recognized,
        "matched": matched,
        "partial": partial,
        "gaps": gaps,
    }
