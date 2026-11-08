"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowUpRight, BarChart3, Bell, BookOpen,
  CandlestickChart, CheckCircle2, ChevronDown, CircleHelp, Clock3,
  Cpu, Gauge, Globe2, LayoutDashboard, LineChart, Menu, RefreshCw,
  Search, Shield, ShieldAlert, Sparkles, Target, Wallet, X, Zap
} from "lucide-react";
import {
  CandlestickSeries, ColorType, createChart, type IChartApi,
} from "lightweight-charts";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

type Candle = { time: number; open: number; high: number; low: number; close: number; volume?: number };
type Analysis = {
  structure?: string; directional_bias?: string; quality_score?: number;
  estimated_win_probability?: number | null; probability_status?: string;
  events?: Array<{ type?: string; direction?: string; level?: number }>;
  zones?: Array<{ type?: string; direction?: string; low?: number; high?: number }>;
  last_price?: number; disclaimer?: string;
};
type Health = { status?: string; environment?: string; live_trading_enabled?: boolean };
type Opportunity = { symbol?: string; direction?: string; signal_state?: string; state?: string; quality_score?: number; reasons?: string[]; plan?: { entry?: number; stop_loss?: number; take_profits?: Array<{ price: number }> } };

type Lang = "fa" | "en";
const copy = {
  fa: {
    navOverview: "نمای کلی", navMarkets: "بازارها و تحلیل", navPlanner: "برنامه‌ریز سرمایه", navPortfolio: "پرتفوی آزمایشی", navResearch: "هوشمندی بازار",
    terminal: "ترمینال هوشمند معاملاتی", subtitle: "تحلیل بازار، سنجش ریسک و بررسی سناریوهای معاملاتی در یک محیط واحد.", paper: "فقط محیط آزمایشی", liveOff: "معاملات واقعی غیرفعال", refresh: "به‌روزرسانی", scanning: "در حال تحلیل…", scan: "تحلیل بازار",
    equity: "سرمایه شبیه‌سازی‌شده", dayPnl: "سود و زیان تحقق‌یافته", openPositions: "موقعیت‌های باز", portfolioRisk: "ریسک باز پرتفوی", noAccount: "برای مشاهده اطلاعات واقعی پرتفوی، وارد فضای آزمایشی V11 شوید.",
    market: "بازار منتخب", priceAction: "رفتار قیمت", structure: "ساختار بازار", bias: "جهت غالب تحلیل", quality: "امتیاز کیفیت ستاپ", events: "رویدادهای ساختاری", zones: "مناطق هوشمند", notProbability: "احتمال برد تأیید نشده", noSignal: "هنوز ستاپ تأییدشده‌ای دریافت نشده است.",
    planner: "برنامه‌ریز سناریوی معامله", plannerSub: "سرمایه، نقطه ورود و حد ضرر را وارد کنید تا اندازه موقعیت و پیامدهای فرضی محاسبه شود.", capital: "سرمایه حساب", riskPct: "ریسک مجاز این سناریو (%)", entry: "قیمت ورود فرضی", stop: "حد ضرر فرضی", target: "هدف قیمتی فرضی", side: "جهت سناریو", long: "خرید (Long)", short: "فروش (Short)", calc: "محاسبه سناریو", riskCash: "مبلغ در معرض ریسک", qty: "حجم محاسباتی", notional: "ارزش اسمی موقعیت", grossLoss: "زیان فرضی تا حد ضرر", grossProfit: "سود فرضی تا هدف", rr: "نسبت سود به زیان", remaining: "سرمایه پس از حد ضرر", warning: "این محاسبه صرفاً سناریوی آموزشی است؛ کارمزد، لغزش قیمت، Funding، اهرم، نقدشوندگی و مشخصات قرارداد در آن لحاظ نشده‌اند. این خروجی توصیه سرمایه‌گذاری یا وعده سود نیست.",
    intelligence: "هوشمندی بازار", scanner: "اسکنر چندنمادی", scanNow: "اجرای اسکن تحقیقاتی", opportunities: "فرصت‌های شناسایی‌شده", monitor: "وضعیت مانیتور بازار", api: "وضعیت API", database: "دیتابیس", connected: "متصل", unavailable: "در دسترس نیست", idle: "بدون داده زنده", lastPrice: "آخرین قیمت", timeframe: "تایم‌فریم", symbol: "نماد", selectSymbol: "انتخاب نماد", noEvents: "رویداد معتبری در داده فعلی شناسایی نشد.", noZones: "منطقه‌ای در تحلیل فعلی گزارش نشده است.", reasons: "دلایل تحلیل", openWorkspace: "ورود به فضای آزمایشی", docs: "مستندات API", status: "وضعیت سامانه", updated: "آخرین به‌روزرسانی", loading: "در حال دریافت داده…", error: "خطا در دریافت داده", dataSource: "منبع داده: Binance عمومی و API پروژه", scoreNote: "امتیاز کیفیت، احتمال برد نیست.", greeting: "تصمیم بهتر با داده شفاف شروع می‌شود.", researchOnly: "تحقیق و شبیه‌سازی؛ بدون ارسال سفارش واقعی", marketOverview: "نمای بازار", setup: "سناریوی معاملاتی", execution: "اجرا", disabled: "غیرفعال", navMenu: "منو", noOpportunities: "فرصتی در آخرین اسکن گزارش نشده است.", notReady: "هنوز ارزیابی نشده", showAll: "مشاهده همه", choose: "انتخاب کنید", gross: "ناخالص", portfolioLink: "مدیریت پرتفوی و معاملات آزمایشی",
  },
  en: {
    navOverview: "Overview", navMarkets: "Markets & Analysis", navPlanner: "Investment Planner", navPortfolio: "Paper Portfolio", navResearch: "Market Intelligence",
    terminal: "Intelligent Trading Terminal", subtitle: "Market research, risk sizing and trade scenarios in one workspace.", paper: "PAPER ENVIRONMENT", liveOff: "LIVE TRADING DISABLED", refresh: "Refresh", scanning: "Analyzing…", scan: "Analyze market",
    equity: "Simulated equity", dayPnl: "Realized P&L", openPositions: "Open positions", portfolioRisk: "Open portfolio risk", noAccount: "Open the V11 paper workspace to view account-specific portfolio data.",
    market: "Selected market", priceAction: "Price action", structure: "Market structure", bias: "Directional bias", quality: "Setup quality score", events: "Structure events", zones: "Smart money zones", notProbability: "Win probability not validated", noSignal: "No confirmed setup has been returned yet.",
    planner: "Trade scenario planner", plannerSub: "Enter capital, entry and stop levels to calculate position size and hypothetical outcomes.", capital: "Account capital", riskPct: "Scenario risk (%)", entry: "Hypothetical entry", stop: "Hypothetical stop", target: "Hypothetical target", side: "Scenario direction", long: "Long", short: "Short", calc: "Calculate scenario", riskCash: "Cash at risk", qty: "Calculated quantity", notional: "Position notional", grossLoss: "Hypothetical loss at stop", grossProfit: "Hypothetical profit at target", rr: "Reward / risk", remaining: "Equity after stop", warning: "Educational scenario only. Fees, slippage, funding, leverage, liquidity and contract specifications are excluded. This is not investment advice or a profit promise.",
    intelligence: "Market intelligence", scanner: "Multi-symbol scanner", scanNow: "Run research scan", opportunities: "Detected opportunities", monitor: "Market monitor", api: "API status", database: "Database", connected: "Connected", unavailable: "Unavailable", idle: "No live data", lastPrice: "Last price", timeframe: "Timeframe", symbol: "Symbol", selectSymbol: "Select symbol", noEvents: "No qualifying structure events in current data.", noZones: "No zones reported in this analysis.", reasons: "Research notes", openWorkspace: "Open paper workspace", docs: "API documentation", status: "System status", updated: "Last updated", loading: "Loading data…", error: "Data request failed", dataSource: "Data source: public Binance market data and project API", scoreNote: "Quality score is not win probability.", greeting: "Better decisions start with transparent data.", researchOnly: "Research and simulation; no live orders are sent", marketOverview: "Market overview", setup: "Trade scenario", execution: "Execution", disabled: "Disabled", navMenu: "Menu", noOpportunities: "No opportunities reported by the latest scan.", notReady: "Not evaluated", showAll: "View all", choose: "Select", gross: "Gross", portfolioLink: "Portfolio & paper trading workspace",
  }
} as const;

function fmt(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
function pretty(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value).replaceAll("_", " ").replaceAll("-", " ").toUpperCase();
}

function PriceChart({ data }: { data: Candle[] }) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  useEffect(() => {
    if (!host.current || !data.length) return;
    const chart = createChart(host.current, {
      width: host.current.clientWidth, height: 330,
      layout: { background: { type: ColorType.Solid, color: "#0b1220" }, textColor: "#8795aa", fontFamily: "Inter, sans-serif" },
      grid: { vertLines: { color: "#172338" }, horzLines: { color: "#172338" } },
      rightPriceScale: { borderColor: "#25334a" }, timeScale: { borderColor: "#25334a", timeVisible: true },
      crosshair: { vertLine: { color: "#59718f" }, horzLine: { color: "#59718f" } },
    });
    chartRef.current = chart;
    const series = chart.addSeries(CandlestickSeries, { upColor: "#39d6a0", downColor: "#f16b83", borderVisible: false, wickUpColor: "#39d6a0", wickDownColor: "#f16b83" });
    series.setData(data.map(c => ({ time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close })));
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(entries => { for (const entry of entries) chart.applyOptions({ width: Math.max(280, entry.contentRect.width) }); });
    observer.observe(host.current);
    return () => { observer.disconnect(); chart.remove(); chartRef.current = null; };
  }, [data]);
  return <div ref={host} className="tradf-chart" />;
}

export default function Home() {
  const [lang, setLang] = useState<Lang>("fa");
  const t = copy[lang];
  const [active, setActive] = useState("overview");
  const [mobileNav, setMobileNav] = useState(false);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("15m");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [ready, setReady] = useState<any>(null);
  const [monitor, setMonitor] = useState<any>(null);
  const [v8, setV8] = useState<any>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [busy, setBusy] = useState(false);
  const [scanBusy, setScanBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [capital, setCapital] = useState("10000");
  const [riskPct, setRiskPct] = useState("0.5");
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [direction, setDirection] = useState<"long" | "short">("long");

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(`${API}${path}`, { ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`);
    return body;
  }, []);

  const loadHealth = useCallback(async () => {
    try {
      const [h, r, m, v] = await Promise.allSettled([
        request("/health"), request("/health/ready"), request("/api/v1/monitor/operational-health"), request("/api/v1/intelligence/v8/latest")
      ]);
      if (h.status === "fulfilled") setHealth(h.value);
      if (r.status === "fulfilled") setReady(r.value);
      if (m.status === "fulfilled") setMonitor(m.value);
      if (v.status === "fulfilled") { setV8(v.value.result || null); setOpportunities(v.value.result?.opportunities || []); }
      setLastUpdated(new Date());
    } catch { /* individual service states remain visible */ }
  }, [request]);

  const runAnalysis = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const market = await request("/api/v1/market/binance/klines", { method: "POST", body: JSON.stringify({ symbol, interval, limit: 300 }) });
      const rows: Candle[] = Array.isArray(market.candles) ? market.candles : [];
      setCandles(rows);
      if (rows.length) {
        const result = await request("/api/v1/analysis/smc", { method: "POST", body: JSON.stringify({ symbol, candles: rows, swing_length: 3, equal_level_tolerance_pct: 0.05 }) });
        setAnalysis(result);
        const current = Number(result.last_price || rows[rows.length - 1]?.close || 0);
        if (current > 0) {
          setEntry(String(current));
          setStop(String(direction === "long" ? current * 0.99 : current * 1.01));
          setTarget(String(direction === "long" ? current * 1.02 : current * 0.98));
        }
      } else throw new Error("Market API returned no candles");
      setLastUpdated(new Date());
    } catch (e) { setError(e instanceof Error ? e.message : "Market analysis failed"); }
    finally { setBusy(false); }
  }, [request, symbol, interval, direction]);

  const runScanner = useCallback(async () => {
    setScanBusy(true); setError("");
    try {
      const result = await request("/api/v1/intelligence/v8/scan", { method: "POST", body: JSON.stringify({ symbols: ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"], limit: 300, persist_signals: false }) });
      setV8(result); setOpportunities(result.opportunities || []); setLastUpdated(new Date());
    } catch (e) { setError(e instanceof Error ? e.message : "Research scan failed"); }
    finally { setScanBusy(false); }
  }, [request]);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  }, [lang]);
  useEffect(() => { void loadHealth(); void runAnalysis(); }, [loadHealth, runAnalysis]);

  const planner = useMemo(() => {
    const c = Number(capital), r = Number(riskPct), e = Number(entry), s = Number(stop), targetPrice = Number(target);
    if (!(c > 0 && r > 0 && r <= 5 && e > 0 && s > 0 && targetPrice > 0)) return null;
    const stopDistance = direction === "long" ? e - s : s - e;
    const targetDistance = direction === "long" ? targetPrice - e : e - targetPrice;
    if (!(stopDistance > 0 && targetDistance > 0)) return null;
    const riskBudget = c * r / 100;
    const rawQty = riskBudget / stopDistance;
    const qty = Math.min(rawQty, c / e);
    const notional = qty * e;
    const actualRisk = qty * stopDistance;
    const grossProfit = qty * targetDistance;
    return { qty, notional, actualRisk, grossProfit, rr: grossProfit / actualRisk, remaining: c - actualRisk, riskBudget, capped: qty < rawQty };
  }, [capital, riskPct, entry, stop, target, direction]);

  const currentPrice = analysis?.last_price ?? candles[candles.length - 1]?.close;
  const navItems = [
    { id: "overview", label: t.navOverview, icon: LayoutDashboard },
    { id: "markets", label: t.navMarkets, icon: CandlestickChart },
    { id: "planner", label: t.navPlanner, icon: Target },
    { id: "research", label: t.navResearch, icon: Sparkles },
  ];
  const go = (id: string) => { setActive(id); setMobileNav(false); document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }); };

  return <main className="tradf-app">
    <aside className={`tradf-sidebar ${mobileNav ? "is-open" : ""}`}>
      <div className="tradf-brand"><div className="tradf-logo">T</div><div><strong>TRADF<span>.</span></strong><small>SMART MONEY TERMINAL</small></div><button className="mobile-close" onClick={() => setMobileNav(false)} aria-label="Close menu"><X size={18}/></button></div>
      <div className="sidebar-label">{lang === "fa" ? "فضای کاری" : "WORKSPACE"}</div>
      <nav>{navItems.map(item => { const Icon = item.icon; return <button key={item.id} className={`nav-item ${active === item.id ? "active" : ""}`} onClick={() => go(item.id)}><Icon size={17}/><span>{item.label}</span>{active === item.id && <i/>}</button>; })}</nav>
      <div className="sidebar-spacer"/>
      <div className="sidebar-status"><div className="status-orb"/><div><b>{t.paper}</b><small>{t.researchOnly}</small></div></div>
      <a className="sidebar-v11" href="/v11"><Wallet size={16}/><span>{t.openWorkspace}</span><ArrowUpRight size={14}/></a>
      <div className="sidebar-footer">TRADF RESEARCH TERMINAL <span>·</span> V1</div>
    </aside>
    {mobileNav && <button className="nav-scrim" onClick={() => setMobileNav(false)} aria-label="Close navigation"/>}

    <section className="tradf-main">
      <header className="tradf-topbar">
        <div className="topbar-left"><button className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open menu"><Menu size={19}/></button><div className="breadcrumb">TRADF <span>/</span> {navItems.find(x => x.id === active)?.label || t.navOverview}</div></div>
        <div className="topbar-actions"><span className="environment-pill"><i/> {t.paper}</span><button className="icon-action" onClick={() => { void loadHealth(); void runAnalysis(); }} title={t.refresh}><RefreshCw size={16}/></button><button className="lang-action" onClick={() => setLang(lang === "fa" ? "en" : "fa")}>{lang === "fa" ? "EN" : "فا"}</button></div>
      </header>

      <div className="page-content">
        <section className="welcome-row" id="overview">
          <div><div className="eyebrow"><span/> {t.terminal}</div><h1>{t.greeting}</h1><p>{t.subtitle}</p></div>
          <div className="welcome-actions"><span className="safety-badge"><Shield size={14}/> {t.liveOff}</span><button className="primary-button" onClick={runAnalysis} disabled={busy}><Zap size={16}/>{busy ? t.scanning : t.scan}</button></div>
        </section>

        {error && <div className="alert-banner"><ShieldAlert size={17}/><span>{t.error}: {error}</span><button onClick={() => setError("")}><X size={15}/></button></div>}

        <section className="metric-grid">
          <article className="metric-card featured"><div className="metric-top"><span>{t.market}</span><span className="metric-icon"><Activity size={16}/></span></div><div className="metric-main mono">{symbol}</div><div className="metric-bottom"><span>{t.lastPrice}</span><b>{fmt(currentPrice, 2)} USDT</b></div></article>
          <article className="metric-card"><div className="metric-top"><span>{t.structure}</span><span className="metric-icon"><GitStructureIcon/></span></div><div className="metric-main">{pretty(analysis?.structure)}</div><div className="metric-bottom"><span>{t.bias}</span><b>{pretty(analysis?.directional_bias)}</b></div></article>
          <article className="metric-card"><div className="metric-top"><span>{t.quality}</span><span className="metric-icon"><Gauge size={16}/></span></div><div className="metric-main">{analysis?.quality_score != null ? `${fmt(analysis.quality_score, 0)}/100` : "—"}</div><div className="metric-bottom"><span>{t.notProbability}</span><b className="muted-text">—</b></div></article>
          <article className="metric-card"><div className="metric-top"><span>{t.api}</span><span className="metric-icon"><Globe2 size={16}/></span></div><div className="metric-main status-main"><i className={health?.status === "ok" ? "good-dot" : "bad-dot"}/>{health?.status === "ok" ? t.connected : t.unavailable}</div><div className="metric-bottom"><span>{t.database}</span><b className={ready?.status === "ready" ? "positive-text" : "muted-text"}>{ready?.status === "ready" ? t.connected : t.notReady}</b></div></article>
        </section>

        <section className="content-grid" id="markets">
          <article className="panel chart-panel">
            <div className="panel-heading"><div><div className="panel-kicker"><LineChart size={14}/> {t.marketOverview}</div><h2>{t.priceAction}</h2><p>{t.dataSource}</p></div><div className="chart-controls"><select value={symbol} onChange={e => setSymbol(e.target.value)} aria-label={t.symbol}>{["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"].map(x => <option key={x}>{x}</option>)}</select><select value={interval} onChange={e => setInterval(e.target.value)} aria-label={t.timeframe}>{["5m", "15m", "1h", "4h", "1d"].map(x => <option key={x}>{x}</option>)}</select><button className="icon-action chart-refresh" onClick={runAnalysis} disabled={busy} aria-label={t.refresh}><RefreshCw size={15}/></button></div></div>
            {candles.length ? <PriceChart data={candles}/> : <div className="chart-empty">{busy ? t.loading : t.unavailable}</div>}
            <div className="chart-foot"><span><i className="legend-up"/> {lang === "fa" ? "صعودی" : "Bullish"}</span><span><i className="legend-down"/> {lang === "fa" ? "نزولی" : "Bearish"}</span><span className="chart-time"><Clock3 size={13}/> {lastUpdated ? lastUpdated.toLocaleTimeString(lang === "fa" ? "fa-IR" : "en-US") : "—"}</span></div>
          </article>
          <article className="panel analysis-panel">
            <div className="panel-heading compact"><div><div className="panel-kicker"><Cpu size={14}/> SMC ENGINE</div><h2>{t.intelligence}</h2></div><span className="live-indicator"><i/> API</span></div>
            <div className="analysis-highlight"><span>{t.bias}</span><strong>{pretty(analysis?.directional_bias)}</strong><small>{pretty(analysis?.structure)}</small></div>
            <div className="data-row"><span>{t.lastPrice}</span><b className="mono">{fmt(currentPrice, 2)}</b></div>
            <div className="data-row"><span>{t.events}</span><b>{analysis?.events?.length ?? "—"}</b></div>
            <div className="data-row"><span>{t.zones}</span><b>{analysis?.zones?.length ?? "—"}</b></div>
            <div className="probability-note"><ShieldAlert size={15}/><span>{t.scoreNote} {analysis?.disclaimer || ""}</span></div>
            <button className="outline-button full-button" onClick={() => go("planner")}><Target size={15}/>{t.planner}</button>
          </article>
        </section>

        <section className="panel planner-panel" id="planner">
          <div className="panel-heading planner-heading"><div><div className="panel-kicker"><Target size={14}/> CAPITAL & RISK</div><h2>{t.planner}</h2><p>{t.plannerSub}</p></div><span className="simulation-label">{lang === "fa" ? "محاسبه فرضی" : "WHAT-IF SIMULATION"}</span></div>
          <div className="planner-layout">
            <div className="planner-inputs">
              <label>{t.capital}<div className="input-wrap"><input inputMode="decimal" type="number" min="1" step="any" value={capital} onChange={e => setCapital(e.target.value)}/><span>USDT</span></div></label>
              <label>{t.riskPct}<div className="input-wrap"><input type="number" min="0.01" max="5" step="0.05" value={riskPct} onChange={e => setRiskPct(e.target.value)}/><span>%</span></div></label>
              <label>{t.entry}<div className="input-wrap"><input type="number" min="0" step="any" value={entry} onChange={e => setEntry(e.target.value)} placeholder="—"/></div></label>
              <label>{t.stop}<div className="input-wrap"><input type="number" min="0" step="any" value={stop} onChange={e => setStop(e.target.value)} placeholder="—"/></div></label>
              <label>{t.target}<div className="input-wrap"><input type="number" min="0" step="any" value={target} onChange={e => setTarget(e.target.value)} placeholder="—"/></div></label>
              <label>{t.side}<select className="direction-select" value={direction} onChange={e => setDirection(e.target.value as "long" | "short") }><option value="long">{t.long}</option><option value="short">{t.short}</option></select></label>
            </div>
            <div className="planner-results">
              {planner ? <>
                <div className="result-hero"><div><span>{t.riskCash}</span><strong className="negative-text">{fmt(planner.actualRisk)} USDT</strong></div><div className="rr-chip"><span>{t.rr}</span><b>{fmt(planner.rr)}R</b></div></div>
                <div className="result-grid"><div className="result-tile"><span>{t.qty}</span><b>{fmt(planner.qty, 6)}</b></div><div className="result-tile"><span>{t.notional}</span><b>{fmt(planner.notional)} USDT</b></div><div className="result-tile loss"><span>{t.grossLoss}</span><b>−{fmt(planner.actualRisk)} USDT</b></div><div className="result-tile profit"><span>{t.grossProfit}</span><b>+{fmt(planner.grossProfit)} USDT</b></div><div className="result-tile"><span>{t.remaining}</span><b>{fmt(planner.remaining)} USDT</b></div><div className="result-tile"><span>{t.riskPct}</span><b>{fmt(planner.actualRisk / Number(capital) * 100, 3)}%</b></div></div>
                {planner.capped && <div className="inline-note">{lang === "fa" ? "حجم به دلیل محدودیت سرمایه نقدی کاهش یافته است." : "Quantity was capped by available cash; leverage is not assumed."}</div>}
              </> : <div className="planner-placeholder"><CalculatorIcon/><b>{lang === "fa" ? "مقادیر معتبر وارد کنید" : "Enter valid scenario values"}</b><span>{lang === "fa" ? "حد ضرر باید در جهت درست نسبت به ورود باشد و هدف نیز در جهت سود قرار گیرد." : "Stop and target must be on the correct side of entry for the selected direction."}</span></div>}
            </div>
          </div>
          <div className="risk-disclaimer"><ShieldAlert size={17}/><span>{t.warning}</span></div>
        </section>

        <section className="research-section" id="research">
          <div className="section-heading"><div><div className="panel-kicker"><Sparkles size={14}/> RESEARCH ENGINE</div><h2>{t.opportunities}</h2><p>{t.researchOnly}</p></div><button className="primary-button" onClick={runScanner} disabled={scanBusy}><Zap size={15}/>{scanBusy ? t.scanning : t.scanNow}</button></div>
          {opportunities.length ? <div className="opportunity-grid">{opportunities.slice(0, 8).map((item, index) => <article className="opportunity-card" key={`${item.symbol}-${item.direction}-${index}`}><div className="opportunity-top"><b className="mono">{item.symbol || "—"}</b><span className={`direction-tag ${String(item.direction).toLowerCase() === "short" ? "short" : "long"}`}>{pretty(item.direction)}</span></div><div className="opportunity-meta"><span>{pretty(item.signal_state || item.state)}</span><b>{fmt(item.quality_score, 0)}/100</b></div>{item.plan && <div className="opportunity-levels"><div><span>{t.entry}</span><b>{fmt(item.plan.entry, 4)}</b></div><div><span>{t.stop}</span><b>{fmt(item.plan.stop_loss, 4)}</b></div><div><span>TP</span><b>{fmt(item.plan.take_profits?.[0]?.price, 4)}</b></div></div>}<div className="opportunity-reasons">{(item.reasons || []).slice(0, 3).join(" · ") || t.notReady}</div><small>{t.scoreNote}</small></article>)}</div> : <div className="empty-opportunities"><Sparkles size={22}/><b>{t.noOpportunities}</b><span>{t.notProbability}</span></div>}
        </section>

        <section className="bottom-cards">
          <article className="panel"><div className="panel-heading compact"><div><div className="panel-kicker"><Activity size={14}/> MARKET STRUCTURE</div><h2>{t.events}</h2></div><span className="count-badge">{analysis?.events?.length ?? 0}</span></div>{analysis?.events?.length ? analysis.events.slice(-6).reverse().map((event, i) => <div className="list-row" key={i}><span>{pretty(event.type)} · {pretty(event.direction)}</span><b className="mono">{fmt(event.level, 4)}</b></div>) : <div className="empty-small">{t.noEvents}</div>}</article>
          <article className="panel"><div className="panel-heading compact"><div><div className="panel-kicker"><Target size={14}/> PRICE ZONES</div><h2>{t.zones}</h2></div><span className="count-badge">{analysis?.zones?.length ?? 0}</span></div>{analysis?.zones?.length ? analysis.zones.slice(-6).reverse().map((zone, i) => <div className="list-row" key={i}><span>{pretty(zone.type)} · {pretty(zone.direction)}</span><b className="mono">{fmt(zone.low, 3)} – {fmt(zone.high, 3)}</b></div>) : <div className="empty-small">{t.noZones}</div>}</article>
          <article className="panel system-panel"><div className="panel-heading compact"><div><div className="panel-kicker"><Shield size={14}/> SYSTEM SAFETY</div><h2>{t.status}</h2></div><CheckCircle2 size={18} className="positive-text"/></div><div className="list-row"><span>{t.api}</span><b className={health?.status === "ok" ? "positive-text" : "muted-text"}>{health?.status === "ok" ? t.connected : t.unavailable}</b></div><div className="list-row"><span>{t.database}</span><b className={ready?.status === "ready" ? "positive-text" : "muted-text"}>{ready?.status === "ready" ? t.connected : t.notReady}</b></div><div className="list-row"><span>{t.execution}</span><b className="warning-text">{t.disabled}</b></div><div className="list-row"><span>{t.monitor}</span><b>{pretty(monitor?.status || "unknown")}</b></div><div className="system-foot">{t.updated}: {lastUpdated ? lastUpdated.toLocaleString(lang === "fa" ? "fa-IR" : "en-US") : "—"}</div></article>
        </section>

        <footer className="tradf-footer"><div className="tradf-logo mini">T</div><span>TRADF · SMART MONEY RESEARCH PLATFORM</span><span>{t.researchOnly}</span><a href={`${API}/docs`} target="_blank" rel="noreferrer"><BookOpen size={13}/> {t.docs}</a></footer>
      </div>
    </section>
  </main>;
}

function GitStructureIcon() { return <BarChart3 size={16}/>; }
function CalculatorIcon() { return <CircleHelp size={22}/>; }
