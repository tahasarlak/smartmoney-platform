import asyncio
import time

from app.multi_symbol import MultiSymbolScanRequest, scan_many_symbols
from app.scanner import TIMEFRAMES


def make_rows(tf):
    seconds = {"4h":14400, "1h":3600, "15m":900, "5m":300, "1m":60}[tf]
    now = int(time.time())
    # 80 historical bars plus a forming bar; all timestamps aligned to interval.
    latest_open = (now // seconds) * seconds
    rows = []
    for i in range(80):
        op = latest_open - (80-i) * seconds
        close = op + seconds
        p = 100 + i * 0.1
        rows.append({
            "time": op, "open": p, "high": p + 0.3,
            "low": p - 0.3, "close": p + 0.1, "volume": 1
        })
    rows.append({
        "time": latest_open, "open": 108, "high": 108.3,
        "low": 107.7, "close": 108.1, "volume": 1
    })
    return rows


def fake_analysis(symbol, candles, swing_length=3):
    return {
        "structure": "range",
        "directional_bias": "range",
        "quality_score": 30,
        "events": [],
        "zones": [],
    }


def test_request_normalizes_and_deduplicates_symbols():
    request = MultiSymbolScanRequest(symbols=["btcusdt", "ETHUSDT", "BTCUSDT"])
    assert request.symbols == ["BTCUSDT", "ETHUSDT"]


def test_multi_scan_isolates_symbol_errors_and_returns_no_fake_probability():
    async def fetch(symbol, tf, limit):
        if symbol == "BADUSDT":
            raise RuntimeError("mock provider failure")
        return make_rows(tf)

    result = asyncio.run(scan_many_symbols(
        ["BTCUSDT", "BADUSDT"], 100, fetch, fake_analysis,
        now_epoch=int(time.time()), max_concurrency=2
    ))
    assert result["summary"]["requested"] == 2
    assert result["summary"]["scanned"] == 1
    assert result["summary"]["errors"] == 1
    assert result["estimated_win_probability"] is None
    assert result["execution_allowed"] is False


def test_multi_scan_rejects_stale_or_bad_data_per_symbol():
    async def fetch(symbol, tf, limit):
        rows = make_rows(tf)
        if symbol == "STALEUSDT" and tf == "5m":
            for i, row in enumerate(rows):
                row["time"] -= 100_000
        return rows

    result = asyncio.run(scan_many_symbols(
        ["STALEUSDT"], 100, fetch, fake_analysis,
        now_epoch=int(time.time())
    ))
    assert result["summary"]["data_rejected"] == 1
