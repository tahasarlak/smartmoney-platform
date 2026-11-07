from app.risk import calculate_position_size

def test_position_size_respects_risk():
    result = calculate_position_size(10000, 1, 100, 98, 1, 0.01, 0.01, 100)
    assert result["executable"]
    assert result["estimated_stop_loss_cash"] <= 100
