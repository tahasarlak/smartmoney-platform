"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Activity, ArrowLeft, RefreshCw, ShieldCheck, Wifi, WifiOff } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TIMEFRAMES = ["4h", "1h", "15m", "5m", "1m"] as const;

type Instrument = { symbol: string; available: boolean; last_candle_time: number | null; age_seconds: number | null };
type Status = { status: string; connected: boolean; age_seconds?: number; demo_only: boolean; execution_enabled: boolean };
type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number; spread_points?: number };
type Analysis = { symbol: string; primary_bias: string; candidate_state: string; best_candidate: { direction: string; quality_score: number; reasons: string[] }; execution_allowed: boolean; probability_status: string };

const money = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 5 });
const stamp = (v: number) => new Date(v * 1000).toLocaleString("fa-IR");

export default function ForexPage() {
  const [symbols, setSymbols] = useState<Instrument[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>("15m");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState("");

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(`${API}${path}`, { ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `خطای سرور ${response.status}`);
    return data;
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [s, m] = await Promise.all([request("/api/v1/mt5/market/status"), request("/api/v1/mt5/market/symbols")]);
      setStatus(s); setSymbols(m.symbols || []); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "دریافت وضعیت انجام نشد"); }
  }, [request]);

  const loadMarket = useCallback(async () => {
    setBusy(true); setError(""); setAnalysis(null);
    try {
      const q = new URLSearchParams({ symbol, timeframe, limit: "100" });
      const data = await request(`/api/v1/mt5/market/klines?${q.toString()}`);
      setCandles(data.candles || []); setUpdated(new Date().toLocaleTimeString("fa-IR"));
    } catch (e) { setCandles([]); setError(e instanceof Error ? e.message : "دریافت کندل انجام نشد"); }
    finally { setBusy(false); }
  }, [request, symbol, timeframe]);

  async function runAnalysis() {
    setBusy(true); setError("");
    try {
      const data = await request("/api/v1/mt5/analysis/multi-timeframe", { method: "POST", body: JSON.stringify({ symbol, limit: 300 }) });
      setAnalysis(data);
    } catch (e) { setError(e instanceof Error ? e.message : "تحلیل انجام نشد"); }
    finally { setBusy(false); }
  }

  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 30000); return () => window.clearInterval(timer); }, [refresh]);
  useEffect(() => { void loadMarket(); }, [loadMarket]);

  const selected = useMemo(() => symbols.find(x => x.symbol === symbol), [symbols, symbol]);
  const last = candles[candles.length - 1];

  return (
    <main className="forex-page" dir="rtl">
      <header className="forex-header">
        <Link href="/" className="forex-brand">TRADF <span>MARKETS</span></Link>
        <Link href="/" className="forex-back"><ArrowLeft size={16}/> بازگشت به داشبورد</Link>
      </header>
      <section className="forex-wrap">
        <div className="forex-title">
          <div><span className="forex-eyebrow">بازار فارکس و فلزات</span><h1>بازارهای فارکس و طلا</h1><p>قیمت‌ها مستقیماً از حساب آزمایشی MetaTrader 5 بروکر دریافت می‌شوند.</p></div>
          <div className={`forex-connection ${status?.connected ? "is-online" : "is-offline"}`}>
            {status?.connected ? <Wifi size={17}/> : <WifiOff size={17}/>}
            {status?.connected ? "اتصال دمو برقرار" : "Bridge متصل نیست"}
          </div>
        </div>

        <div className="forex-safety"><ShieldCheck size={18}/><span>فقط دریافت داده از حساب Demo فعال است. ارسال سفارش و معاملات واقعی در این Bridge پیاده‌سازی نشده است.</span></div>

        {error && <div className="forex-error">{error}</div>}

        <section className="forex-grid">
          <div className="forex-panel">
            <div className="forex-panel-head"><h2>انتخاب نماد</h2><button onClick={() => void refresh()} aria-label="تازه‌سازی"><RefreshCw size={16}/></button></div>
            <div className="forex-symbol-list">
              {symbols.map(item => (
                <button key={item.symbol} onClick={() => setSymbol(item.symbol)} className={symbol === item.symbol ? "selected" : ""}>
                  <span><b>{item.symbol}</b><small>{item.symbol === "XAUUSD" ? "طلا / دلار" : "جفت‌ارز اصلی"}</small></span>
                  <i className={item.available ? "available" : ""}>{item.available ? "داده موجود" : "در انتظار داده"}</i>
                </button>
              ))}
            </div>
          </div>

          <div className="forex-panel forex-market">
            <div className="forex-panel-head"><div><h2>{symbol}</h2><small>{selected?.available ? `آخرین کندل: ${selected.last_candle_time ? stamp(selected.last_candle_time) : "—"}` : "هنوز داده‌ای از Bridge دریافت نشده"}</small></div><Activity size={20}/></div>
            <div className="forex-controls">
              <label>تایم‌فریم<select value={timeframe} onChange={e => setTimeframe(e.target.value as (typeof TIMEFRAMES)[number])}>{TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf.toUpperCase()}</option>)}</select></label>
              <button onClick={() => void loadMarket()} disabled={busy}><RefreshCw size={15}/> بروزرسانی</button>
            </div>
            <div className="forex-price">{last ? money(last.close) : "—"}<small>{last ? `آخرین کندل ${stamp(last.time)}` : "قیمتی دریافت نشده"}</small></div>
            <div className="forex-table-wrap"><table><thead><tr><th>زمان</th><th>بازشدن</th><th>بیشترین</th><th>کمترین</th><th>بسته‌شدن</th></tr></thead><tbody>{candles.slice(-12).reverse().map(c => <tr key={c.time}><td>{stamp(c.time)}</td><td>{money(c.open)}</td><td>{money(c.high)}</td><td>{money(c.low)}</td><td>{money(c.close)}</td></tr>)}</tbody></table>{!candles.length && <p className="forex-empty">برای نمایش قیمت، ابتدا Bridge ویندوزی را اجرا کن.</p>}</div>
            <small className="forex-updated">آخرین دریافت از API: {updated || "—"}</small>
            <button className="forex-analysis" onClick={() => void runAnalysis()} disabled={busy}>تحلیل چندتایم‌فریمی SMC</button>
            {analysis && <div className="forex-analysis-result"><b>وضعیت: {analysis.candidate_state}</b><span>جهت غالب: {analysis.primary_bias}</span><span>کاندید: {analysis.best_candidate.direction} · امتیاز کیفیت {analysis.best_candidate.quality_score}/100</span><small>این امتیاز احتمال سود نیست؛ سفارش خودکار ارسال نمی‌شود.</small><ul>{analysis.best_candidate.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul></div>}
          </div>
        </section>
        <p className="forex-footnote">نمادهای قابل پشتیبانی: EURUSD، GBPUSD، USDJPY، USDCHF، AUDUSD، USDCAD، NZDUSD و XAUUSD. پسوند نمادها ممکن است بین بروکرها متفاوت باشد و از طریق MT5_SYMBOL_MAP قابل تنظیم است.</p>
      </section>
    </main>
  );
}
