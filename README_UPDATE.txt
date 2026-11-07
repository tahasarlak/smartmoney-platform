TRADE SETUP ENGINE 3.0 - FIRST RESEARCH MILESTONE

1. Copy backend/app/trade_setup.py into the same folder in your project.
2. Open backend/app/main.py and add the import and endpoint shown in MAIN_PY_PATCH.txt.
3. Run: python -m pytest tests -v
4. Open /docs and call POST /api/v1/analysis/trade-setup with:
   {"symbol":"BTCUSDT","interval":"15m","limit":300}

This milestone produces a proposed retest entry, structure-buffered stop and 1R/2R/3R targets only when a valid 5m zone exists. It does not place orders. It is not yet a validated strategy; no probability is claimed. Contract sizing, exchange precision, fees, slippage, funding, and broker-specific tick values must be added before execution.
