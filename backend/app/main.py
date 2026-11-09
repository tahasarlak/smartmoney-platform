from contextlib import asynccontextmanager
import asyncio
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .database import get_engine
from .config import settings
from .schemas import SettingsIn, OHLCVRequest, AnalysisRequest, PositionSizeRequest, PaperOrderRequest
from .market_data import binance_klines
from .smc import analyze_smc
from .mtf import analyze_multi_timeframe, TIMEFRAMES
from .trade_setup import build_trade_setup
from .scanner import scan_symbol
from .multi_symbol import MultiSymbolScanRequest, scan_many_symbols
from .data_quality import validate_candle_series
from .market_regime import analyze_market_regime
import time
from .risk import calculate_position_size
from .execution import create_paper_order
from .risk_controls import evaluate_risk
from .backtesting import run_bar_backtest
from .multi_backtesting import run_multi_symbol_backtest
from .calibration import evaluate_calibration
from .advanced_schemas import RiskPreflightRequest, BacktestRequest, MultiSymbolBacktestRequest, StrategyValidationRequest
from .strategy_validation import validate_strategy_walk_forward
from .signal_journal import (
    create_signal,
    get_signal,
    list_signals,
    signal_events,
    update_signal_price,
    closed_signal_outcomes,
)
from .signal_schemas import SignalPriceUpdate
from .live_price_monitor import live_price_monitor
from .v8_engine import V8ScanRequest, V8StartRequest, V8IntelligenceService
from .v11_platform import router as v11_router
from .live_strategy_router import router as live_strategy_router
from .live_signal_monitor import live_signal_monitor
from .paper_automation_router import router as paper_automation_router
from .phase12_router import router as phase12_router
from .operational_resilience import build_operational_health
from .production_infrastructure import router as production_router
from .forex_reference import router as forex_reference_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Alembic owns schema creation. Application startup only starts runtime services.
    await live_price_monitor.start()
    await live_signal_monitor.start()
    try:
        yield
    finally:
        await live_signal_monitor.stop()
        await live_price_monitor.stop()


app = FastAPI(
    title="SmartMoney Platform API",
    version="11.0.0",
    description="SmartMoney research and tenant-scoped paper trading API. Live execution is disabled.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.api_cors_origins.split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(v11_router)
app.include_router(live_strategy_router)
app.include_router(paper_automation_router)
app.include_router(phase12_router)
app.include_router(production_router)
app.include_router(forex_reference_router)
_current_settings = SettingsIn()

v8_service = V8IntelligenceService(
    fetch_klines=binance_klines,
    analyze_smc_fn=analyze_smc,
    create_signal_fn=create_signal,
    list_signals_fn=list_signals,
)


@app.get("/health")
def health():
    """Liveness probe: confirms the API process is responsive."""
    return {
        "status": "ok",
        "environment": settings.app_env,
        "live_trading_enabled": False,
    }


@app.get("/api/v1/monitor/operational-health")
def operational_health():
    """Read-only process health assembled from monitor telemetry; no DB query."""
    return build_operational_health(
        live_price_monitor.status(),
        live_signal_monitor.status(),
    )


@app.get("/health/ready")
def readiness():
    """Readiness probe: confirms the configured PostgreSQL database is reachable."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "postgresql",
            "live_trading_enabled": False,
        }
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database is not ready",
        )

@app.get("/api/v1/settings/defaults")
def defaults():
    return _current_settings.model_dump()

@app.put("/api/v1/settings")
def update_settings(payload: SettingsIn):
    global _current_settings
    _current_settings = payload
    return {"saved": True, "settings": _current_settings.model_dump(),
            "note":"In-memory starter storage only; persistent user settings/auth are a later milestone."}

@app.post("/api/v1/market/binance/klines")
async def get_binance_klines(payload: OHLCVRequest):
    try:
        candles = await binance_klines(payload.symbol, payload.interval, payload.limit)
        return {"provider":"Binance public market data", "symbol":payload.symbol,
                "interval":payload.interval, "candles":candles}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market data provider error: {exc}")

@app.post("/api/v1/analysis/smc")
def smc_analysis(payload: AnalysisRequest):
    try:
        return analyze_smc(payload.symbol, [c.model_dump() for c in payload.candles],
                           payload.swing_length, payload.equal_level_tolerance_pct)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.post("/api/v1/analysis/multi-timeframe")
async def multi_timeframe_analysis(payload: OHLCVRequest):
    try:
        rows = await asyncio.gather(*[
            binance_klines(payload.symbol, tf, max(payload.limit, 100)) for tf in TIMEFRAMES
        ])
        result = analyze_multi_timeframe(payload.symbol, dict(zip(TIMEFRAMES, rows)),
                                         min_rr=_current_settings.min_rr,
                                         allow_counter_trend=_current_settings.allow_counter_trend)
        return {"provider":"Binance public market data", **result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Multi-timeframe analysis failed: {exc}")

@app.post("/api/v1/risk/position-size")
def position_size(payload: PositionSizeRequest):
    try:
        return calculate_position_size(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.post("/api/v1/execution/paper-order")
def paper_order(payload: PaperOrderRequest):
    try:
        return create_paper_order(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/analysis/trade-setup")
async def trade_setup_analysis(payload: OHLCVRequest):
    try:
        rows = await asyncio.gather(*[
            binance_klines(payload.symbol, tf, max(payload.limit, 100))
            for tf in TIMEFRAMES
        ])

        candles_by_tf = dict(zip(TIMEFRAMES, rows))

        analyses = {
            tf: analyze_smc(
                payload.symbol,
                candles_by_tf[tf],
                swing_length=3
            )
            for tf in TIMEFRAMES
        }

        result = build_trade_setup(
            payload.symbol,
            candles_by_tf,
            analyses,
            min_rr=_current_settings.min_rr,
            risk_percent=_current_settings.risk_per_trade_pct,
            allow_counter_trend=_current_settings.allow_counter_trend,
        )

        return {
            "provider": "Binance public market data",
            **result
        }

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Trade setup analysis failed: {exc}"
        )




@app.post("/api/v1/scanner/binance/symbol")
async def scan_binance_symbol(payload: OHLCVRequest):
    try:
        rows = await asyncio.gather(*[
            binance_klines(payload.symbol, tf, max(payload.limit, 100))
            for tf in TIMEFRAMES
        ])

        candles_by_tf = dict(zip(TIMEFRAMES, rows))
        now = int(time.time())

        data_checks = {}

        for tf in TIMEFRAMES:
            check = validate_candle_series(
                candles_by_tf[tf],
                tf,
                now
            )
            data_checks[tf] = check

            if not check["valid"]:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Market data validation failed",
                        "timeframe": tf,
                        "validation": check
                    }
                )

        analyses = {
            tf: analyze_smc(
                payload.symbol,
                candles_by_tf[tf],
                swing_length=3
            )
            for tf in TIMEFRAMES
        }

        regimes = {
            tf: analyze_market_regime(candles_by_tf[tf], tf)
            for tf in TIMEFRAMES
        }

        result = scan_symbol(
            payload.symbol,
            candles_by_tf,
            analyses,
            settings={
                "min_quality_score": _current_settings.min_quality_score,
                "min_rr": _current_settings.min_rr,
                "allow_counter_trend": _current_settings.allow_counter_trend
            },
            regimes=regimes,
        )

        return {
            "provider": "Binance public market data",
            "data_quality": data_checks,
            "market_regime": regimes,
            "settings": {
                "min_quality_score": _current_settings.min_quality_score,
                "min_rr": _current_settings.min_rr,
                "allow_counter_trend": _current_settings.allow_counter_trend
            },
            **result
        }

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Market scanner failed: {exc}"
        )



@app.post("/api/v1/scanner/binance/multi-symbol")
async def scan_binance_multi_symbol(payload: MultiSymbolScanRequest):
    try:
        return await scan_many_symbols(
            symbols=payload.symbols,
            limit=payload.limit,
            fetch_klines=binance_klines,
            analyze_smc_fn=analyze_smc,
            settings={
                "min_quality_score": _current_settings.min_quality_score,
                "min_rr": _current_settings.min_rr,
                "allow_counter_trend": _current_settings.allow_counter_trend,
            },
            max_concurrency=payload.max_concurrency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))



# SMARTMONEY SIGNAL JOURNAL V6 + LIVE MONITOR V7

# V6: Create signal from current market analysis
@app.post("/api/v1/signals/from-market/{symbol}")
async def create_signal_from_market(symbol: str, payload: OHLCVRequest):
    symbol = symbol.upper()

    if symbol != payload.symbol.upper():
        raise HTTPException(
            status_code=422,
            detail="Path symbol and payload symbol must match"
        )

    try:
        rows = await asyncio.gather(*[
            binance_klines(symbol, tf, max(payload.limit, 100))
            for tf in TIMEFRAMES
        ])

        candles_by_tf = dict(zip(TIMEFRAMES, rows))

        analyses = {
            tf: analyze_smc(
                symbol,
                candles_by_tf[tf],
                swing_length=3
            )
            for tf in TIMEFRAMES
        }

        plan = build_trade_setup(
            symbol,
            candles_by_tf,
            analyses,
            min_rr=_current_settings.min_rr,
            risk_percent=_current_settings.risk_per_trade_pct,
            allow_counter_trend=_current_settings.allow_counter_trend,
        )

        if plan.get("status") not in ("pending_retest", "zone_active"):
            return {"saved": False, "plan": plan}

        saved = create_signal(plan)

        return {
            "saved": True,
            "signal": saved,
            "plan": plan,
            "execution_allowed": False
        }

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Signal creation failed: {exc}"
        )


# V6: List signals
@app.get("/api/v1/signals")
def get_signals(status: str | None = None,
                symbol: str | None = None,
                limit: int = 100):

    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be 1..500")

    return {
        "signals": list_signals(status, symbol, limit),
        "execution_allowed": False
    }


# V6: Signal details and event history
@app.get("/api/v1/signals/{signal_id}")
def get_signal_detail(signal_id: str):

    signal = get_signal(signal_id)

    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")

    return {
        "signal": signal,
        "events": signal_events(signal_id),
        "execution_allowed": False
    }


# V6: Manual price update
@app.post("/api/v1/signals/{signal_id}/price")
def update_signal_market_price(
    signal_id: str,
    payload: SignalPriceUpdate
):
    try:
        result = update_signal_price(
            signal_id,
            payload.price,
            payload.timestamp
        )

        if result is None:
            raise HTTPException(status_code=404, detail="Signal not found")

        return {
            "signal": result,
            "execution_allowed": False
        }

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/monitor/live-price/watchlist")
def get_live_price_watchlist():
    return live_price_monitor.watchlist_status()

@app.post("/api/v1/monitor/live-price/watchlist/{symbol}")
def add_live_price_watchlist_symbol(symbol: str):
    try:
        return live_price_monitor.add_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.delete("/api/v1/monitor/live-price/watchlist/{symbol}")
def remove_live_price_watchlist_symbol(symbol: str):
    try:
        return live_price_monitor.remove_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.get("/api/v1/monitor/live-price/market")
def live_price_market_snapshot():
    return live_price_monitor.market_snapshot()
# V7: Live monitor status
@app.get("/api/v1/monitor/live-price/status")
def live_price_monitor_status():
    return live_price_monitor.status()


# V7: Start monitor
@app.post("/api/v1/monitor/live-price/start")
async def start_live_price_monitor_manually():
    return await live_price_monitor.start()


# V7: Stop monitor
@app.post("/api/v1/monitor/live-price/stop")
async def stop_live_price_monitor_manually():
    return await live_price_monitor.stop()






# V9: Risk preflight, conservative backtest replay and evidence-gated calibration.
@app.post("/api/v1/risk/preflight")
def risk_preflight(payload: RiskPreflightRequest):
    try:
        return evaluate_risk(
            **payload.model_dump(),
            settings=_current_settings.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/backtest/replay")
def backtest_replay(payload: BacktestRequest):
    try:
        return run_bar_backtest(
            candles=payload.candles,
            signals=[item.model_dump() for item in payload.signals],
            initial_equity=payload.initial_equity,
            spread=payload.spread,
            slippage=payload.slippage,
            commission_pct=payload.commission_pct,
            max_open_trades=payload.max_open_trades,
            max_daily_loss_pct=payload.max_daily_loss_pct,
            max_weekly_loss_pct=payload.max_weekly_loss_pct,
            max_drawdown_pct=payload.max_drawdown_pct,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))




@app.post("/api/v1/backtest/validate")
def strategy_validation(payload: StrategyValidationRequest):
    """Run rolling out-of-sample replay, Monte Carlo and cost stress analysis."""
    try:
        data = payload.model_dump()
        controls = {
            "folds": data.pop("folds"),
            "monte_carlo_simulations": data.pop("monte_carlo_simulations"),
            "random_seed": data.pop("random_seed"),
            "stress_cost_multiplier": data.pop("stress_cost_multiplier"),
        }
        return validate_strategy_walk_forward(
            candles_by_symbol=data.pop("candles_by_symbol"),
            signals=data.pop("signals"),
            **data,
            **controls,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/backtest/multi-symbol")
def multi_symbol_backtest(payload: MultiSymbolBacktestRequest):
    try:
        return run_multi_symbol_backtest(
            candles_by_symbol=payload.candles_by_symbol,
            signals=[
                item.model_dump()
                for item in payload.signals
            ],
            initial_equity=payload.initial_equity,
            spread=payload.spread,
            slippage=payload.slippage,
            commission_pct=payload.commission_pct,
            max_open_trades=payload.max_open_trades,
            max_daily_loss_pct=payload.max_daily_loss_pct,
            max_weekly_loss_pct=payload.max_weekly_loss_pct,
            max_drawdown_pct=payload.max_drawdown_pct,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
@app.get("/api/v1/intelligence/calibration/report")
def calibration_report():
    try:
        observations = closed_signal_outcomes(limit=20000)
        report = evaluate_calibration(observations)
        report["source"] = "terminal signal journal outcomes (TP3_HIT vs STOPPED)"
        report["execution_allowed"] = False
        return report
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))




@app.get("/api/v1/intelligence/v4/regime/{symbol}")
async def v4_market_regime(symbol: str, limit: int = 300):
    """Return closed-candle trend, volatility and participation context."""
    normalized = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
        raise HTTPException(status_code=422, detail="Invalid symbol")
    if not 100 <= limit <= 1000:
        raise HTTPException(status_code=422, detail="limit must be between 100 and 1000")
    try:
        rows = await asyncio.gather(*[
            binance_klines(normalized, timeframe, limit)
            for timeframe in TIMEFRAMES
        ])
        candles_by_tf = dict(zip(TIMEFRAMES, rows))
        now = int(time.time())
        data_quality = {
            timeframe: validate_candle_series(candles_by_tf[timeframe], timeframe, now)
            for timeframe in TIMEFRAMES
        }
        invalid = next((tf for tf, check in data_quality.items() if not check["valid"]), None)
        if invalid:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Market data validation failed",
                    "timeframe": invalid,
                    "validation": data_quality[invalid],
                },
            )
        return {
            "symbol": normalized,
            "provider": "Binance public market data",
            "market_regime": {
                timeframe: analyze_market_regime(candles_by_tf[timeframe], timeframe)
                for timeframe in TIMEFRAMES
            },
            "data_quality": data_quality,
            "methodology_version": "market-regime-1.0",
            "estimated_win_probability": None,
            "execution_allowed": False,
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market regime analysis failed: {exc}")


# V8: Multi-timeframe intelligence scanner and optional research-signal journal.
def _v8_current_settings():
    return {
        "min_quality_score": _current_settings.min_quality_score,
        "min_rr": _current_settings.min_rr,
        "risk_per_trade_pct": _current_settings.risk_per_trade_pct,
        "allow_counter_trend": _current_settings.allow_counter_trend,
    }


def _v8_default_symbols():
    return sorted(set(str(x).upper() for x in live_price_monitor.status().get("symbols", [])))


@app.post("/api/v1/intelligence/v8/scan")
async def v8_scan(payload: V8ScanRequest):
    symbols = payload.symbols or _v8_default_symbols()
    if not symbols:
        raise HTTPException(
            status_code=422,
            detail="No symbols supplied. Add symbols to the live watchlist or provide symbols in the request.",
        )
    try:
        return await v8_service.scan_once(
            symbols=symbols,
            limit=payload.limit,
            settings=_v8_current_settings(),
            persist_signals=payload.persist_signals,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/intelligence/v8/status")
def v8_status():
    return v8_service.status()


@app.get("/api/v1/intelligence/v8/latest")
def v8_latest():
    return {"result": v8_service.latest(), "execution_allowed": False}


@app.post("/api/v1/intelligence/v8/start")
async def v8_start(payload: V8StartRequest):
    symbols = payload.symbols or _v8_default_symbols()
    if not symbols:
        raise HTTPException(
            status_code=422,
            detail="No symbols supplied. Add symbols to the live watchlist or provide symbols in the request.",
        )
    try:
        return await v8_service.start(
            symbols=symbols,
            limit=payload.limit,
            interval_seconds=payload.interval_seconds,
            settings=_v8_current_settings(),
            persist_signals=payload.persist_signals,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/intelligence/v8/stop")
async def v8_stop():
    return await v8_service.stop()





