"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, BarChart3, CheckCircle2, RefreshCw, ShieldCheck, SlidersHorizontal } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Portfolio = { id: string; name: string; initial_equity?: number };
type Json = Record<string, any>;
async function request(path: string, token: string, init?: RequestInit): Promise<Json> {
  const response = await fetch(`${API}${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init?.body ? { "Content-Type": "application/json" } : {}), ...(init?.headers || {}) }, cache: "no-store" });
  const data = await response.json().catch(() => ({ detail: "Invalid API response" }));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}
const sample = `{
  "BTCUSDT": {
    "4h": [{"time": 1700000000, "open": 36000, "high": 36200, "low": 35900, "close": 36100, "volume": 100}],
    "1h": [{"time": 1700000000, "open": 36000, "high": 36200, "low": 35900, "close": 36100, "volume": 100}],
    "15m": [{"time": 1700000000, "open": 36000, "high": 36200, "low": 35900, "close": 36100, "volume": 100}],
    "5m": [{"time": 1700000000, "open": 36000, "high": 36200, "low": 35900, "close": 36100, "volume": 100}]
  }
}`;
const strategySample = `[
  {"name":"SMC BTC","expectancy_r":0.18,"risk_r":1.0},
  {"name":"SMC ETH","expectancy_r":0.14,"risk_r":1.1},
  {"name":"Trend SOL","expectancy_r":0.11,"risk_r":1.2}
]`;
function Metric({ label, value }: { label: string; value: any }) { return <div className="p1520-metric"><span>{label}</span><strong>{value === null || value === undefined ? "—" : typeof value === "number" ? value.toLocaleString("en-US", { maximumFractionDigits: 3 }) : String(value)}</strong></div>; }
function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) { return <section className="p1520-panel"><h2>{icon}{title}</h2>{children}</section>; }

export default function ResearchOperationsPage() {
  const [token, setToken] = useState("");
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [portfolioId, setPortfolioId] = useState("");
  const [candles, setCandles] = useState(sample);
  const [strategies, setStrategies] = useState(strategySample);
  const [optimizer, setOptimizer] = useState<Json | null>(null);
  const [allocation, setAllocation] = useState<Json | null>(null);
  const [monitor, setMonitor] = useState<Json | null>(null);
  const [security, setSecurity] = useState<Json | null>(null);
  const [release, setRelease] = useState<Json | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => { const saved = window.localStorage.getItem("smartmoney_v11_token"); if (saved) setToken(saved); }, []);
  const loadPortfolios = useCallback(async () => {
    if (!token) return;
    try { const result = await request("/api/v1/v11/portfolios", token); const rows = Array.isArray(result) ? result : result.items || result.portfolios || []; setPortfolios(rows); if (rows.length && !portfolioId) setPortfolioId(rows[0].id); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load portfolios"); }
  }, [token, portfolioId]);
  useEffect(() => { void loadPortfolios(); }, [loadPortfolios]);

  const run = async (key: string, fn: () => Promise<Json>, setter: (v: Json) => void) => {
    setBusy(key); setError(""); try { setter(await fn()); } catch (e) { setError(e instanceof Error ? e.message : "Request failed"); } finally { setBusy(""); }
  };
  const refreshReports = async () => {
    if (!token || !portfolioId) return;
    await run("reports", async () => {
      const [m, s, r] = await Promise.all([
        request("/api/v1/v11/operations/monitoring", token),
        request(`/api/v1/v11/portfolios/${portfolioId}/security-audit`, token),
        request(`/api/v1/v11/portfolios/${portfolioId}/release-audit?limit=500`, token),
      ]);
      setMonitor(m); setSecurity(s); setRelease(r); return { status: "completed" };
    }, () => {});
  };
  const runOptimizer = () => run("optimizer", async () => {
    const parsed = JSON.parse(candles);
    return request("/api/v1/v11/research/historical-optimization", token, { method: "POST", body: JSON.stringify({ candles_by_symbol_and_tf: parsed, initial_equity: 10000, risk_percent: 0.5, min_quality_scores: [60, 65, 70], min_rr_values: [1.5, 2, 2.5], train_fraction: 0.7, max_combinations: 9, min_train_trades: 5, commission_pct: 0.04, slippage: 0, spread: 0 }) });
  }, setOptimizer);
  const runAllocation = () => run("allocation", async () => request("/api/v1/v11/research/strategy-allocation", token, { method: "POST", body: JSON.stringify({ strategies: JSON.parse(strategies), max_weight: 0.4, min_edge: 0 }) }), setAllocation);

  if (!token) return <main className="p1520-shell"><div className="p1520-hero"><span className="p1520-kicker">TRADF · RESEARCH WORKSPACE</span><h1>Research & Operations</h1><p>ابتدا وارد حساب V11 شو؛ توکن ورود از فضای کاری اصلی خوانده می‌شود.</p><a href="/v11">بازگشت به داشبورد</a></div></main>;
  return <main className="p1520-shell">
    <header className="p1520-hero"><div><span className="p1520-kicker">TRADF · PHASES 16—20</span><h1>Research & Operations</h1><p>تحقیق تاریخی، تخصیص چنداستراتژی، پایش سرویس و ممیزی انتشار؛ بدون اجرای سفارش واقعی.</p></div><a href="/v11">داشبورد اصلی ↗</a></header>
    {error && <div className="p1520-error"><AlertTriangle size={17}/>{error}</div>}
    <div className="p1520-toolbar"><label>پرتفوی<select value={portfolioId} onChange={e => setPortfolioId(e.target.value)}><option value="">انتخاب پرتفوی</option>{portfolios.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><button onClick={refreshReports} disabled={!portfolioId || !!busy}><RefreshCw size={16}/> {busy === "reports" ? "در حال بررسی…" : "به‌روزرسانی ممیزی‌ها"}</button></div>
    <div className="p1520-grid">
      <Panel title="Phase 16 · Historical Optimization" icon={<SlidersHorizontal size={19}/> }>
        <p>داده OHLC چندتایم‌فریمی را به‌صورت JSON وارد کن. پارامترها فقط روی بخش آموزشی انتخاب و سپس روی بازه خارج از نمونه ارزیابی می‌شوند.</p>
        <textarea className="p1520-code" value={candles} onChange={e => setCandles(e.target.value)} spellCheck={false}/>
        <button onClick={runOptimizer} disabled={!!busy}>{busy === "optimizer" ? "در حال اجرای بک‌تست…" : "اجرای Historical Optimization"}</button>
        {optimizer && <div className="p1520-result"><Metric label="وضعیت" value={optimizer.status}/><Metric label="پارامتر منتخب" value={JSON.stringify(optimizer.selected_parameters)}/><Metric label="OOS معاملات" value={optimizer.out_of_sample?.trade_count}/><Metric label="OOS خالص P&L" value={optimizer.out_of_sample?.net_pnl}/><Metric label="OOS Expectancy" value={optimizer.out_of_sample?.expectancy_per_trade}/><pre>{JSON.stringify(optimizer.limitations, null, 2)}</pre></div>}
      </Panel>
      <Panel title="Phase 17 · Multi-Strategy Allocation" icon={<BarChart3 size={19}/> }>
        <p>معیارهای تحقیق هر استراتژی را وارد کن. خروجی یک تخصیص تحلیلی محدودشده با جریمه همبستگی است.</p>
        <textarea className="p1520-code p1520-short" value={strategies} onChange={e => setStrategies(e.target.value)} spellCheck={false}/>
        <button onClick={runAllocation} disabled={!!busy}>{busy === "allocation" ? "در حال محاسبه…" : "محاسبه تخصیص پیشنهادی"}</button>
        {allocation && <div className="p1520-result"><Metric label="سرمایه تخصیص‌یافته" value={`${allocation.allocated_pct}%`}/><Metric label="ذخیره نقدی" value={`${allocation.cash_reserve_pct}%`}/>{allocation.allocations?.map((a: any) => <Metric key={a.name} label={a.name} value={`${a.weight_pct}%`}/>)}</div>}
      </Panel>
      <Panel title="Phase 18 · Operational Monitoring" icon={<Activity size={19}/> }>
        {monitor ? <><Metric label="وضعیت عملیات" value={monitor.status}/><Metric label="زمان بررسی" value={monitor.checked_at}/>{monitor.checks?.map((c: any) => <Metric key={c.name} label={c.name} value={c.status}/>)}</> : <p>برای بررسی اتصال PostgreSQL، وضعیت عملیات را به‌روزرسانی کن.</p>}
      </Panel>
      <Panel title="Phase 19 · Security Audit" icon={<ShieldCheck size={19}/> }>
        {security ? <><Metric label="وضعیت بررسی محدود" value={security.status}/>{security.checks?.map((c: any) => <Metric key={c.name} label={c.name} value={c.status}/>)}</> : <p>گزارش امنیتی محدود به احراز هویت و دامنه پرتفوی انتخاب‌شده است.</p>}
      </Panel>
      <Panel title="Phase 20 · Release Readiness" icon={<CheckCircle2 size={19}/> }>
        {release ? <><Metric label="نتیجه ممیزی انتشار" value={release.status}/>{Object.entries(release.components || {}).map(([k,v]) => <Metric key={k} label={k} value={v}/>) }<p className="p1520-note">این گزارش آمادگی تحقیق و Paper را بررسی می‌کند؛ گواهی سودآوری یا مجوز معاملات واقعی نیست.</p></> : <p>برای ساخت گزارش نهایی، یک پرتفوی انتخاب و «به‌روزرسانی ممیزی‌ها» را اجرا کن.</p>}
      </Panel>
    </div>
    <footer className="p1520-footer">PAPER / RESEARCH ONLY · LIVE EXECUTION DISABLED</footer>
  </main>;
}
