"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import "./forex.css";
import { ArrowLeft, RefreshCw, Info, TrendingUp, Coins } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

type RateItem = {
  symbol: string;
  display: string;
  name: string;
  rate: number | null;
  date: string | null;
  frequency: string;
  source: string;
  status?: string;
};
type Payload = {
  provider: string;
  provider_url: string;
  attribution: string;
  data_type: string;
  frequency: string;
  intraday_available: boolean;
  ohlc_available: boolean;
  tradable: boolean;
  execution_allowed: boolean;
  available_symbols: number;
  symbol_count: number;
  items: RateItem[];
  warnings: string[];
};

const fmt = (value: number | null) => value == null
  ? "داده موجود نیست"
  : value.toLocaleString("en-US", { maximumFractionDigits: value > 100 ? 4 : 6 });

export default function ForexReferencePage() {
  const [data, setData] = useState<Payload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/v1/forex/reference`, { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `خطای سرور (${response.status})`);
      setData(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : "دریافت نرخ‌های مرجع ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <main className="forex-reference-shell" dir="rtl">
      <header className="forex-reference-header">
        <Link href="/" className="forex-back"><ArrowLeft size={17}/> بازگشت به داشبورد</Link>
        <span className="forex-free-pill">داده مرجع رایگان · بدون MetaTrader</span>
      </header>

      <section className="forex-reference-hero">
        <div>
          <span className="forex-eyebrow"><TrendingUp size={15}/> MARKET REFERENCE</span>
          <h1>بازار ارز و طلا</h1>
          <p>نمایش نرخ‌های مرجع روزانه برای ۷ جفت‌ارز اصلی و طلا، بدون نیاز به نصب نرم‌افزار یا اتصال بروکر.</p>
        </div>
        <button className="forex-refresh" onClick={() => void load()} disabled={busy}>
          <RefreshCw size={16} className={busy ? "forex-spin" : ""}/>
          بروزرسانی
        </button>
      </section>

      <div className="forex-reference-warning">
        <Info size={19}/>
        <div>
          <b>این صفحه نرخ مرجع روزانه را نشان می‌دهد، نه قیمت لحظه‌ای قابل معامله.</b>
          <p>منبع رایگان Frankfurter نرخ‌های میانگین مرجع را معمولاً روزانه منتشر می‌کند. این داده‌ها کندل OHLC، قیمت Bid/Ask یا اسپرد بروکر نیستند و برای ورود ۵ دقیقه‌ای، بک‌تست درون‌روزی یا اجرای سفارش مناسب نیستند.</p>
        </div>
      </div>

      {error && <div className="forex-reference-error">{error}</div>}
      {!data && busy && <div className="forex-reference-loading">در حال دریافت نرخ‌های مرجع...</div>}

      {data && <>
        <section className="forex-reference-summary">
          <div><span>منبع داده</span><b>Frankfurter</b></div>
          <div><span>تناوب انتشار</span><b>روزانه</b></div>
          <div><span>نمادهای دریافت‌شده</span><b>{data.available_symbols} از {data.symbol_count}</b></div>
          <div><span>معامله واقعی</span><b className="forex-disabled">غیرفعال</b></div>
        </section>

        <section className="forex-reference-grid">
          {data.items.map((item) => (
            <article className="forex-rate-card" key={item.symbol}>
              <div className="forex-rate-card-top">
                <span className="forex-rate-symbol">{item.symbol === "XAUUSD" ? <Coins size={17}/> : null}{item.symbol}</span>
                <span className={item.rate == null ? "forex-state-missing" : "forex-state-reference"}>{item.rate == null ? "ناموجود" : "نرخ مرجع"}</span>
              </div>
              <p>{item.name}</p>
              <strong>{fmt(item.rate)}</strong>
              <small>تاریخ داده: {item.date || "—"}</small>
            </article>
          ))}
        </section>

        <section className="forex-reference-limitations">
          <h2>چه کارهایی با این داده ممکن است؟</h2>
          <div className="forex-limits-grid">
            <div><b>مجاز و قابل استفاده</b><span>نمایش نرخ مرجع، مقایسه روزانه و تحلیل تغییرات بلندمدت.</span></div>
            <div><b>در این پلن موجود نیست</b><span>کندل 1m/5m/15m، اسپرد بروکر، Bid/Ask و قیمت لحظه‌ای.</span></div>
            <div><b>معاملات</b><span>هیچ سفارش واقعی یا Paper مبتنی بر کندل ساختگی از این API ایجاد نمی‌شود.</span></div>
          </div>
        </section>

        <footer className="forex-reference-attribution">
          منبع: <a href={data.provider_url} target="_blank" rel="noreferrer">Frankfurter</a> · نرخ‌های مرجع روزانه و رایگان. زمان هر مشاهده در کارت همان نماد درج شده است.
        </footer>
      </>}
    </main>
  );
}
