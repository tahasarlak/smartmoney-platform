"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, RefreshCw, ShieldCheck, TrendingUp } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Portfolio = { id: string; name: string };
type AnyReport = Record<string, any>;

async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return data as T;
}

export default function ValidationCenterPage() {
  const [token, setToken] = useState("");
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [portfolioId, setPortfolioId] = useState("");
  const [lifecycle, setLifecycle] = useState<AnyReport | null>(null);
  const [release, setRelease] = useState<AnyReport | null>(null);
  const [guidance, setGuidance] = useState<AnyReport | null>(null);
  const [market, setMarket] = useState<AnyReport | null>(null);
  const [governance, setGovernance] = useState<AnyReport | null>(null);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [regime, setRegime] = useState("unknown");
  const [strategiesJson, setStrategiesJson] = useState('[{"strategy_id":"smc-core","sample_size":50,"out_of_sample_expectancy_r":0.12,"max_drawdown_pct":8,"stability_score":0.7,"crowding_score":0.2,"market_regimes":["trending"]}]');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const saved = window.localStorage.getItem("smartmoney_v11_token");
    if (saved) setToken(saved);
    else setError("ابتدا وارد حساب TRADF شو.");
  }, []);

  useEffect(() => {
    if (!token) return;
    request<{ items: Portfolio[] }>("/api/v1/v11/portfolios", token)
      .then((data) => {
        setPortfolios(data.items || []);
        if (data.items?.length) setPortfolioId((current) => current || data.items[0].id);
      })
      .catch((e: Error) => setError(e.message));
  }, [token]);

  const refresh = useCallback(async () => {
    if (!token || !portfolioId) return;
    setLoading(true);
    setError("");
    try {
      const base = `/api/v1/v11/portfolios/${portfolioId}`;
      const [life, gate, trades] = await Promise.all([
        request<AnyReport>(`${base}/lifecycle-validation`, token),
        request<AnyReport>(`${base}/release-validation`, token),
        request<{ items: AnyReport[] }>(`/api/v1/v11/execution/paper/trades?portfolio_id=${encodeURIComponent(portfolioId)}&limit=500`, token),
      ]);
      setLifecycle(life);
      setRelease(gate);
      const priceMap: Record<string, number> = {};
      (trades.items || []).forEach((trade) => {
        if (trade.last_price && Number(trade.last_price) > 0) priceMap[String(trade.id)] = Number(trade.last_price);
      });
      const advice = await request<AnyReport>(`${base}/position-guidance`, token, {
        method: "POST",
        body: JSON.stringify({ prices_by_trade_id: priceMap, near_level_pct: 0.5 }),
      });
      setGuidance(advice);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت گزارش‌ها");
    } finally {
      setLoading(false);
    }
  }, [token, portfolioId]);

  useEffect(() => {
    if (portfolioId) void refresh();
  }, [portfolioId, refresh]);

  async function loadMarket() {
    if (!token) return;
    setError("");
    setMarket(null);
    try {
      const result = await request<AnyReport>(
        `/api/v1/v11/market-intelligence/${encodeURIComponent(symbol)}?timeframes=4h,1h,15m,5m&limit=300`,
        token,
      );
      setMarket(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در تحلیل بازار");
    }
  }

  async function rankStrategies() {
    if (!token) return;
    setError("");
    setGovernance(null);
    try {
      const strategies = JSON.parse(strategiesJson);
      const result = await request<AnyReport>("/api/v1/v11/research/strategy-governance", token, {
        method: "POST",
        body: JSON.stringify({ strategies, market_regime: regime, max_recommended: 5, min_sample_size: 30 }),
      });
      setGovernance(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "JSON استراتژی‌ها معتبر نیست");
    }
  }

  return (
    <main className="p2630-page">
      <header className="p2630-header">
        <div>
          <div className="p2630-eyebrow">TRADF / VALIDATION CENTER · PHASES 26–30</div>
          <h1>مرکز اعتبارسنجی و عملیات TRADF</h1>
          <p>تطبیق معاملات آزمایشی، راهنمای مدیریت پوزیشن، هوش چندتایم‌فریمی و کنترل آمادگی انتشار.</p>
        </div>
        <button className="p2630-button" onClick={() => void refresh()} disabled={loading || !portfolioId}>
          <RefreshCw size={16} /> {loading ? "در حال بررسی..." : "به‌روزرسانی"}
        </button>
      </header>

      {error && <div className="p2630-error"><AlertTriangle size={17} />{error}</div>}

      <section className="p2630-toolbar">
        <label>پرتفوی
          <select value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)}>
            {portfolios.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <span className="p2630-paper"><ShieldCheck size={15} /> PAPER ONLY · LIVE EXECUTION DISABLED</span>
      </section>

      <section className="p2630-grid">
        <article className="p2630-card">
          <div className="p2630-card-title"><CheckCircle2 size={18} /> Phase 26 · تطبیق چرخه معاملات</div>
          <div className="p2630-number">{lifecycle?.status || "—"}</div>
          <div className="p2630-line">کل معاملات: <b>{lifecycle?.trade_count ?? "—"}</b></div>
          <div className="p2630-line">رویدادهای بررسی‌شده: <b>{lifecycle?.event_count_checked ?? "—"}</b></div>
          <div className="p2630-line">مغایرت‌ها: <b>{lifecycle?.integrity_issue_count ?? "—"}</b></div>
          <div className="p2630-line">سود خالص ثبت‌شده: <b>{lifecycle?.realized_net_pnl ?? "—"}</b></div>
        </article>

        <article className="p2630-card">
          <div className="p2630-card-title"><Activity size={18} /> Phase 27 · راهنمای پوزیشن</div>
          <div className="p2630-number">{guidance?.position_count ?? "—"}</div>
          <div className="p2630-line">پوزیشن‌های فعال بررسی‌شده</div>
          {(guidance?.items || []).slice(0, 4).map((item: AnyReport) => (
            <div className="p2630-subitem" key={item.trade_id}>
              <b>{item.symbol}</b> · {item.status}
              {(item.suggestions || []).map((s: string, i: number) => <small key={i}>{s}</small>)}
            </div>
          ))}
        </article>

        <article className="p2630-card">
          <div className="p2630-card-title"><ShieldCheck size={18} /> Phase 30 · آمادگی انتشار</div>
          <div className="p2630-number">{release?.status || "—"}</div>
          <div className="p2630-line">موفق: <b>{release?.passed_count ?? "—"}</b></div>
          <div className="p2630-line">نیازمند بررسی: <b>{release?.review_count ?? "—"}</b></div>
          <div className="p2630-line">مسدود: <b>{release?.failed_count ?? "—"}</b></div>
          <small>این گزارش فقط آمادگی محدود Paper Trading را می‌سنجد.</small>
        </article>
      </section>

      <section className="p2630-card">
        <div className="p2630-card-title"><TrendingUp size={18} /> Phase 28 · هوش چندتایم‌فریمی بازار</div>
        <div className="p2630-form">
          <label>نماد<input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></label>
          <button className="p2630-button" onClick={() => void loadMarket()}>تحلیل بازار</button>
        </div>
        {market && <>
          <div className="p2630-market-consensus">جهت توافق تایم‌فریم‌ها: <b>{market.trend_consensus}</b></div>
          <div className="p2630-regimes">
            {Object.entries(market.timeframes || {}).map(([tf, report]: [string, any]) => (
              <div key={tf}><b>{tf}</b><span>{report.regime}</span><span>{report.trend_direction}</span><span>{report.volatility_regime}</span></div>
            ))}
          </div>
        </>}
      </section>

      <section className="p2630-card">
        <div className="p2630-card-title"><ShieldCheck size={18} /> Phase 29 · حاکمیت و رتبه‌بندی استراتژی</div>
        <label>رژیم بازار
          <select value={regime} onChange={(e) => setRegime(e.target.value)}>
            <option value="unknown">نامشخص</option>
            <option value="trending">رونددار</option>
            <option value="ranging">رنج</option>
            <option value="transition">انتقالی</option>
            <option value="high_volatility">نوسان بالا</option>
          </select>
        </label>
        <label>اطلاعات استراتژی‌ها (JSON)
          <textarea className="p2630-json" value={strategiesJson} onChange={(e) => setStrategiesJson(e.target.value)} rows={5} />
        </label>
        <button className="p2630-button" onClick={() => void rankStrategies()}>رتبه‌بندی پیشنهادی</button>
        {governance && <div className="p2630-governance">
          <b>مناسب برای Paper Validation:</b>
          <span>{(governance.recommended_for_paper_validation || []).join("، ") || "هنوز استراتژی واجد شرایطی وجود ندارد."}</span>
        </div>}
        <small>رتبه‌بندی فقط توصیه‌ای است؛ هیچ استراتژی خودکار فعال و هیچ سرمایه‌ای تخصیص داده نمی‌شود.</small>
      </section>

      <footer className="p2630-footer">تمام عملیات این مرکز تحلیلی و آزمایشی هستند. هیچ سفارش واقعی به صرافی ارسال نمی‌شود.</footer>
    </main>
  );
}
