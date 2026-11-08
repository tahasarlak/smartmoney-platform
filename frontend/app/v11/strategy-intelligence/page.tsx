"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BrainCircuit, RefreshCw, ShieldCheck, AlertTriangle } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Strategy = {
  name: string; trade_count: number; win_rate_pct: number; profit_factor: number;
  max_drawdown_pct: number; expectancy_r: number; suitable_regimes: string[];
};
type Result = {
  status: string; market_regime: string; candidate_count: number; eligible_candidate_count: number;
  ranked_strategies: Array<Strategy & { score: number; eligible_for_consideration: boolean; regime_compatible: boolean; issues: string[] }>;
  limitations: string[]; execution_allowed: false;
};

const starter: Strategy[] = [
  { name: "SMC Trend", trade_count: 120, win_rate_pct: 54, profit_factor: 1.55, max_drawdown_pct: 7, expectancy_r: .28, suitable_regimes: ["trending"] },
  { name: "Range Reversal", trade_count: 95, win_rate_pct: 58, profit_factor: 1.42, max_drawdown_pct: 9, expectancy_r: .22, suitable_regimes: ["ranging"] },
];

export default function StrategyIntelligencePage() {
  const [token, setToken] = useState("");
  const [regime, setRegime] = useState("trending");
  const [strategies, setStrategies] = useState<Strategy[]>(starter);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => setToken(window.localStorage.getItem("smartmoney_v11_token") || ""), []);

  function update(index: number, field: keyof Strategy, value: string) {
    setStrategies(old => old.map((s, i) => {
      if (i !== index) return s;
      if (field === "suitable_regimes") return { ...s, suitable_regimes: value.split(",").map(x => x.trim()).filter(Boolean) };
      if (field === "name") return { ...s, name: value };
      return { ...s, [field]: Number(value) };
    }));
  }

  async function evaluate() {
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await fetch(`${API}/api/v1/v11/strategy-intelligence/evaluate`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ market_regime: regime, strategies, minimum_trades: 30, max_drawdown_pct: 15 }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
      setResult(body as Result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "ارزیابی انجام نشد");
    } finally { setBusy(false); }
  }

  return <main className="p32-shell">
    <header><Link href="/v11">TRADF / V11</Link><span> / Strategy Intelligence</span></header>
    <section className="p32-hero">
      <span><BrainCircuit size={16}/> PHASE 32 · EXPLAINABLE INTELLIGENCE</span>
      <h1>هوش ارزیابی استراتژی</h1>
      <p>استراتژی‌ها را با توجه به رژیم بازار و شواهد عملکردی مقایسه کن. این ابزار فقط تحلیل می‌کند و هیچ تغییری در معاملات یا سرمایه ایجاد نمی‌کند.</p>
      <label>وضعیت بازار
        <select value={regime} onChange={e => setRegime(e.target.value)}>
          <option value="trending">رونددار</option><option value="ranging">رنج</option>
          <option value="transition">گذار</option><option value="high_volatility">نوسان بالا</option><option value="unknown">نامشخص</option>
        </select>
      </label>
    </section>
    <section className="p32-list">
      {strategies.map((s, i) => <article key={i}>
        <h2>استراتژی {i + 1}</h2>
        <label>نام<input value={s.name} onChange={e => update(i, "name", e.target.value)}/></label>
        <div className="p32-fields">
          <label>تعداد معاملات<input type="number" value={s.trade_count} onChange={e => update(i, "trade_count", e.target.value)}/></label>
          <label>Win rate %<input type="number" step=".1" value={s.win_rate_pct} onChange={e => update(i, "win_rate_pct", e.target.value)}/></label>
          <label>Profit factor<input type="number" step=".01" value={s.profit_factor} onChange={e => update(i, "profit_factor", e.target.value)}/></label>
          <label>Max drawdown %<input type="number" step=".1" value={s.max_drawdown_pct} onChange={e => update(i, "max_drawdown_pct", e.target.value)}/></label>
          <label>Expectancy (R)<input type="number" step=".01" value={s.expectancy_r} onChange={e => update(i, "expectancy_r", e.target.value)}/></label>
          <label>رژیم‌های مناسب<input value={s.suitable_regimes.join(",")} onChange={e => update(i, "suitable_regimes", e.target.value)} placeholder="trending,ranging"/></label>
        </div>
        <button className="p32-remove" onClick={() => setStrategies(old => old.filter((_, j) => i !== j))}>حذف استراتژی</button>
      </article>)}
    </section>
    <div className="p32-actions">
      <button onClick={() => setStrategies(old => [...old, { name: `Strategy ${old.length + 1}`, trade_count: 0, win_rate_pct: 0, profit_factor: 0, max_drawdown_pct: 0, expectancy_r: 0, suitable_regimes: [] }])}>افزودن استراتژی</button>
      <button className="p32-primary" onClick={evaluate} disabled={busy || !token || strategies.length === 0}><RefreshCw size={16}/>{busy ? "در حال ارزیابی…" : "ارزیابی و رتبه‌بندی"}</button>
    </div>
    {!token && <p className="p32-warning">برای استفاده از API ابتدا وارد TRADF شوید.</p>}
    {error && <p className="p32-warning"><AlertTriangle size={16}/>{error}</p>}
    {result && <section className="p32-results">
      <div className="p32-result-head"><div><h2>نتیجه ارزیابی</h2><p>{result.eligible_candidate_count} گزینه واجد شرایط بررسی از {result.candidate_count} استراتژی</p></div><span><ShieldCheck size={15}/> بدون اجرای معامله</span></div>
      {result.ranked_strategies.map((s, i) => <article key={s.name + i}>
        <div><b>#{i + 1} · {s.name}</b><span className={s.eligible_for_consideration ? "p32-eligible" : "p32-ineligible"}>{s.eligible_for_consideration ? "واجد شرایط بررسی" : "نیازمند بررسی"}</span></div>
        <strong>{s.score.toFixed(1)}<small>/100</small></strong>
        <p>PF {s.profit_factor} · DD {s.max_drawdown_pct}% · Expectancy {s.expectancy_r}R · {s.trade_count} معامله</p>
        {s.issues.length > 0 && <small>{s.issues.join(" · ")}</small>}
      </article>)}
      <ul>{result.limitations.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </section>}
    <footer>TRADF · PHASE 32 · HEURISTIC STRATEGY EVALUATION · NO AUTO-SELECTION · NO LIVE ORDERS</footer>
  </main>;
}
