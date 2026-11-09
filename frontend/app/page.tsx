 "use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  Activity, ArrowDownRight, ArrowUpRight, BarChart3, CheckCircle2,
  ChevronDown, CircleHelp, KeyRound, LayoutDashboard, LogOut,
  Plus, RefreshCw, ShieldCheck, Wallet, Zap
} from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "smartmoney_v11_token";

type Portfolio = {
  id: string; name: string; base_currency: string; initial_equity: number;
  realized_pnl: number; cash_equity: number; open_positions: number;
  open_risk_cash: number; open_risk_pct: number; max_trade_risk_pct: number;
};
type Status = { vault_ready?: boolean; testnet_order_placement_enabled?: boolean; global_kill_switch_enabled?: boolean; live_trading_enabled?: boolean };
type Worker = { status?: string; worker_running?: boolean; heartbeat_age_seconds?: number | null };

const money = (v: number | undefined, currency = "USDT") =>
  `${Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: 2 })} ${currency}`;

export default function Home() {
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [register, setRegister] = useState(false);
  const [userEmail, setUserEmail] = useState("");
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [portfolioId, setPortfolioId] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [worker, setWorker] = useState<Worker | null>(null);
  const [loading, setLoading] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showSetup, setShowSetup] = useState(false);
  const [portfolioName, setPortfolioName] = useState("پرتفوی آزمایشی من");
  const [budget, setBudget] = useState("500");
  const [risk, setRisk] = useState("1");

  const request = useCallback(async (path: string, init: RequestInit = {}, authToken = token) => {
    const response = await fetch(`${API}${path}`, {
      ...init, cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        ...(init.headers || {}),
      },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof body.detail === "string" ? body.detail :
        typeof body.detail?.message === "string" ? body.detail.message : `خطای سرور (${response.status})`;
      throw new Error(detail);
    }
    return body;
  }, [token]);

  const loadDashboard = useCallback(async (authToken = token) => {
    if (!authToken) return;
    setLoading(true); setError("");
    try {
      const [p, s, w] = await Promise.all([
        request("/api/v1/v11/portfolios", {}, authToken),
        request("/api/v1/v11/production/status", {}, authToken).catch(() => null),
        request("/api/v1/v11/production/worker/status", {}, authToken).catch(() => null),
      ]);
      const items: Portfolio[] = p.items || [];
      setPortfolios(items);
      setPortfolioId(current => items.some(x => x.id === current) ? current : (items[0]?.id || ""));
      setStatus(s); setWorker(w);
    } catch (e) {
      const message = e instanceof Error ? e.message : "دریافت اطلاعات حساب انجام نشد";
      setError(message);
      if (message.toLowerCase().includes("session") || message.toLowerCase().includes("bearer")) {
        localStorage.removeItem(TOKEN_KEY); setToken(""); setUserEmail("");
      }
    } finally { setLoading(false); }
  }, [request, token]);

  useEffect(() => {
    const saved = localStorage.getItem(TOKEN_KEY) || "";
    setToken(saved);
    if (saved) {
      request("/api/v1/v11/auth/me", {}, saved)
        .then((u) => { setUserEmail(u.email || ""); void loadDashboard(saved); })
        .catch(() => { localStorage.removeItem(TOKEN_KEY); setToken(""); });
    }
  // Initial session restoration only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!token) return;
    const timer = window.setInterval(() => { void loadDashboard(token); }, 60000);
    return () => window.clearInterval(timer);
  }, [token, loadDashboard]);

  const selected = useMemo(() => portfolios.find(p => p.id === portfolioId) || portfolios[0], [portfolios, portfolioId]);
  const pnl = Number(selected?.realized_pnl || 0);
  const initial = Number(selected?.initial_equity || 0);
  const returnPct = initial > 0 ? pnl / initial * 100 : 0;
  const currency = selected?.base_currency || "USDT";

  async function authenticate(e: FormEvent) {
    e.preventDefault(); setAuthBusy(true); setError("");
    try {
      const path = register ? "/api/v1/v11/auth/register" : "/api/v1/v11/auth/login";
      if (register) {
        await request(path, { method: "POST", body: JSON.stringify({ email, password }) }, "");
      }
      const result = await request("/api/v1/v11/auth/login", {
        method: "POST", body: JSON.stringify({ email, password }),
      }, "");
      localStorage.setItem(TOKEN_KEY, result.access_token);
      setToken(result.access_token); setUserEmail(result.user?.email || email);
      setPassword(""); await loadDashboard(result.access_token);
      setNotice(register ? "حساب شما ساخته شد. پرتفوی پیش‌فرض آزمایشی آماده است." : "با موفقیت وارد شدید.");
    } catch (e) { setError(e instanceof Error ? e.message : "ورود انجام نشد"); }
    finally { setAuthBusy(false); }
  }

  async function logout() {
    try { await request("/api/v1/v11/auth/logout", { method: "POST" }); } catch {}
    localStorage.removeItem(TOKEN_KEY); setToken(""); setPortfolios([]); setPortfolioId(""); setUserEmail("");
  }

  async function createPortfolio(e: FormEvent) {
    e.preventDefault(); setAuthBusy(true); setError(""); setNotice("");
    const amount = Number(budget), riskPct = Number(risk);
    if (!Number.isFinite(amount) || amount < 10 || amount > 1000000) {
      setError("بودجه آزمایشی باید بین ۱۰ تا ۱٬۰۰۰٬۰۰۰ باشد."); setAuthBusy(false); return;
    }
    if (!Number.isFinite(riskPct) || riskPct < 0.1 || riskPct > 1) {
      setError("برای شروع، ریسک هر معامله را بین ۰٫۱ تا ۱ درصد انتخاب کن."); setAuthBusy(false); return;
    }
    try {
      const p = await request("/api/v1/v11/portfolios", {
        method: "POST",
        body: JSON.stringify({
          name: portfolioName, initial_equity: amount, base_currency: "USDT",
          max_open_trades: 3, max_portfolio_risk_pct: 3, max_trade_risk_pct: riskPct,
        }),
      });
      try {
        await request("/api/v1/v11/accounts", {
          method: "POST",
          body: JSON.stringify({ portfolio_id: p.id, broker: "binance", label: "TRADF Paper" }),
        });
      } catch { /* Portfolio is created; account can be added later from the workspace. */ }
      setShowSetup(false); setNotice("پرتفوی آزمایشی ساخته شد؛ هیچ پول واقعی جابه‌جا نشده است.");
      await loadDashboard();
      setPortfolioId(p.id);
    } catch (e) { setError(e instanceof Error ? e.message : "ساخت پرتفوی انجام نشد"); }
    finally { setAuthBusy(false); }
  }

  if (!token) return (
    <main className="beginner-shell">
      <header className="beginner-header"><Link href="/" className="brand"><span className="brand-mark">T</span>TRADF</Link><span className="paper-chip">محیط آزمایشی</span></header>
      <section className="auth-layout">
        <div className="auth-copy">
          <span className="eyebrow">مدیریت سرمایه، ساده و شفاف</span>
          <h1>برای شروع ترید لازم نیست متخصص باشی.</h1>
          <p>TRADF کمک می‌کند عملکرد حساب آزمایشی، ریسک و وضعیت معاملات را در یک صفحه ساده ببینی. ابتدا با پول مجازی شروع کن.</p>
          <div className="auth-points"><span><CheckCircle2/> نمایش شفاف سود و زیان</span><span><ShieldCheck/> کنترل ریسک و توقف اضطراری</span><span><BarChart3/> گزارش قابل فهم</span></div>
        </div>
        <form className="auth-card" onSubmit={authenticate}>
          <h2>{register ? "ساخت حساب کاربری" : "خوش آمدی"}</h2>
          <p>{register ? "حساب بساز و یک پرتفوی آزمایشی دریافت کن." : "برای دیدن داشبورد وارد حساب خودت شو."}</p>
          <label>ایمیل<input type="email" autoComplete="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="name@example.com"/></label>
          <label>رمز عبور<input type="password" autoComplete={register?"new-password":"current-password"} required minLength={register?10:1} value={password} onChange={e=>setPassword(e.target.value)} placeholder={register?"حداقل ۱۰ کاراکتر":"رمز عبور"}/></label>
          {error && <div className="notice error">{error}</div>}
          <button className="primary wide" disabled={authBusy}>{authBusy ? "در حال انجام..." : register ? "ساخت حساب" : "ورود به TRADF"}</button>
          <button type="button" className="text-button" onClick={()=>{setRegister(!register);setError("");}}>{register?"قبلاً حساب ساخته‌ای؟ ورود":"حساب نداری؟ ثبت‌نام کن"}</button>
          <small>حساب و موجودی این محیط آزمایشی است؛ برای شروع نیازی به واریز پول واقعی نیست.</small>
        </form>
      </section>
    </main>
  );

  return (
    <main className="beginner-shell">
      <header className="beginner-header">
        <Link href="/" className="brand"><span className="brand-mark">T</span>TRADF</Link>
        <nav className="beginner-nav">
          <a href="#overview">نمای کلی</a><a href="#account">حساب من</a><Link href="/analytics">عملکرد</Link><Link href="/forex">فارکس و طلا</Link><Link href="/advanced">ابزار حرفه‌ای</Link>
        </nav>
        <div className="header-user"><span>{userEmail}</span><button className="icon-button" onClick={logout} title="خروج"><LogOut size={17}/></button></div>
      </header>

      <section className="welcome">
        <div><span className="eyebrow">داشبورد شخصی</span><h1>سلام، خوش آمدی 👋</h1><p>وضعیت سرمایه آزمایشی‌ات را ساده و شفاف دنبال کن.</p></div>
        <div className="welcome-actions"><span className="paper-chip"><span className="pulse-dot"/> فقط حساب آزمایشی</span><button className="secondary" onClick={()=>void loadDashboard()} disabled={loading}><RefreshCw size={16}/> بروزرسانی</button></div>
      </section>

      {error && <div className="notice error">{error}</div>}
      {notice && <div className="notice success">{notice}</div>}

      <section className="overview-grid" id="overview">
        <article className="balance-card">
          <div className="balance-top"><span>ارزش فعلی حساب آزمایشی</span><Wallet size={20}/></div>
          <strong>{selected ? money(selected.cash_equity, currency) : "—"}</strong>
          <div className="balance-foot"><span>سرمایه اولیه: {selected ? money(initial, currency) : "—"}</span><span className={pnl>=0?"positive":"negative"}>{pnl>=0?<ArrowUpRight size={15}/>:<ArrowDownRight size={15}/>} {selected ? money(pnl, currency) : "—"} ({selected?`${returnPct>=0?"+":""}${returnPct.toFixed(2)}%`:"—"})</span></div>
        </article>
        <article className="stat-card"><span>سود و زیان ثبت‌شده</span><strong className={pnl>=0?"positive":"negative"}>{selected?money(pnl,currency):"—"}</strong><small>بر اساس معاملات ثبت‌شده؛ نه پیش‌بینی آینده</small></article>
        <article className="stat-card"><span>موقعیت‌های باز</span><strong>{selected?.open_positions ?? "—"}</strong><small>معاملاتی که هنوز بسته نشده‌اند</small></article>
        <article className="stat-card"><span>ریسک باز پرتفوی</span><strong>{selected?`${Number(selected.open_risk_pct||0).toFixed(2)}%`:"—"}</strong><small>{selected?money(selected.open_risk_cash,currency):"حد ضررهای ثبت‌شده"}</small></article>
      </section>

      <section className="content-two" id="account">
        <article className="surface-card">
          <div className="section-title"><div><h2>حساب‌های من</h2><p>پرتفوی آزمایشی موردنظرت را انتخاب کن.</p></div><button className="secondary" onClick={()=>setShowSetup(true)}><Plus size={16}/> ساخت پرتفوی</button></div>
          {portfolios.length ? <div className="portfolio-list">{portfolios.map(p=><button key={p.id} className={`portfolio-item ${selected?.id===p.id?"selected":""}`} onClick={()=>setPortfolioId(p.id)}><span className="portfolio-icon"><Wallet size={18}/></span><span className="portfolio-name"><b>{p.name}</b><small>سرمایه اولیه {money(p.initial_equity,p.base_currency)}</small></span><span className="portfolio-value">{money(p.cash_equity,p.base_currency)}<small>ارزش فعلی</small></span><ChevronDown size={16}/></button>)}</div> : <div className="empty-state"><Wallet size={28}/><b>هنوز پرتفویی نداری</b><p>یک حساب آزمایشی بساز تا بتوانی با داده‌های شبیه‌سازی‌شده شروع کنی.</p><button className="primary" onClick={()=>setShowSetup(true)}>ساخت پرتفوی آزمایشی</button></div>}
        </article>

        <article className="surface-card">
          <div className="section-title"><div><h2>وضعیت سیستم</h2><p>این موارد فقط وضعیت فنی سرویس را نشان می‌دهند.</p></div><ShieldCheck size={20}/></div>
          <div className="status-row"><span>محیط معاملات</span><b className="status-ok">Paper / Testnet</b></div>
          <div className="status-row"><span>معاملات واقعی</span><b className="status-off">غیرفعال</b></div>
          <div className="status-row"><span>رمزنگاری کلید صرافی</span><b>{status?.vault_ready ? <i className="status-ok">آماده</i> : <i className="status-warn">تنظیم نشده</i>}</b></div>
          <div className="status-row"><span>Worker پس‌زمینه</span><b>{worker?.worker_running ? <i className="status-ok">فعال</i> : <i className="status-warn">متصل نیست / نامشخص</i>}</b></div>
          <div className="status-row"><span>توقف اضطراری</span><b>{status?.global_kill_switch_enabled ? <i className="status-warn">فعال (ایمن)</i> : <i className="status-ok">غیرفعال</i>}</b></div>
          <p className="helper-note">تا وقتی همه کنترل‌ها بررسی نشده‌اند، سفارش آزمایشی صرافی هم فعال نمی‌شود.</p>
        </article>
      </section>

      <section className="surface-card next-steps">
        <div><span className="eyebrow">قدم بعدی</span><h2>از محیط آزمایشی شروع کن</h2><p>بدون واریز وجه، گزارش‌ها و رفتار سیستم را بررسی کن. وقتی آماده بودی، ابزارهای تخصصی در دسترس هستند.</p></div>
        <div className="next-actions"><Link className="primary" href="/analytics"><BarChart3 size={17}/> مشاهده عملکرد</Link><Link className="secondary" href="/forex"><Activity size={17}/> بازار فارکس و طلا</Link><Link className="secondary" href="/v11"><Activity size={17}/> فضای معاملاتی آزمایشی</Link><Link className="text-link" href="/advanced">ابزارهای حرفه‌ای و تحلیل بازار</Link></div>
      </section>

      <footer className="beginner-footer"><span>TRADF · مدیریت شفاف سرمایه</span><span>این محیط آزمایشی است و سود آینده را پیش‌بینی یا تضمین نمی‌کند.</span></footer>

      {showSetup && <div className="modal-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)setShowSetup(false);}}>
        <form className="setup-modal" onSubmit={createPortfolio}>
          <button type="button" className="modal-close" onClick={()=>setShowSetup(false)}>×</button>
          <span className="eyebrow">راه‌اندازی ساده</span><h2>پرتفوی آزمایشی جدید</h2><p>این مبلغ فقط موجودی مجازی برای آزمایش است؛ هیچ واریز یا برداشت واقعی انجام نمی‌شود.</p>
          <label>نام حساب<input value={portfolioName} onChange={e=>setPortfolioName(e.target.value)} maxLength={80} required/></label>
          <label>بودجه آزمایشی (USDT)<input type="number" min="10" max="1000000" step="10" value={budget} onChange={e=>setBudget(e.target.value)} required/></label>
          <label>حداکثر ریسک هر معامله<select value={risk} onChange={e=>setRisk(e.target.value)}><option value="0.25">۰٫۲۵٪ (محافظه‌کارانه)</option><option value="0.5">۰٫۵٪ (محتاطانه)</option><option value="1">۱٪ (حد بالای شروع)</option></select></label>
          <div className="helper-note">این تنظیمات محدودیت آزمایشی هستند و سودی را تضمین نمی‌کنند.</div>
          <button className="primary wide" disabled={authBusy}>{authBusy?"در حال ساخت...":"ساخت حساب آزمایشی"}</button>
        </form>
      </div>}
    </main>
  );
}
