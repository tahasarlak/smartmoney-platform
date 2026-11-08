"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Clock3, RefreshCw, ShieldCheck, XCircle } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

type Account = { id: string; broker: "binance" | "mt5"; label: string; mode?: "paper" };
type Trade = {
  id: string; portfolio_id: string; account_id: string; broker: string; symbol: string;
  side: "long" | "short"; status: "pending_entry" | "open" | "partially_closed" | "closed" | "cancelled";
  planned_entry: number; avg_entry_price: number | null; stop_loss: number; initial_stop_loss: number;
  tp1: number; tp2: number; tp3: number; quantity: number; remaining_quantity: number;
  tp1_fraction: number; tp2_fraction: number; tp3_fraction: number;
  tp1_hit: boolean; tp2_hit: boolean; tp3_hit: boolean;
  move_stop_to_breakeven_after_tp1: boolean; trailing_stop_pct: number | null;
  realized_pnl: number; fees_paid: number; net_realized_pnl: number;
  last_price: number | null; last_event_time_ms: number; entry_filled_at_ms: number | null;
  closed_at_ms: number | null; created_at: string; updated_at: string;
  idempotent_replay?: boolean;
};
type Event = {
  id: number; event_type: string; market_price: number; fill_price: number | null;
  quantity: number; pnl: number; fee: number; event_time: string; details: Record<string, unknown>;
};

const number = (n: number | null | undefined, digits = 5) =>
  n == null || !Number.isFinite(Number(n))
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(Number(n));
const money = (n: number | null | undefined) =>
  n == null || !Number.isFinite(Number(n))
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 2, signDisplay: "exceptZero" }).format(Number(n));
const active = (s: Trade["status"]) => ["pending_entry", "open", "partially_closed"].includes(s);

export default function ExecutionManager({
  token, portfolioId, accounts, onChanged,
}: {
  token: string;
  portfolioId: string;
  accounts: Account[];
  onChanged: () => Promise<void> | void;
}) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [selectedTrade, setSelectedTrade] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [accountId, setAccountId] = useState("");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [side, setSide] = useState<"long" | "short">("long");
  const [quantity, setQuantity] = useState("");
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [tp1, setTp1] = useState("");
  const [tp2, setTp2] = useState("");
  const [tp3, setTp3] = useState("");
  const [trailing, setTrailing] = useState("1");
  const [useTrailing, setUseTrailing] = useState(false);
  const [breakeven, setBreakeven] = useState(true);
  const marketAccounts = useMemo(() => accounts.filter(a => a.broker === "binance"), [accounts]);

  const request = useCallback(async (path: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers || {});
    headers.set("Content-Type", "application/json");
    headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(`${API}${path}`, { ...init, headers, cache: "no-store" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `API ${response.status}`);
    return body;
  }, [token]);

  const load = useCallback(async (quiet = false) => {
    if (!token || !portfolioId) return;
    if (!quiet) setLoading(true);
    try {
      const body = await request(`/api/v1/v11/execution/paper/trades?portfolio_id=${encodeURIComponent(portfolioId)}&limit=200`);
      const items: Trade[] = Array.isArray(body.items) ? body.items : [];
      setTrades(items);
      setSelectedTrade(current => current && items.some(x => x.id === current) ? current : "");
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "دریافت معاملات ناموفق بود.");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [token, portfolioId, request]);

  useEffect(() => {
    setTrades([]);
    setEvents([]);
    setSelectedTrade("");
    if (marketAccounts.length) setAccountId(current => marketAccounts.some(a => a.id === current) ? current : marketAccounts[0].id);
    else setAccountId("");
    void load();
  }, [portfolioId, token, load, marketAccounts]);

  useEffect(() => {
    if (!token || !portfolioId) return;
    const timer = window.setInterval(() => { void load(true); }, 10000);
    return () => window.clearInterval(timer);
  }, [token, portfolioId, load]);

  useEffect(() => {
    if (!selectedTrade || !token) { setEvents([]); return; }
    let cancelled = false;
    request(`/api/v1/v11/execution/paper/trades/${selectedTrade}/events?limit=100`)
      .then(body => { if (!cancelled) setEvents(Array.isArray(body.items) ? body.items : []); })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : "دریافت رویدادها ناموفق بود."); });
    return () => { cancelled = true; };
  }, [selectedTrade, token, request, trades]);

  const activeTrades = useMemo(() => trades.filter(t => active(t.status)), [trades]);
  const closedTrades = useMemo(() => trades.filter(t => !active(t.status)), [trades]);
  const chosen = trades.find(t => t.id === selectedTrade) || null;

  async function createTrade(e: FormEvent) {
    e.preventDefault();
    if (!portfolioId || !accountId) { setError("ابتدا پرتفوی و حساب Paper را انتخاب کن."); return; }
    const payload = {
      portfolio_id: portfolioId, account_id: accountId,
      idempotency_key: `ui-${crypto.randomUUID()}`,
      symbol: symbol.trim().toUpperCase(), side, quantity: Number(quantity),
      planned_entry: Number(entry), stop_loss: Number(stop),
      tp1: Number(tp1), tp2: Number(tp2), tp3: Number(tp3),
      tp1_fraction: 0.5, tp2_fraction: 0.3, tp3_fraction: 0.2,
      move_stop_to_breakeven_after_tp1: breakeven,
      trailing_stop_pct: useTrailing ? Number(trailing) : null,
    };
    if (Object.values(payload).some(v => typeof v === "number" && (!Number.isFinite(v) || v <= 0))) {
      setError("همه قیمت‌ها و حجم باید عدد مثبت و معتبر باشند."); return;
    }
    setSaving(true); setError(""); setNotice("");
    try {
      const created = await request("/api/v1/v11/execution/paper/trades", {
        method: "POST", body: JSON.stringify(payload),
      });
      setNotice(created.idempotent_replay ? "درخواست قبلی بازیابی شد." : "معامله پیشرفته Paper ثبت شد؛ سفارش واقعی ارسال نشده است.");
      setShowCreate(false);
      setSelectedTrade(created.id);
      await load(true);
      await onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "ثبت معامله ناموفق بود.");
    } finally { setSaving(false); }
  }

  async function closeTrade(trade: Trade) {
    if (trade.status === "pending_entry") return;
    const defaultPrice = trade.last_price ?? trade.avg_entry_price ?? trade.planned_entry;
    const raw = window.prompt(`قیمت خروج شبیه‌سازی‌شده برای ${trade.symbol} را وارد کن:`, String(defaultPrice));
    if (raw === null) return;
    const price = Number(raw);
    if (!Number.isFinite(price) || price <= 0) { setError("قیمت خروج باید عدد مثبت باشد."); return; }
    if (!window.confirm(`بستن کامل معامله آزمایشی ${trade.symbol} در قیمت ${price}؟ هیچ سفارش واقعی ارسال نمی‌شود.`)) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const eventTime = Math.max(Date.now(), Number(trade.last_event_time_ms || 0) + 1);
      await request(`/api/v1/v11/execution/paper/trades/${trade.id}/close`, {
        method: "POST",
        body: JSON.stringify({ event_id: `ui-close-${crypto.randomUUID()}`, market_price: price, event_time_ms: eventTime }),
      });
      setNotice("معامله آزمایشی بسته شد و رویداد آن در ژورنال ثبت شد.");
      await load(true); await onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "بستن معامله ناموفق بود."); }
    finally { setSaving(false); }
  }

  async function cancelTrade(trade: Trade) {
    if (trade.status !== "pending_entry") return;
    if (!window.confirm(`سفارش ورودی معلق ${trade.symbol} لغو شود؟`)) return;
    setSaving(true); setError(""); setNotice("");
    try {
      await request(`/api/v1/v11/execution/paper/trades/${trade.id}/cancel`, {
        method: "POST", body: JSON.stringify({ event_id: `ui-cancel-${crypto.randomUUID()}` }),
      });
      setNotice("ورودی معلق لغو شد.");
      await load(true); await onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "لغو سفارش ناموفق بود."); }
    finally { setSaving(false); }
  }

  if (!token || !portfolioId) return null;

  return (
    <section className="xpm-wrap card">
      <div className="xpm-head">
        <div>
          <span className="v11-eyebrow">TRADF · EXECUTION MANAGEMENT</span>
          <h2><Activity size={18}/> مدیریت پیشرفته معاملات آزمایشی</h2>
          <p className="muted">خروج پله‌ای، انتقال حد ضرر به نقطه ورود و Trailing Stop توسط موتور اجرای موجود مدیریت می‌شود.</p>
        </div>
        <div className="xpm-head-actions">
          <span className="v11-badge"><ShieldCheck size={13}/> PAPER ONLY</span>
          <button className="v11-iconbtn" type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={15}/></button>
          <button className="btn" type="button" onClick={() => setShowCreate(v => !v)}>{showCreate ? "بستن فرم" : "معامله پیشرفته جدید"}</button>
        </div>
      </div>

      {error && <div className="v11-error"><AlertTriangle size={15}/> {error}</div>}
      {notice && <div className="v11-success"><CheckCircle2 size={15}/> {notice}</div>}

      {showCreate && <form className="xpm-create" onSubmit={createTrade}>
        <div className="xpm-section-title">تعریف معامله با سه هدف سود</div>
        <div className="xpm-form-grid">
          <label>حساب Paper<select value={accountId} onChange={e => setAccountId(e.target.value)} required>
            <option value="">انتخاب حساب Binance Paper</option>{marketAccounts.map(a => <option key={a.id} value={a.id}>{a.label} · BINANCE PAPER</option>)}
          </select></label>
          <label>نماد<input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} required maxLength={40}/></label>
          <label>جهت<select value={side} onChange={e => setSide(e.target.value as "long" | "short")}><option value="long">LONG</option><option value="short">SHORT</option></select></label>
          <label>حجم<input type="number" min="0.00000001" step="any" value={quantity} onChange={e => setQuantity(e.target.value)} required/></label>
          <label>قیمت ورود برنامه‌ریزی‌شده<input type="number" min="0.00000001" step="any" value={entry} onChange={e => setEntry(e.target.value)} required/></label>
          <label>حد ضرر اولیه<input type="number" min="0.00000001" step="any" value={stop} onChange={e => setStop(e.target.value)} required/></label>
          <label>هدف سود ۱<input type="number" min="0.00000001" step="any" value={tp1} onChange={e => setTp1(e.target.value)} required/></label>
          <label>هدف سود ۲<input type="number" min="0.00000001" step="any" value={tp2} onChange={e => setTp2(e.target.value)} required/></label>
          <label>هدف سود ۳<input type="number" min="0.00000001" step="any" value={tp3} onChange={e => setTp3(e.target.value)} required/></label>
          <label>Trailing Stop (%)<span className="xpm-checkline"><input type="checkbox" checked={useTrailing} onChange={e => setUseTrailing(e.target.checked)}/> فعال‌سازی</span>
            <input type="number" min="0.01" max="20" step="0.01" value={trailing} onChange={e => setTrailing(e.target.value)} disabled={!useTrailing}/></label>
        </div>
        <label className="xpm-checkline xpm-breakeven"><input type="checkbox" checked={breakeven} onChange={e => setBreakeven(e.target.checked)}/> بعد از تحقق TP1، حد ضرر به نقطه ورود منتقل شود.</label>
        <div className="xpm-plan-note">تقسیم پیش‌فرض حجم: TP1 = ۵۰٪، TP2 = ۳۰٪، TP3 = ۲۰٪. اعتبارسنجی ترتیب قیمت‌ها و محدودیت ریسک در Backend انجام می‌شود. مدیریت خودکار حد ضرر و اهداف فعلاً فقط با حساب Binance Paper و فید بازار متصل کار می‌کند.</div>
        {!marketAccounts.length && <div className="v11-error">برای مدیریت خودکار قیمت، ابتدا یک حساب Binance Paper بساز. اتصال MT5 هنوز فعال نیست.</div>}
        <div className="xpm-form-actions"><button className="btn" disabled={saving || !marketAccounts.length}>{saving ? "در حال ثبت…" : "ثبت معامله آزمایشی"}</button><span className="muted">هیچ سفارش واقعی به صرافی یا MT5 ارسال نمی‌شود.</span></div>
      </form>}

      <div className="xpm-section-title">موقعیت‌های فعال <span>{activeTrades.length}</span></div>
      {loading && <p className="muted">در حال دریافت معاملات…</p>}
      {activeTrades.length ? <div className="xpm-trade-grid">{activeTrades.map(t => {
        const entryPrice = t.avg_entry_price ?? t.planned_entry;
        const floating = t.last_price != null && t.avg_entry_price != null
          ? (t.side === "long" ? t.last_price - t.avg_entry_price : t.avg_entry_price - t.last_price) * t.remaining_quantity
          : null;
        return <article className={`xpm-trade ${selectedTrade === t.id ? "selected" : ""}`} key={t.id}>
          <div className="xpm-trade-top"><div><b>{t.symbol}</b><span className={t.side === "long" ? "positive" : "negative"}>{t.side.toUpperCase()}</span></div><span className={`xpm-status ${t.status}`}>{statusLabel(t.status)}</span></div>
          <div className="xpm-trade-metrics">
            <div><small>ورود واقعی / برنامه‌ای</small><b>{number(entryPrice)}</b></div>
            <div><small>قیمت آخر بازار</small><b>{number(t.last_price)}</b></div>
            <div><small>حجم باقی‌مانده</small><b>{number(t.remaining_quantity, 8)}</b></div>
            <div><small>حد ضرر جاری</small><b className="negative">{number(t.stop_loss)}</b></div>
            <div><small>سود تحقق‌یافته خالص</small><b className={t.net_realized_pnl >= 0 ? "positive" : "negative"}>{money(t.net_realized_pnl)}</b></div>
            <div><small>سود/زیان شناور تخمینی</small><b className={floating == null ? "" : floating >= 0 ? "positive" : "negative"}>{floating == null ? "—" : money(floating)}</b></div>
          </div>
          <div className="xpm-targets">
            {[1,2,3].map(n => {
              const hit = n === 1 ? t.tp1_hit : n === 2 ? t.tp2_hit : t.tp3_hit;
              const target = n === 1 ? t.tp1 : n === 2 ? t.tp2 : t.tp3;
              return <span className={hit ? "hit" : ""} key={n}><i>{hit ? "✓" : `TP${n}`}</i>{number(target)}</span>;
            })}
          </div>
          {t.trailing_stop_pct != null && <div className="xpm-trail"><Activity size={13}/> Trailing Stop فعال · {t.trailing_stop_pct}%</div>}
          <div className="xpm-card-actions">
            <button type="button" className="xpm-secondary" onClick={() => setSelectedTrade(v => v === t.id ? "" : t.id)}>{selectedTrade === t.id ? "بستن جزئیات" : "رویدادها و جزئیات"}</button>
            {t.status === "pending_entry"
              ? <button type="button" className="xpm-danger" disabled={saving} onClick={() => void cancelTrade(t)}>لغو ورودی</button>
              : <button type="button" className="xpm-danger" disabled={saving} onClick={() => void closeTrade(t)}>بستن کامل</button>}
          </div>
        </article>;
      })}</div> : <div className="v11-empty"><Activity size={22}/><span>موقعیت پیشرفته فعالی وجود ندارد.</span></div>}

      {chosen && <section className="xpm-events">
        <div className="xpm-section-title">ژورنال رویدادها · {chosen.symbol}</div>
        <div className="xpm-event-list">{events.length ? events.slice().reverse().map(ev => <div className="xpm-event" key={ev.id}>
          <span className="xpm-event-icon"><Clock3 size={14}/></span>
          <div><b>{eventLabel(ev.event_type)}</b><small>{new Date(ev.event_time).toLocaleString()}</small></div>
          <span>{number(ev.fill_price ?? ev.market_price)}</span>
          <b className={ev.pnl >= 0 ? "positive" : "negative"}>{money(ev.pnl - ev.fee)}</b>
        </div>) : <p className="muted">هنوز رویداد اجرایی ثبت نشده است.</p>}</div>
      </section>}

      <div className="xpm-section-title xpm-history-title">تاریخچه معاملات پیشرفته</div>
      {closedTrades.length ? <div className="xpm-history-wrap"><table className="v11-table"><thead><tr><th>نماد</th><th>جهت</th><th>وضعیت</th><th>سود ناخالص</th><th>کارمزد</th><th>سود خالص</th><th>زمان ثبت</th></tr></thead><tbody>{closedTrades.map(t => <tr key={t.id}><td><b>{t.symbol}</b></td><td>{t.side.toUpperCase()}</td><td>{statusLabel(t.status)}</td><td>{money(t.realized_pnl)}</td><td>{number(t.fees_paid, 4)}</td><td className={t.net_realized_pnl >= 0 ? "positive" : "negative"}>{money(t.net_realized_pnl)}</td><td>{new Date(t.created_at).toLocaleDateString()}</td></tr>)}</tbody></table></div> : <p className="muted">معامله بسته‌شده‌ای در این موتور ثبت نشده است.</p>}

      <p className="xpm-footnote"><ShieldCheck size={14}/> قیمت و رویدادها از موتور Paper موجود دریافت می‌شوند. سود شناور صرفاً تخمین بر اساس آخرین قیمت ثبت‌شده است؛ در نبود اتصال Market Monitor به‌روزرسانی نمی‌شود. Trailing Stop و خروج پله‌ای فقط هنگام دریافت Tick معتبر اجرا می‌شوند. معاملات قدیمی از نوع Paper Order در این جدول نمایش داده نمی‌شوند.</p>
    </section>
  );
}

function statusLabel(status: Trade["status"]) {
  return ({ pending_entry: "در انتظار ورود", open: "باز", partially_closed: "خروج پله‌ای", closed: "بسته", cancelled: "لغوشده" })[status];
}
function eventLabel(type: string) {
  const labels: Record<string, string> = {
    ENTRY_FILLED: "ورود اجرا شد", TP1_FILLED: "هدف اول محقق شد", TP2_FILLED: "هدف دوم محقق شد",
    TP3_FILLED: "هدف سوم محقق شد", STOP_FILLED: "حد ضرر فعال شد",
    MANUAL_CLOSE_FILLED: "بستن دستی", TRAILING_STOP_UPDATED: "حد ضرر شناور به‌روزرسانی شد",
    STOP_MOVED_TO_BREAKEVEN: "حد ضرر به نقطه ورود منتقل شد", ORDER_CANCELLED: "ورودی لغو شد",
  };
  return labels[type] || type.replaceAll("_", " ");
}
