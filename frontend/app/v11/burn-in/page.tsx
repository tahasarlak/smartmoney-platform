"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Activity, AlertTriangle, CheckCircle2, Clock3, RefreshCw, ShieldCheck, XCircle } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Portfolio = { id: string; name: string };
type BurnInReport = {
  status: string;
  portfolio_name: string;
  portfolio_trade_count: number;
  active_trade_count: number;
  pending_entry_count: number;
  closed_trade_count: number;
  journal_event_count: number;
  window_event_count: number;
  window_hours: number;
  observation_span_minutes: number;
  minimum_observation_minutes: number;
  minimum_events: number;
  activity_requirement_met: boolean;
  observation_requirement_met: boolean;
  stale_active_trade_ids: string[];
  integrity_issue_count: number;
  issues: { trade_id: string; code: string; detail: string }[];
  warnings: { code: string; detail: string }[];
  realized_net_pnl: number;
  execution_allowed: false;
  limitations: string[];
};

const statusText: Record<string, string> = {
  passed: "آزمون نمونه موفق",
  review_required: "نیازمند بررسی",
  degraded: "وضعیت نامطلوب",
  insufficient_activity: "فعالیت کافی وجود ندارد",
  insufficient_observation: "دوره مشاهده کافی نیست",
};

export default function BurnInPage() {
  const [token, setToken] = useState("");
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [portfolioId, setPortfolioId] = useState("");
  const [report, setReport] = useState<BurnInReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const saved = window.localStorage.getItem("smartmoney_v11_token") || "";
    setToken(saved);
  }, []);

  const request = useCallback(async (path: string) => {
    const response = await fetch(`${API}${path}`, {
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      cache: "no-store",
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    return body;
  }, [token]);

  const loadPortfolios = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const body = await request("/api/v1/v11/portfolios");
      const items = (body.items || []) as Portfolio[];
      setPortfolios(items);
      setPortfolioId(current => current && items.some(x => x.id === current) ? current : (items[0]?.id || ""));
    } catch (e) {
      setError(e instanceof Error ? e.message : "بارگذاری پرتفوی ناموفق بود");
    } finally {
      setLoading(false);
    }
  }, [request, token]);

  const loadReport = useCallback(async () => {
    if (!token || !portfolioId) return;
    setLoading(true);
    setError("");
    try {
      const body = await request(
        `/api/v1/v11/portfolios/${encodeURIComponent(portfolioId)}/burn-in?limit=500&window_hours=24&stale_after_seconds=300&minimum_events=5&minimum_observation_minutes=30`
      );
      setReport(body as BurnInReport);
    } catch (e) {
      setError(e instanceof Error ? e.message : "گزارش Burn-in دریافت نشد");
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [portfolioId, request, token]);

  useEffect(() => { if (token) void loadPortfolios(); }, [token, loadPortfolios]);
  useEffect(() => { if (portfolioId) void loadReport(); }, [portfolioId, loadReport]);

  const statusIcon = report?.status === "passed"
    ? <CheckCircle2 size={20}/>
    : report?.status === "review_required" || report?.status === "degraded"
      ? <XCircle size={20}/>
      : <AlertTriangle size={20}/>;

  if (!token) return <main className="p31-shell"><header><Link href="/v11">← بازگشت به TRADF</Link></header><section className="p31-card"><h1>Paper Trading Burn-in</h1><p>ابتدا وارد محیط TRADF شوید تا گزارش پرتفوی نمایش داده شود.</p><Link href="/v11">ورود به محیط معاملاتی</Link></section></main>;

  return (
    <main className="p31-shell">
      <header className="p31-header">
        <div><Link href="/v11">TRADF / V11</Link><span> / Burn-in Validation</span></div>
        <button onClick={() => { void loadPortfolios(); if (portfolioId) void loadReport(); }} disabled={loading}><RefreshCw size={16}/> به‌روزرسانی</button>
      </header>
      <section className="p31-hero">
        <span className="p31-eyebrow"><Activity size={15}/> PHASE 31 · PAPER OPERATIONS</span>
        <h1>اعتبارسنجی چرخه معاملات آزمایشی</h1>
        <p>تطبیق معاملات ذخیره‌شده، دفتر رویدادها، کارمزدها و فعالیت اخیر پرتفوی.</p>
        <label>پرتفوی
          <select value={portfolioId} onChange={e => setPortfolioId(e.target.value)}>
            {portfolios.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      </section>

      {error && <div className="p31-error"><AlertTriangle size={17}/>{error}</div>}
      {loading && <div className="p31-card">در حال دریافت گزارش…</div>}

      {report && !loading && <>
        <section className={`p31-status p31-${report.status}`}>
          {statusIcon}
          <div><b>{statusText[report.status] || report.status}</b><span>این نتیجه فقط مربوط به نمونه داده بررسی‌شده است؛ گواهی آمادگی معاملات زنده نیست.</span></div>
          <span className="p31-paper"><ShieldCheck size={14}/> PAPER ONLY</span>
        </section>
        <section className="p31-grid">
          <article><span>کل معاملات بررسی‌شده</span><b>{report.portfolio_trade_count}</b></article>
          <article><span>معاملات فعال</span><b>{report.active_trade_count}</b></article>
          <article><span>رویدادهای ۲۴ ساعت</span><b>{report.window_event_count}</b></article>
          <article><span>رویدادهای دفتر کل</span><b>{report.journal_event_count}</b></article>
          <article><span>سود خالص ثبت‌شده</span><b>{report.realized_net_pnl.toFixed(4)}</b></article>
          <article><span>مغایرت‌های ثبت</span><b>{report.integrity_issue_count}</b></article>
        </section>
        <section className="p31-card">
          <h2>پوشش دوره مشاهده</h2>
          <div className="p31-progress"><span style={{width:`${Math.min(100, report.observation_span_minutes / Math.max(1, report.minimum_observation_minutes) * 100)}%`}}/></div>
          <p>{report.observation_span_minutes} دقیقه مشاهده‌شده از حداقل {report.minimum_observation_minutes} دقیقه موردنیاز</p>
          <p>{report.window_event_count} رویداد از حداقل {report.minimum_events} رویداد موردنیاز</p>
        </section>
        <section className="p31-card">
          <h2>مغایرت‌ها و هشدارها</h2>
          {report.issues.length === 0 && report.warnings.length === 0
            ? <p className="p31-good">مغایرتی در نمونه بررسی‌شده پیدا نشد.</p>
            : <ul>{[...report.issues, ...report.warnings].map((item, i) => <li key={`${item.code}-${i}`}><b>{item.code}</b> — {item.detail}</li>)}</ul>}
        </section>
        <section className="p31-card">
          <h2>محدودیت‌های گزارش</h2>
          <ul>{report.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul>
        </section>
      </>}
      <footer>TRADF · PHASE 31 · READ-ONLY PAPER TRADING VALIDATION · LIVE EXECUTION DISABLED</footer>
    </main>
  );
}
