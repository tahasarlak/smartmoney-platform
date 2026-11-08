# SmartMoney Phase 5 — Signal Quality & Confluence Engine

## Scope

Phase 5 adds a deterministic signal-quality assessment layer to the existing scanner.
It builds on the repository's existing SMC analysis, multi-timeframe structure,
closed-candle trigger detection, market-regime classification, and signal journal.
It does not replace those components or claim to predict market outcomes.

## Implementation

- Added `app/quality_engine.py` with versioned methodology `signal-quality-1.0`.
- Combines the existing rule-based technical score with limited 4H/15M regime
  adjustments. Regime agreement can add at most 6 points; regime conflict,
  expanded volatility, and low volume participation reduce the score.
- Reports independent confluence families: multi-timeframe structure, liquidity,
  structure shift, micro confirmation, entry location, closed-candle trigger,
  and market regime.
- Reports risk flags for higher-timeframe conflict, counter-trend setups,
  missing entry zones, missing closed-candle confirmation, volatility expansion,
  and low volume participation.
- Adds a qualitative false-signal-risk label (`low`, `moderate`, `elevated`).
  This is a rule-based warning classification, not a measured false-positive rate.
- A setup is `review_eligible` only when it has a valid entry zone, a confirmed
  closed-5M trigger, and meets the configured quality threshold.
- The V8 intelligence response ranks review-eligible setups first, then by
  independent confluence count and quality score.
- The single-symbol scanner and V8 scanner both expose the same assessment.

## API response additions

Each scenario now includes `quality_assessment` with:
- `quality_score`, `grade`, and `classification`
- `review_eligible`
- `score_components`
- `independent_confluence_count` and `confluence_groups`
- `supporting_evidence` and `risk_flags`
- `false_signal_risk`
- `methodology_version`

The V8 scan response includes `quality_methodology_version`.

## Safety and limitations

- `estimated_win_probability` remains `null`. A quality score is not a win
  probability and must not be interpreted as one.
- Evidence is intended to be derived from closed candles; the existing data
  validation and SMC/regime modules remain responsible for candle validity.
- The new false-signal-risk label is heuristic. It is not a statistically
  calibrated false-positive rate.
- No database tables or migrations were added.
- No live trading or broker execution was enabled. `execution_allowed` remains
  false throughout the research scanner.
- Historical probability calibration remains gated by the existing chronological
  holdout calibration process and sufficient sample counts.

## Validation

Run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_phase5_quality_engine.py `
  tests\test_phase4_market_regime.py `
  tests\test_scanner_v4.py `
  tests\test_v8_engine.py -q
```

The full PostgreSQL-backed test suite must be run through the existing
`SmartMoney V11 - PostgreSQL Phase 3 Integration` GitHub Actions workflow,
because Neon credentials are stored as GitHub Environment secrets. Do not run
the workflow's optional schema-reset input for this phase.
