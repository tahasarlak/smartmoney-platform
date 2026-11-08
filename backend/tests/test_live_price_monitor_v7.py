import json
from app.live_price_monitor import build_stream_url, parse_trade_message

def test_parse_binance_combined_trade_message():
    raw = json.dumps({
        "stream": "btcusdt@trade",
        "data": {"e":"trade","E":1790000000123,"s":"BTCUSDT","p":"67500.25","T":1790000000122,"t":123456}
    })
    event = parse_trade_message(raw)
    assert event["symbol"] == "BTCUSDT"
    assert event["price"] == 67500.25
    assert event["event_time_ms"] == 1790000000122
    assert event["event_id"] == "123456"

def test_invalid_trade_message_is_ignored():
    assert parse_trade_message('{"data":{"s":"BTCUSDT","p":"NaN"}}') is None
    assert parse_trade_message("not-json") is None

def test_build_stream_url_deduplicates_symbols():
    url = build_stream_url(["btcusdt", "ETHUSDT", "BTCUSDT"])
    assert url.endswith("btcusdt@trade/ethusdt@trade")
