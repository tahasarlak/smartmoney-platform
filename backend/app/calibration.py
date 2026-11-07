from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


_BUCKETS = ((0, 49, "weak"), (50, 64, "moderate"), (65, 79, "good"), (80, 100, "strong"))


def _wilson(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 1.0)
    p = wins / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def evaluate_calibration(
    observations: list[dict[str, Any]],
    *,
    min_validation_samples: int = 100,
    min_bucket_samples: int = 30,
) -> dict[str, Any]:
    """Chronological holdout evaluation; never turns quality score into a probability by itself."""
    cleaned = []
    for item in observations:
        score = int(item["quality_score"])
        won = item["won"]
        stamp = str(item.get("closed_at") or item.get("timestamp") or "")
        if not 0 <= score <= 100 or not isinstance(won, bool) or not stamp:
            raise ValueError("Each observation needs score 0..100, boolean won and a timestamp")
        cleaned.append({"quality_score": score, "won": won, "timestamp": stamp})
    cleaned.sort(key=lambda x: x["timestamp"])
    split = int(len(cleaned) * 0.7)
    train, validation = cleaned[:split], cleaned[split:]
    report: dict[str, Any] = {
        "sample_count": len(cleaned),
        "training_sample_count": len(train),
        "validation_sample_count": len(validation),
        "status": "insufficient_out_of_sample_data",
        "buckets": [],
        "brier_score": None,
        "probabilities_available": False,
        "note": "Quality score is not a win probability. Probabilities require a sufficiently large chronological holdout sample.",
    }
    if len(validation) < min_validation_samples:
        return report

    bucket_results = []
    all_bucketed = []
    for low, high, label in _BUCKETS:
        rows = [x for x in validation if low <= x["quality_score"] <= high]
        wins = sum(x["won"] for x in rows)
        total = len(rows)
        result = {
            "label": label, "score_range": [low, high], "sample_count": total,
            "win_rate": None, "confidence_95": None,
        }
        if total >= min_bucket_samples:
            rate = wins / total
            lo, hi = _wilson(wins, total)
            result["win_rate"] = round(rate, 4)
            result["confidence_95"] = [round(lo, 4), round(hi, 4)]
            all_bucketed.extend((x, rate) for x in rows)
        bucket_results.append(result)

    if not all_bucketed:
        report["buckets"] = bucket_results
        report["status"] = "validation_data_not_distributed_across_buckets"
        return report

    # Brier score on only buckets meeting the predeclared minimum sample threshold.
    brier = sum((prob - float(row["won"])) ** 2 for row, prob in all_bucketed) / len(all_bucketed)
    enough = len(all_bucketed) >= min_validation_samples and all(
        (not any(low <= x["quality_score"] <= high for x in validation))
        or next(b for b in bucket_results if b["label"] == label)["win_rate"] is not None
        for low, high, label in _BUCKETS
    )
    report.update({
        "buckets": bucket_results,
        "brier_score": round(brier, 6),
        "status": "empirical_holdout_calibration_available" if enough else "partial_holdout_evidence_only",
        "probabilities_available": bool(enough),
        "note": "Empirical holdout bucket rates only; do not treat as a universal or forward guarantee. Revalidate after strategy or market-regime changes.",
    })
    return report
