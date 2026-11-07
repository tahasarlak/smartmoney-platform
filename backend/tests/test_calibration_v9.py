from app.calibration import evaluate_calibration


def test_small_sample_never_claims_probability():
    rows = [
        {"quality_score": 70, "won": i % 2 == 0, "closed_at": f"2026-01-{i+1:02d}"}
        for i in range(20)
    ]
    result = evaluate_calibration(rows)
    assert result["probabilities_available"] is False
    assert result["status"] == "insufficient_out_of_sample_data"


def test_large_chronological_holdout_produces_bucket_evidence():
    rows = []
    for i in range(400):
        bucket = i % 4
        score = [25, 57, 72, 90][bucket]
        rows.append({
            "quality_score": score,
            "won": (i % 5) != 0,
            "closed_at": f"2026-{1 + i // 300:02d}-{1 + i % 28:02d}T{i:04d}",
        })
    result = evaluate_calibration(rows, min_validation_samples=100, min_bucket_samples=20)
    assert result["validation_sample_count"] == 120
    assert result["probabilities_available"] is True
    assert result["brier_score"] is not None
