import math

def calculate_position_size(account_value: float, risk_pct: float, entry: float, stop: float,
                            cash_per_price_unit_per_lot: float, lot_step: float,
                            min_lot: float, max_lot: float) -> dict:
    distance = abs(entry - stop)
    if distance <= 0:
        raise ValueError("Entry and stop must differ")
    risk_cash = account_value * risk_pct / 100
    loss_per_lot = distance * cash_per_price_unit_per_lot
    raw = risk_cash / loss_per_lot
    lots = math.floor(raw / lot_step) * lot_step
    if lots < min_lot:
        return {"risk_cash": risk_cash, "raw_lots": raw, "lots": 0,
                "executable": False, "reason": "Calculated size is below broker minimum"}
    lots = min(lots, max_lot)
    return {"risk_cash": round(risk_cash, 2), "loss_per_lot": round(loss_per_lot, 6),
            "raw_lots": raw, "lots": round(lots, 8), "executable": True,
            "estimated_stop_loss_cash": round(lots * loss_per_lot, 2)}
