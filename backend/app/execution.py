from uuid import uuid4

def create_paper_order(payload: dict) -> dict:
    if payload["side"] == "buy" and not payload["stop_loss"] < payload["entry"] < payload["take_profit"]:
        raise ValueError("For a BUY, expected stop_loss < entry < take_profit")
    if payload["side"] == "sell" and not payload["take_profit"] < payload["entry"] < payload["stop_loss"]:
        raise ValueError("For a SELL, expected take_profit < entry < stop_loss")
    return {"order_id": str(uuid4()), "status": "PAPER_ACCEPTED", "mode": "paper",
            "message": "Paper order recorded in response only; no broker order was sent."}

def live_execution_guard(enabled: bool):
    if not enabled:
        raise RuntimeError("Live trading is disabled. Use paper mode until broker integration is validated.")
    raise NotImplementedError("Live execution adapter is not implemented in this starter.")
