# Multi-timeframe update 0.2

New endpoint: `POST /api/v1/analysis/multi-timeframe`

Example request:
`{"symbol":"BTCUSDT","interval":"15m","limit":300}`

The backend fetches 4h, 1h, 15m, 5m and 1m Binance candles concurrently and analyses each timeframe.

Important: quality score is heuristic, win probability remains null, and no entry/SL/TP or live execution is generated. This is an orchestration milestone, not a validated trading strategy. The baseline SMC rules require independent verification and out-of-sample backtesting.
