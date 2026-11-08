"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, RefreshCw, ShieldCheck, Wallet, Zap } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Portfolio = { id: string; name: string; cash_equity?: number };
type Report = Record<string, any>;

async function api<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body as T;
}

export default function OperationsPage() {
  const [token, setToken] = useState("");
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [portfolioId, setPortfolioId] = useState("");
  const [reports, setReports] = useState<Record<string, Report>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preflight, setPreflight] = useState<Report | null>(null);
  const [side, setSide] = useState("long");
  const [quantity, setQuantity] = useState("0.01");
  const [entry, setEntry] = useState("60000");
  const [stop, setStop] = useState("59000");

  useEffect(() => {
    const saved = window.localStorage.getItem("smartmoney_v11_token");
    if (saved) setToken(saved);
    else setError("ابتدا از داشبورد اصلی TRADF وارد حساب کاربری شو.");
  }, []);

  useEffect(() => {
    if (!token) return;
    api<{items: Portfolio[]}>("/api/v1/v11/portfolios", token)
      .then((data) => {
        setPortfolios(data.items || []);
        if (data.items?.length) setPortfolioId((current) => current || data.items[0].id);
      })
      .catch((e) => setError(e.message));
  }, [token]);

  const refresh = useCallback(async () => {
    if (!token || !portfolioId) return;
    setLoading(true); setError(""); setPreflight(null);
    try {
      const base = `/api/v1/v11/portfolios/${portfolioId}`;
      const [paper, alerts, reliability] = await Promise.all([
        api<Report>(`${base}/paper-control`, token),
        api<Report>(`${base}/intelligence-alerts`, token),
        api<Report>(`${base}/reliability`, token),
      ]);
      const adaptive = await api<Report>(`${base}/adaptive-risk`, token, {
        method: "POST",
        body: JSON.stringify({ baseline_risk_pct: 0.25, max_risk_pct: 0.5,
          volatility_multiple: 1, drawdown_pct: 0, market_regime: "unknown" }),
      });
      setReports({ paper, alerts, reliability, adaptive });
    } catch (e: any) { setError(e.message || "خطا در دریافت گزارش‌ها"); }
    finally { setLoading(false); }
  }, [token, portfolioId]);

  useEffect(() => { if (portfolioId) void refresh(); }, [portfolioId, refresh]);

  async function runPreflight(event: FormEvent) {
    event.preventDefault(); setError(""); setPreflight(null);
    try {
      const result = await api<Report>(`/api/v1/v11/portfolios/${portfolioId}/execution-preflight`, token, {
        method: "POST",
        body: JSON.stringify({ side, quantity: Number(quantity), entry: Number(entry), stop_loss: Number(stop) }),
      });
      setPreflight(result);
    } catch (e: any) { setError(e.message || "خطای بررسی ریسک"); }
  }

  const paper = reports.paper || {};
  const reliability = reports.reliability || {};
  const alerts = reports.alerts || {};
  const adaptive = reports.adaptive || {};

  return <main className="p2125-page">
    <header className="p2125-header">
      <div><div className="p2125-eyebrow">TRADF / OPERATIONS SUITE · PHASES 21–25</div>
        <h1>مرکز عملیات معاملات آزمایشی</h1>
        <p>کنترل چرخه معاملات، پیش‌بررسی ریسک، هشدارها و سلامت داده‌ها؛ بدون ارسال سفارش واقعی.</p>
      </div>
      <button className="p2125-refresh" onClick={() => void refresh()} disabled={loading}>
        <RefreshCw size={16} className={loading ? "p2125-spin" : ""}/> به‌روزرسانی
      </button>
    </header>

    {error && <div className="p2125-error"><AlertTriangle size={17}/>{error}</div>}

    <section className="p2125-toolbar">
      <label>پرتفوی
        <select value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)}>
          {portfolios.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <span className="p2125-paper"><ShieldCheck size={15}/> PAPER ONLY · LIVE EXECUTION DISABLED</span>
    </section>

    <section className="p2125-grid">
      <article className="p2125-card">
        <div className="p2125-card-title"><Wallet size={18}/> چرخه معاملات · فاز ۲۱</div>
        <div className="p2125-number">{paper.trade_count ?? "—"}</div><small>کل معاملات ثبت‌شده</small>
        <div className="p2125-stats"><span>فعال: <b>{paper.active_trade_count ?? "—"}</b></span><span>بسته: <b>{paper.closed_trade_count ?? "—"}</b></span></div>
        <div className="p2125-sub">سود خالص تحقق‌یافته: <b>{paper.realized_net_pnl ?? "—"}</b></div>
        <div className={`p2125-status ${paper.status === "passed" ? "good" : "warn"}`}>{paper.status || "در انتظار داده"}</div>
      </article>

      <article className="p2125-card">
        <div className="p2125-card-title"><Zap size={18}/> ریسک تطبیقی · فاز ۲۳</div>
        <div className="p2125-number">{adaptive.recommended_risk_pct ?? "—"}<small>%</small></div>
        <small>ریسک پیشنهادی هر معامله</small>
        <div className="p2125-sub">ضریب نوسان: <b>{adaptive.volatility_factor ?? "—"}</b></div>
        <div className={`p2125-status ${adaptive.status === "recommendation_ready" ? "good" : "warn"}`}>{adaptive.status || "در انتظار داده"}</div>
      </article>

      <article className="p2125-card">
        <div className="p2125-card-title"><Activity size={18}/> هشدارهای بازار · فاز ۲۴</div>
        <div className="p2125-number">{alerts.alert_count ?? "—"}</div><small>هشدارهای مبتنی بر قیمت ذخیره‌شده</small>
        <div className="p2125-sub">وضعیت: <b>{alerts.status || "در انتظار داده"}</b></div>
        <div className="p2125-alert-list">{(alerts.alerts || []).slice(0, 4).map((a: any, i: number) =>
          <div key={`${a.code}-${i}`}><span>{a.severity}</span> {a.symbol}: {a.message}</div>)}</div>
      </article>

      <article className="p2125-card">
        <div className="p2125-card-title"><CheckCircle2 size={18}/> پایداری سرویس · فاز ۲۵</div>
        <div className={`p2125-number ${reliability.status === "ok" ? "p2125-positive" : ""}`}>{reliability.status || "—"}</div>
        <small>گزارش سلامت محدود به این پرتفوی</small>
        <div className="p2125-checks">{(reliability.checks || []).map((c: any) =>
          <div key={c.name}><span>{c.name}</span><b className={c.status === "passed" ? "p2125-positive" : "p2125-warning"}>{c.status}</b></div>)}</div>
      </article>
    </section>

    <section className="p2125-card p2125-preflight">
      <div className="p2125-card-title"><ShieldCheck size={18}/> پیش‌بررسی معامله · فاز ۲۲</div>
      <p>پیش از ایجاد معامله آزمایشی، ریسک اسمی را با محدودیت‌های پرتفوی مقایسه کن. این فرم سفارش ایجاد نمی‌کند.</p>
      <form onSubmit={runPreflight}>
        <label>جهت<select value={side} onChange={(e) => setSide(e.target.value)}><option value="long">Long</option><option value="short">Short</option></select></label>
        <label>حجم<input value={quantity} onChange={(e) => setQuantity(e.target.value)} type="number" min="0.00000001" step="any" required/></label>
        <label>قیمت ورود<input value={entry} onChange={(e) => setEntry(e.target.value)} type="number" min="0.00000001" step="any" required/></label>
        <label>حد ضرر<input value={stop} onChange={(e) => setStop(e.target.value)} type="number" min="0.00000001" step="any" required/></label>
        <button type="submit" disabled={!portfolioId}>بررسی ریسک</button>
      </form>
      {preflight && <div className={`p2125-preflight-result ${preflight.status === "passed" ? "good" : "warn"}`}>
        <b>{preflight.status === "passed" ? "پیش‌بررسی موفق" : "معامله از محدودیت‌ها عبور می‌کند"}</b>
        <span>ریسک معامله: {preflight.proposed_risk_cash} · {preflight.proposed_risk_pct}%</span>
        <span>ریسک باز پس از معامله: {preflight.projected_open_risk_pct}%</span>
        {(preflight.rejection_reasons || []).map((r: string) => <span key={r}>{r}</span>)}
      </div>}
    </section>

    <footer className="p2125-footer">این صفحه ابزار کنترل و تحلیل معاملات آزمایشی است. داده‌های لحظه‌ای تضمین نمی‌شوند و هیچ سفارش واقعی به صرافی یا MT5 ارسال نمی‌شود.</footer>
  </main>;
}
