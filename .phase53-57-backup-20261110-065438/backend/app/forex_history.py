"""Dukascopy M1 import, strict OHLC resampling, and isolated per-symbol SMC backtests."""
from __future__ import annotations
import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from .database import session_scope
from .forex_models import ForexCandle
from .forex_intraday import SYMBOLS, PROVIDER

TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
QUOTE_CURRENCY = {"EURUSD":"USD","GBPUSD":"USD","USDJPY":"JPY","USDCHF":"CHF",
                  "AUDUSD":"USD","USDCAD":"CAD","NZDUSD":"USD","XAUUSD":"USD"}


def _timestamp(value: str) -> int:
    raw = str(value).strip()
    try:
        number = float(raw)
        if number > 10_000_000_000:
            number /= 1000.0
        return int(number)
    except ValueError:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())


def load_m1_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no CSV header")
        names = {name.strip().lower(): name for name in reader.fieldnames}
        required = {"timestamp", "open", "high", "low", "close"}
        if not required.issubset(names):
            raise ValueError(f"{path} must contain columns {sorted(required)}")
        for index, row in enumerate(reader, 2):
            try:
                item = {
                    "time": _timestamp(row[names["timestamp"]]),
                    "open": float(row[names["open"]]),
                    "high": float(row[names["high"]]),
                    "low": float(row[names["low"]]),
                    "close": float(row[names["close"]]),
                    "volume": float(row[names["volume"]]) if "volume" in names and row[names["volume"]] else 0.0,
                }
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Invalid row {index} in {path}") from exc
            prices = [item[k] for k in ("open", "high", "low", "close")]
            if not all(math.isfinite(x) and x > 0 for x in prices):
                raise ValueError(f"Non-positive or non-finite price at row {index}")
            if not item["low"] <= min(item["open"], item["close"]) <= max(item["open"], item["close"]) <= item["high"]:
                raise ValueError(f"Invalid OHLC relationship at row {index}")
            rows.append(item)
    rows.sort(key=lambda x: x["time"])
    if not rows:
        raise ValueError(f"No rows in {path}")
    if len({x["time"] for x in rows}) != len(rows):
        raise ValueError(f"Duplicate minute timestamps in {path}")
    return rows


def aggregate_m1(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"1m": rows}
    for tf, seconds in TF_SECONDS.items():
        if tf == "1m":
            continue
        required = seconds // 60
        groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            bucket = int(row["time"]) // seconds * seconds
            groups[bucket].append(row)
        candles = []
        for bucket, group in sorted(groups.items()):
            group.sort(key=lambda x: x["time"])
            if len(group) != required:
                continue
            if any(int(group[i]["time"]) != bucket + i * 60 for i in range(required)):
                continue
            candles.append({
                "time": bucket, "open": group[0]["open"],
                "high": max(x["high"] for x in group),
                "low": min(x["low"] for x in group),
                "close": group[-1]["close"],
                "volume": sum(float(x.get("volume", 0.0)) for x in group),
            })
        result[tf] = candles
    return result


def load_market_data(data_dir: Path, symbols: list[str] | None = None):
    selected = symbols or list(SYMBOLS)
    result = {}
    for symbol in selected:
        normalized = symbol.strip().upper()
        if normalized not in SYMBOLS:
            raise ValueError(f"Unsupported Forex symbol: {normalized}")
        path = data_dir / f"{normalized}_m1.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing historical file: {path}")
        frames = aggregate_m1(load_m1_csv(path))
        insufficient = {tf: len(frames[tf]) for tf in TF_SECONDS if len(frames[tf]) < 51}
        if insufficient:
            raise ValueError(f"{normalized} has insufficient complete candles: {insufficient}")
        result[normalized] = frames
    return result


def import_market_data(data_dir: Path, symbols: list[str] | None = None) -> dict[str, int]:
    datasets = load_market_data(data_dir, symbols)
    total: dict[str, int] = {}
    with session_scope() as db:
        for symbol, frames in datasets.items():
            for timeframe, rows in frames.items():
                total[f"{symbol}:{timeframe}"] = len(rows)
                for offset in range(0, len(rows), 500):
                    values = [{
                        "symbol": symbol, "timeframe": timeframe,
                        "candle_time": int(row["time"]), "open": row["open"],
                        "high": row["high"], "low": row["low"], "close": row["close"],
                        "volume": row.get("volume", 0.0), "provider": "dukascopy_historical_bid",
                    } for row in rows[offset:offset + 500]]
                    stmt = pg_insert(ForexCandle).values(values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[ForexCandle.symbol, ForexCandle.timeframe, ForexCandle.candle_time],
                        set_={"open": stmt.excluded.open, "high": stmt.excluded.high,
                              "low": stmt.excluded.low, "close": stmt.excluded.close,
                              "volume": stmt.excluded.volume, "provider": stmt.excluded.provider},
                    )
                    db.execute(stmt)
    return total


def run_backtests(data_dir: Path, costs_path: Path, output_path: Path,
                  symbols: list[str] | None = None, initial_equity: float = 10_000.0,
                  risk_percent: float = 0.25, min_quality_score: int = 65,
                  min_rr: float = 2.0):
    from .historical_smc_backtest import run_historical_smc_portfolio_backtest
    datasets = load_market_data(data_dir, symbols)
    costs = json.loads(costs_path.read_text(encoding="utf-8"))
    results = {}
    for symbol, frames in datasets.items():
        cfg = costs.get(symbol)
        if not isinstance(cfg, dict) or not {"spread", "slippage", "commission_pct"}.issubset(cfg):
            raise ValueError(f"Costs file needs spread, slippage and commission_pct for {symbol}")
        result = run_historical_smc_portfolio_backtest(
            {symbol: frames}, initial_equity=initial_equity,
            risk_percent=risk_percent, min_quality_score=min_quality_score,
            min_rr=min_rr, allow_counter_trend=False, max_signals_per_symbol=500,
            history_limit=500, spread=float(cfg["spread"]),
            slippage=float(cfg["slippage"]), commission_pct=float(cfg["commission_pct"]),
            max_open_trades=1, use_regime_filter=True,
        )
        results[symbol] = {
            "account_currency": QUOTE_CURRENCY[symbol],
            "account_model": "isolated_single_symbol_account; not combined portfolio",
            "spread_assumption_price_units": float(cfg["spread"]),
            "slippage_assumption_price_units": float(cfg["slippage"]),
            "commission_pct": float(cfg["commission_pct"]),
            "candles_by_timeframe": {tf: len(rows) for tf, rows in frames.items()},
            **result,
        }
    payload = {
        "status": "completed",
        "provider": "Dukascopy historical bid candles via dukascopy-node",
        "symbols": list(results),
        "results_by_symbol": results,
        "portfolio_aggregation": None,
        "limitations": [
            "Each instrument is tested in an isolated account denominated in its quote currency; results are not a combined USD portfolio.",
            "Cost inputs are user-configured assumptions and must be replaced with the intended broker's actual spread, commission and slippage.",
            "Historical bid candles do not reconstruct exact historical bid/ask fills or broker-specific execution.",
            "This research result is not a profitability guarantee and never enables execution.",
        ],
        "execution_allowed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("import-db", "backtest"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/forex"))
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--costs", type=Path, default=Path("data/forex/forex_costs.json"))
    parser.add_argument("--output", type=Path, default=Path("data/forex/backtest_results.json"))
    parser.add_argument("--initial-equity", type=float, default=10000.0)
    parser.add_argument("--risk-percent", type=float, default=0.25)
    parser.add_argument("--min-quality-score", type=int, default=65)
    parser.add_argument("--min-rr", type=float, default=2.0)
    args = parser.parse_args()
    if args.action == "import-db":
        print(json.dumps(import_market_data(args.data_dir, args.symbols), indent=2))
    else:
        payload = run_backtests(args.data_dir, args.costs, args.output, args.symbols,
                                args.initial_equity, args.risk_percent,
                                args.min_quality_score, args.min_rr)
        print(json.dumps({"status": payload["status"], "output": str(args.output),
                          "symbols": payload["symbols"], "execution_allowed": False}, indent=2))


if __name__ == "__main__":
    main()
