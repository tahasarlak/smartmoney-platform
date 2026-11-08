"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import TerminalPanel from "./terminal-panel";
import ExecutionManager from "./execution-manager";
import CapitalAllocator from "./capital-allocator";
import CorrelationLab from "./correlation-lab";
import CorrelationAllocator from "./correlation-allocator";
import PerformanceReport from "./performance-report";
import StatisticalValidation from "./statistical-validation";
import { Activity, ArrowDownRight, ArrowUpRight, Bot, CircleUserRound, LogOut, Plus, RefreshCw, ShieldCheck, Wallet } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Language = "en" | "fa";
const translations: Record<Language, Record<string, string>> = {
  en: {
    "paperOnly":"PAPER ONLY","paper":"PAPER","openCount":"OPEN","accountLabel":"Account label","tagline":"INTELLIGENCE & PAPER TRADING","welcome":"Welcome back",
    "createWorkspace":"Create your workspace","authSubtitle":"Multi-user accounts · isolated portfolios · simulated execution",
    "email":"Email","password":"Password","passwordHint":"At least 10 characters","signIn":"Sign in",
    "createAccount":"Create account","pleaseWait":"Please wait…","already":"Already have an account? Sign in",
    "newHere":"New here? Create an account","paperDisclaimer":"Trading is disabled. This workspace creates simulated paper positions only.",
    "workspace":"MULTI-USER WORKSPACE","portfolioControl":"Portfolio control",
    "portfolioSubtitle":"Separate user data · shared portfolio risk · paper execution only",
    "liveDisabled":"LIVE EXECUTION DISABLED","cashEquity":"Cash equity","initial":"Initial",
    "realizedPnl":"Realized P&L","closedPaper":"Closed paper positions","openPositions":"Open positions",
    "acrossAccounts":"Across connected paper accounts","aggregateRisk":"Aggregate open risk",
    "brokerAccounts":"Broker accounts","bothProviders":"Both providers use simulated execution in V11.",
    "addAccount":"Add account","noAccounts":"No paper accounts yet. Add Binance or MT5 to start.",
    "openPaperPositions":"Open paper positions","localSimulation":"Orders are simulated locally; no exchange or terminal receives them.",
    "instrument":"Instrument","side":"Side","entry":"Entry","stop":"Stop","target":"Target","risk":"Risk",
    "close":"Close","noOpen":"No open paper positions","closedPositions":"Closed positions",
    "realizedOutcomes":"Realized outcomes recorded in the tenant journal.","exit":"Exit",
    "noClosed":"No closed positions yet","newPaper":"New paper position",
    "hypothetical":"Enter a hypothetical fill price and protective levels.","broker":"Broker",
    "symbol":"Symbol","direction":"Direction","long":"Long","short":"Short","quantity":"Quantity",
    "referenceEntry":"Reference / entry price","stopLoss":"Stop loss","takeProfit":"Take profit",
    "openSimulated":"Open simulated position","riskChecked":"Risk is checked against the selected portfolio limits. The supplied price is a simulation input, not a live quote.",
    "riskGuardrails":"Risk guardrails","perTrade":"Per-trade risk cap","portfolioRisk":"Portfolio open-risk cap",
    "maxPositions":"Maximum open positions","executionState":"Execution state","disabled":"DISABLED",
    "executionAdapters":"Execution adapters","binanceData":"Public market data available · simulated orders only",
    "mt5Paper":"Paper simulator available · terminal bridge not configured",
    "footer":"SMARTMONEY V11 · TENANT-SCOPED PAPER WORKSPACE · NOT CONNECTED TO LIVE EXECUTION",
    "refresh":"Refresh","signOut":"Sign out","language":"فارسی","accountCreated":"paper account created",
    "createAccountFirst":"Create a paper broker account first","orderOpened":"Paper position opened. No broker order was sent.",
    "orderClosed":"Paper position closed","exitPrompt":"Simulated exit price for","workspaceError":"Could not load workspace",
    "authError":"Authentication failed","accountError":"Account creation failed","paperError":"Paper order failed","closeError":"Close failed"
  },
  fa: {
    "paperOnly":"فقط معاملات آزمایشی","paper":"آزمایشی","openCount":"باز","accountLabel":"عنوان حساب","tagline":"هوشمندی بازار و معاملات آزمایشی","welcome":"خوش آمدید",
    "createWorkspace":"ساخت حساب کاربری","authSubtitle":"حساب‌های چندکاربره · پرتفوی‌های مجزا · اجرای شبیه‌سازی‌شده",
    "email":"ایمیل","password":"رمز عبور","passwordHint":"حداقل ۱۰ کاراکتر","signIn":"ورود",
    "createAccount":"ایجاد حساب","pleaseWait":"لطفاً صبر کنید…","already":"قبلاً حساب ساخته‌اید؟ ورود",
    "newHere":"تازه وارد هستید؟ ایجاد حساب","paperDisclaimer":"معاملات واقعی غیرفعال است. این محیط فقط موقعیت‌های معاملاتی آزمایشی ایجاد می‌کند.",
    "workspace":"محیط چندکاربره","portfolioControl":"مدیریت پرتفوی",
    "portfolioSubtitle":"اطلاعات مجزای کاربران · مدیریت ریسک مشترک پرتفوی · اجرای آزمایشی",
    "liveDisabled":"معاملات واقعی غیرفعال است","cashEquity":"موجودی نقدی","initial":"سرمایه اولیه",
    "realizedPnl":"سود و زیان تحقق‌یافته","closedPaper":"موقعیت‌های آزمایشی بسته‌شده","openPositions":"موقعیت‌های باز",
    "acrossAccounts":"در تمام حساب‌های آزمایشی متصل","aggregateRisk":"ریسک کل موقعیت‌های باز",
    "brokerAccounts":"حساب‌های کارگزاری","bothProviders":"هر دو کارگزاری در V11 فقط به‌صورت آزمایشی اجرا می‌شوند.",
    "addAccount":"افزودن حساب","noAccounts":"هنوز حساب آزمایشی ندارید. برای شروع Binance یا MT5 را اضافه کنید.",
    "openPaperPositions":"موقعیت‌های آزمایشی باز","localSimulation":"سفارش‌ها به‌صورت محلی شبیه‌سازی می‌شوند و به صرافی یا ترمینال ارسال نمی‌شوند.",
    "instrument":"نماد","side":"جهت","entry":"ورود","stop":"حد ضرر","target":"حد سود","risk":"ریسک",
    "close":"بستن","noOpen":"موقعیت آزمایشی بازی وجود ندارد","closedPositions":"موقعیت‌های بسته‌شده",
    "realizedOutcomes":"نتایج تحقق‌یافته در دفتر ثبت اختصاصی کاربر ذخیره می‌شوند.","exit":"خروج",
    "noClosed":"هنوز موقعیت بسته‌شده‌ای وجود ندارد","newPaper":"موقعیت آزمایشی جدید",
    "hypothetical":"قیمت فرضی ورود و سطوح حد ضرر و حد سود را وارد کنید.","broker":"کارگزاری",
    "symbol":"نماد معاملاتی","direction":"جهت معامله","long":"خرید (Long)","short":"فروش (Short)","quantity":"حجم",
    "referenceEntry":"قیمت مرجع / ورود","stopLoss":"حد ضرر","takeProfit":"حد سود",
    "openSimulated":"ایجاد موقعیت آزمایشی","riskChecked":"ریسک بر اساس محدودیت‌های پرتفوی انتخاب‌شده بررسی می‌شود. قیمت واردشده فرضی است و قیمت زنده بازار نیست.",
    "riskGuardrails":"محدودیت‌های مدیریت ریسک","perTrade":"سقف ریسک هر معامله","portfolioRisk":"سقف ریسک کل پرتفوی",
    "maxPositions":"حداکثر تعداد موقعیت باز","executionState":"وضعیت اجرا","disabled":"غیرفعال",
    "executionAdapters":"اتصال‌های معاملاتی","binanceData":"داده عمومی بازار در دسترس است · فقط سفارش آزمایشی",
    "mt5Paper":"شبیه‌ساز آزمایشی فعال است · اتصال ترمینال هنوز پیکربندی نشده",
    "footer":"SMARTMONEY V11 · محیط آزمایشی اختصاصی کاربران · بدون اتصال به معاملات واقعی",
    "refresh":"به‌روزرسانی","signOut":"خروج","language":"English","accountCreated":"حساب آزمایشی ایجاد شد",
    "createAccountFirst":"ابتدا یک حساب کارگزاری آزمایشی ایجاد کنید","orderOpened":"موقعیت آزمایشی باز شد. هیچ سفارشی به کارگزاری ارسال نشد.",
    "orderClosed":"موقعیت آزمایشی بسته شد","exitPrompt":"قیمت خروج فرضی برای","workspaceError":"بارگذاری محیط کاربری ناموفق بود",
    "authError":"احراز هویت ناموفق بود","accountError":"ایجاد حساب ناموفق بود","paperError":"ایجاد سفارش آزمایشی ناموفق بود","closeError":"بستن موقعیت ناموفق بود"
  }
};

type User = { id: string; email: string };
type Portfolio = { id: string; name: string; base_currency: string; initial_equity: number; cash_equity: number; realized_pnl: number; open_positions: number; open_risk_cash: number; open_risk_pct: number; max_open_trades: number; max_trade_risk_pct: number; max_portfolio_risk_pct: number; accounts: Account[] };
type Account = { id: string; portfolio_id: string; broker: "binance" | "mt5"; mode: "paper"; label: string };
type Order = { id: string; symbol: string; side: "long" | "short"; quantity: number; entry_price: number; stop_loss: number; take_profit: number; risk_cash: number; status: "open" | "closed"; exit_price?: number; realized_pnl?: number; broker: string; created_at: string };

export default function V11Workspace() {
  const [token, setToken] = useState("");
  const [lang, setLang] = useState<Language>("en");
  const t = (key: string) => translations[lang][key] || key;
  const [user, setUser] = useState<User | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [register, setRegister] = useState(false);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [portfolioId, setPortfolioId] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [brokers, setBrokers] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [broker, setBroker] = useState<"binance" | "mt5">("binance");
  const [label, setLabel] = useState("Binance Paper");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [side, setSide] = useState<"long" | "short">("long");
  const [quantity, setQuantity] = useState("0.01");
  const [entry, setEntry] = useState("65000");
  const [stop, setStop] = useState("64000");
  const [target, setTarget] = useState("68000");

  const request = useCallback(async (path: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers || {});
    headers.set("Content-Type", "application/json");
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(`${API}${path}`, { ...init, headers, cache: "no-store" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    return body;
  }, [token]);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true); setError("");
    try {
      const [me, p, b] = await Promise.all([
        request("/api/v1/v11/auth/me"),
        request("/api/v1/v11/portfolios"),
        request("/api/v1/v11/brokers"),
      ]);
      setUser(me); setPortfolios(p.items || []); setBrokers(b.brokers || []);
      const activeId = portfolioId && (p.items || []).some((x: Portfolio) => x.id === portfolioId) ? portfolioId : p.items?.[0]?.id || "";
      setPortfolioId(activeId);
      if (activeId) {
        const [a, o] = await Promise.all([
          request(`/api/v1/v11/accounts?portfolio_id=${encodeURIComponent(activeId)}`),
          request(`/api/v1/v11/paper/orders?portfolio_id=${encodeURIComponent(activeId)}`),
        ]);
        setAccounts(a.items || []); setOrders(o.items || []);
      } else { setAccounts([]); setOrders([]); }
    } catch (e) { setError(e instanceof Error ? e.message : t("workspaceError")); }
    finally { setLoading(false); }
  }, [token, portfolioId, request]);

  useEffect(() => {
    const saved = window.localStorage.getItem("smartmoney_v11_token"); if (saved) setToken(saved);
    const savedLang = window.localStorage.getItem("smartmoney_v11_language");
    if (savedLang === "fa" || savedLang === "en") setLang(savedLang);
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
    window.localStorage.setItem("smartmoney_v11_language", lang);
  }, [lang]);
  useEffect(() => { if (token) void refresh(); }, [token, refresh]);

  async function submitAuth(e: FormEvent) {
    e.preventDefault(); setError(""); setMessage(""); setLoading(true);
    try {
      if (register) await request("/api/v1/v11/auth/register", { method: "POST", body: JSON.stringify({ email, password }) });
      const session = await request("/api/v1/v11/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      window.localStorage.setItem("smartmoney_v11_token", session.access_token); setToken(session.access_token); setPassword("");
    } catch (err) { setError(err instanceof Error ? err.message : t("authError")); }
    finally { setLoading(false); }
  }

  function signOut() { window.localStorage.removeItem("smartmoney_v11_token"); setToken(""); setUser(null); setPortfolios([]); setAccounts([]); setOrders([]); }

  async function addAccount(e: FormEvent) {
    e.preventDefault(); if (!portfolioId) return;
    setError(""); setMessage("");
    try { await request("/api/v1/v11/accounts", { method: "POST", body: JSON.stringify({ portfolio_id: portfolioId, broker, label }) }); setMessage(`${broker.toUpperCase()} ${t("accountCreated")}`); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : t("accountError")); }
  }

  async function createOrder(e: FormEvent) {
    e.preventDefault(); if (!accounts.length) { setError(t("createAccountFirst")); return; }
    const account = accounts.find(a => a.broker === broker) || accounts[0];
    setError(""); setMessage("");
    try {
      await request("/api/v1/v11/paper/orders", { method: "POST", body: JSON.stringify({ account_id: account.id, symbol, side, quantity: Number(quantity), reference_price: Number(entry), stop_loss: Number(stop), take_profit: Number(target) }) });
      setMessage(t("orderOpened")); await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : t("paperError")); }
  }

  async function closeOrder(order: Order) {
    const value = window.prompt(`${t("exitPrompt")} ${order.symbol}:`, String(entry));
    if (!value) return;
    try { await request(`/api/v1/v11/paper/orders/${order.id}/close`, { method: "POST", body: JSON.stringify({ exit_price: Number(value) }) }); setMessage(t("orderClosed")); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : t("closeError")); }
  }

  const selected = useMemo(() => portfolios.find(p => p.id === portfolioId) || null, [portfolios, portfolioId]);
  const openOrders = orders.filter(o => o.status === "open");
  const closedOrders = orders.filter(o => o.status === "closed");

  if (!token || !user) return <main className="v11-shell"><header className="v11-top"><Link href="/" className="v11-brand v11-tradf-brand"><span className="v11-mark">T</span><div><b>TRADF<span className="v11-brand-dot">.</span></b><small>SMART MONEY INTELLIGENCE</small></div></Link><nav className="v11-global-nav"><Link href="/">داشبورد</Link><Link href="/analytics">سود و زیان</Link><Link href="/strategies">رتبه‌بندی</Link><Link href="/reports">گزارش‌ها</Link><Link href="/account">حساب کاربری</Link><Link href="#capital-allocation">تخصیص سرمایه</Link><Link href="#correlation-lab">همبستگی و تنوع</Link><span className="v11-current">Paper Workspace</span></nav><div className="v11-auth-actions"><button className="v11-language" type="button" onClick={()=>setLang(lang==="en"?"fa":"en")}>{t("language")}</button><span className="v11-badge">{t("paperOnly")}</span></div></header><section className="v11-auth card"><div className="v11-icon"><CircleUserRound/></div><h1>{register ? t("createWorkspace") : t("welcome")}</h1><p className="muted">{t("authSubtitle")}</p><form onSubmit={submitAuth} className="v11-form"><label>{t("email")}<input type="email" value={email} onChange={e=>setEmail(e.target.value)} required autoComplete="email" placeholder="you@example.com"/></label><label>{t("password")}<input type="password" value={password} onChange={e=>setPassword(e.target.value)} required minLength={register ? 10 : 1} autoComplete={register ? "new-password" : "current-password"} placeholder={register ? t("passwordHint") : "Your password"}/></label><button className="btn" disabled={loading}>{loading ? t("pleaseWait") : register ? t("createAccount") : t("signIn")}</button></form>{error&&<div className="v11-error">{error}</div>}<button className="v11-link" onClick={()=>{setRegister(!register);setError("");}}>{register ? t("already") : t("newHere")}</button><p className="v11-disclaimer">{t("paperDisclaimer")}</p></section></main>;

  return <main className="v11-shell"><header className="v11-top"><Link href="/" className="v11-brand v11-tradf-brand"><span className="v11-mark">T</span><div><b>TRADF<span className="v11-brand-dot">.</span></b><small>SMART MONEY INTELLIGENCE</small></div></Link><nav className="v11-global-nav"><Link href="/">داشبورد</Link><Link href="/analytics">سود و زیان</Link><Link href="/strategies">رتبه‌بندی</Link><Link href="/reports">گزارش‌ها</Link><Link href="/account">حساب کاربری</Link><Link href="#capital-allocation">تخصیص سرمایه</Link><Link href="#correlation-lab">همبستگی و تنوع</Link><span className="v11-current">Paper Workspace</span></nav><div className="v11-user"><button className="v11-language" type="button" onClick={()=>setLang(lang==="en"?"fa":"en")}>{t("language")}</button><span>{user.email}</span><button className="v11-iconbtn" onClick={refresh} title={t("refresh")}><RefreshCw size={16}/></button><button className="v11-iconbtn" onClick={signOut} title={t("signOut")}><LogOut size={16}/></button></div></header>
    <div className="v11-title"><div><span className="v11-eyebrow">{t("workspace")}</span><h1>{t("portfolioControl")}</h1><p className="muted">{t("portfolioSubtitle")}</p></div><span className="v11-badge"><ShieldCheck size={13}/> {t("liveDisabled")}</span></div>
    <TerminalPanel token={token} portfolio={selected} accounts={accounts} onOrderCreated={refresh} />
    <ExecutionManager token={token} portfolioId={selected?.id || ""} accounts={accounts} onChanged={refresh} />
    <CapitalAllocator token={token} portfolioId={selected?.id || ""} />
    <CorrelationLab token={token} portfolioId={selected?.id || ""} />
    <CorrelationAllocator token={token} portfolioId={selected?.id || ""} />
    <PerformanceReport token={token} portfolioId={selected?.id || ""} />
    <StatisticalValidation token={token} portfolioId={selected?.id || ""} />
    {error&&<div className="v11-error">{error}</div>}{message&&<div className="v11-success">{message}</div>}
    <section className="v11-stats"><article className="card"><span>{t("cashEquity")}</span><strong>{selected ? selected.cash_equity.toLocaleString(lang==="fa"?"fa-IR":"en-US",{maximumFractionDigits:2}) : "—"} <small>USDT</small></strong><em>{t("initial")}: {selected?.initial_equity.toLocaleString(lang==="fa"?"fa-IR":"en-US") || "—"}</em></article><article className="card"><span>{t("realizedPnl")}</span><strong className={(selected?.realized_pnl||0)>=0?"positive":"negative"}>{selected?.realized_pnl?.toFixed(2) ?? "—"}</strong><em>{t("closedPaper")}</em></article><article className="card"><span>{t("openPositions")}</span><strong>{selected?.open_positions ?? 0}<small> / {selected?.max_open_trades ?? 0}</small></strong><em>{t("acrossAccounts")}</em></article><article className="card"><span>{t("aggregateRisk")}</span><strong>{selected?.open_risk_pct.toFixed(3) ?? "0.000"}<small>%</small></strong><em>{selected?.open_risk_cash.toFixed(2) ?? "0.00"} {selected?.base_currency || "USDT"}</em></article></section>
    <section className="v11-layout"><div className="v11-column"><article className="card"><div className="v11-cardhead"><div><h2><Wallet size={17}/> {t("brokerAccounts")}</h2><p className="muted">{t("bothProviders")}</p></div><select value={portfolioId} onChange={e=>setPortfolioId(e.target.value)}>{portfolios.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></div><div className="v11-brokers">{brokers.map(b=><div className="v11-broker" key={b.id}><div className="v11-broker-logo">{b.id==="binance"?"B":"MT"}</div><div><b>{b.name}</b><small>{b.status.replaceAll("_"," ")}</small></div><span className="v11-paper">{t("paper")}</span></div>)}</div><form className="v11-inlineform" onSubmit={addAccount}><select value={broker} onChange={e=>{setBroker(e.target.value as "binance"|"mt5");setLabel(e.target.value==="mt5"?"MT5 Paper":"Binance Paper");}}><option value="binance">Binance Paper</option><option value="mt5">MT5 Paper</option></select><input value={label} onChange={e=>setLabel(e.target.value)} aria-label={t("accountLabel")}/><button className="btn"><Plus size={14}/> {t("addAccount")}</button></form><div className="v11-accountlist">{accounts.map(a=><div key={a.id}><span>{a.label}</span><small>{a.broker.toUpperCase()} · PAPER</small></div>)}{!accounts.length&&<p className="muted">{t("noAccounts")}</p>}</div></article>
      <article className="card"><div className="v11-cardhead"><div><h2><Bot size={17}/> {t("openPaperPositions")}</h2><p className="muted">{t("localSimulation")}</p></div><span className="v11-count">{openOrders.length} {t("openCount")}</span></div>{openOrders.length ? <div className="v11-tablewrap"><table className="v11-table"><thead><tr><th>{t("instrument")}</th><th>{t("side")}</th><th>{t("entry")}</th><th>{t("stop")}</th><th>{t("target")}</th><th>{t("risk")}</th><th/></tr></thead><tbody>{openOrders.map(o=><tr key={o.id}><td><b>{o.symbol}</b><small>{o.broker.toUpperCase()}</small></td><td className={o.side==="long"?"positive":"negative"}>{o.side.toUpperCase()}</td><td>{o.entry_price}</td><td>{o.stop_loss}</td><td>{o.take_profit}</td><td>{o.risk_cash.toFixed(2)}</td><td><button className="v11-close" onClick={()=>closeOrder(o)}>{t("close")}</button></td></tr>)}</tbody></table></div>:<div className="v11-empty"><Activity size={22}/><span>{t("noOpen")}</span></div>}</article>
      <article className="card"><div className="v11-cardhead"><div><h2>{t("closedPositions")}</h2><p className="muted">{t("realizedOutcomes")}</p></div></div>{closedOrders.length?<div className="v11-tablewrap"><table className="v11-table"><thead><tr><th>{t("instrument")}</th><th>{t("side")}</th><th>{t("entry")}</th><th>{t("exit")}</th><th>{t("realizedPnl")}</th></tr></thead><tbody>{closedOrders.map(o=><tr key={o.id}><td>{o.symbol}</td><td>{o.side.toUpperCase()}</td><td>{o.entry_price}</td><td>{o.exit_price}</td><td className={(o.realized_pnl||0)>=0?"positive":"negative"}>{o.realized_pnl?.toFixed(2)}</td></tr>)}</tbody></table></div>:<div className="v11-empty">{t("noClosed")}</div>}</article></div>
      <aside className="v11-column"><article className="card"><div className="v11-cardhead"><div><h2><Plus size={17}/> {t("newPaper")}</h2><p className="muted">{t("hypothetical")}</p></div></div><form className="v11-form" onSubmit={createOrder}><label>{t("broker")}<select value={broker} onChange={e=>setBroker(e.target.value as "binance"|"mt5")}><option value="binance">Binance Paper</option><option value="mt5">MT5 Paper</option></select></label><label>{t("symbol")}<input value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())} required/></label><label>{t("direction")}<select value={side} onChange={e=>setSide(e.target.value as "long"|"short")}><option value="long">{t("long")}</option><option value="short">{t("short")}</option></select></label><label>{t("quantity")}<input type="number" min="0.00000001" step="any" value={quantity} onChange={e=>setQuantity(e.target.value)} required/></label><label>{t("referenceEntry")}<input type="number" min="0.00000001" step="any" value={entry} onChange={e=>setEntry(e.target.value)} required/></label><div className="v11-two"><label>{t("stopLoss")}<input type="number" min="0.00000001" step="any" value={stop} onChange={e=>setStop(e.target.value)} required/></label><label>{t("takeProfit")}<input type="number" min="0.00000001" step="any" value={target} onChange={e=>setTarget(e.target.value)} required/></label></div><button className="btn" disabled={!accounts.some(a=>a.broker===broker)}>{t("openSimulated")}</button></form><p className="v11-disclaimer">{t("riskChecked")}</p></article><article className="card"><h2>{t("riskGuardrails")}</h2><div className="v11-guard"><span>{t("perTrade")}</span><b>{selected?.max_trade_risk_pct ?? 1}%</b></div><div className="v11-guard"><span>{t("portfolioRisk")}</span><b>{selected?.max_portfolio_risk_pct ?? 3}%</b></div><div className="v11-guard"><span>{t("maxPositions")}</span><b>{selected?.max_open_trades ?? 3}</b></div><div className="v11-guard"><span>{t("executionState")}</span><b className="positive">{t("disabled")}</b></div></article><article className="card"><h2>{t("executionAdapters")}</h2><div className="v11-adapter"><ArrowUpRight size={15}/><div><b>Binance</b><small>{t("binanceData")}</small></div></div><div className="v11-adapter"><ArrowDownRight size={15}/><div><b>MetaTrader 5</b><small>{t("mt5Paper")}</small></div></div></article></aside></section>
    <footer className="v11-footer">{t("footer")}</footer>
  </main>;
}
