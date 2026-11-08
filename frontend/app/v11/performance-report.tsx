"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, BarChart3, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
type Point = {time_ms:number|null;equity:number;drawdown_cash:number;drawdown_pct:number};
type Cohort = {group:string;symbol:string;side:string;closed_trades:number;net_pnl:number;win_rate_pct:number;profit_factor:number|null;expectancy_cash:number;average_r:number|null};
type Report = {
  trades_returned:number;
  status:string;mode:string;portfolio_name:string;initial_equity:number;cash_equity_to_date:number;
  realized_net_pnl_to_date:number;closed_trade_count:number;win_rate_pct:number|null;profit_factor:number|null;
  expectancy_cash:number|null;average_win_cash:number|null;average_loss_cash:number|null;
  max_drawdown_cash:number;max_drawdown_pct:number;sharpe_per_trade:number|null;sortino_per_trade:number|null;
  return_observations:number;equity_curve:Point[];cohort_ranking:Cohort[];sample_quality:string;
  truncated:boolean;limitations:string[];execution_allowed:false;
};
const money=(v:number|null|undefined)=>v==null?"—":new Intl.NumberFormat("en-US",{maximumFractionDigits:2}).format(v);
const pct=(v:number|null|undefined)=>v==null?"—":`${v.toFixed(2)}٪`;
const ratio=(v:number|null|undefined)=>v==null?"—":v.toFixed(3);

export default function PerformanceReport({token,portfolioId}:{token:string;portfolioId:string}) {
  const [report,setReport]=useState<Report|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [updated,setUpdated]=useState("");

  const load=useCallback(async()=>{
    if(!token||!portfolioId){setReport(null);return;}
    setLoading(true);setError("");
    try{
      const response=await fetch(`${API}/api/v1/v11/portfolios/${encodeURIComponent(portfolioId)}/performance?limit=500`,{
        headers:{Authorization:`Bearer ${token}`},cache:"no-store"
      });
      const body=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(body.detail||`API ${response.status}`);
      setReport(body);setUpdated(new Date().toLocaleString());
    }catch(e){setError(e instanceof Error?e.message:"گزارش عملکرد دریافت نشد.");}
    finally{setLoading(false);}
  },[token,portfolioId]);

  useEffect(()=>{void load();},[load]);

  const chart=useMemo(()=>{
    if(!report||report.equity_curve.length<2)return null;
    const values=report.equity_curve.map(p=>p.equity);
    const min=Math.min(...values),max=Math.max(...values);
    const range=Math.max(max-min,Math.abs(max)*0.0001,1);
    const width=900,height=190,pad=12;
    const points=values.map((v,i)=>{
      const x=pad+(i/(values.length-1))*(width-pad*2);
      const y=height-pad-((v-min)/range)*(height-pad*2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return {points,min,max,width,height};
  },[report]);

  return <section id="performance-report" className="p10-performance card">
    <div className="p10-head">
      <div><span className="v11-eyebrow">PHASE 10 · PERFORMANCE INTELLIGENCE</span>
        <h2><BarChart3 size={19}/> گزارش عملکرد واقعی پرتفوی</h2>
        <p className="muted">محاسبات از معاملات اجرای آزمایشی ذخیره‌شده و سود خالص پس از کارمزد استخراج می‌شوند؛ داده ساختگی یا پیش‌بینی سود نمایش داده نمی‌شود.</p>
      </div>
      <button type="button" className="v11-iconbtn" onClick={()=>void load()} disabled={loading} title="به‌روزرسانی"><RefreshCw size={16}/></button>
    </div>
    {!portfolioId&&<div className="v11-error">ابتدا یک پرتفوی انتخاب کنید.</div>}
    {error&&<div className="v11-error">{error}</div>}
    {loading&&!report&&<div className="v11-empty">در حال دریافت گزارش عملکرد…</div>}
    {report&&<>
      <div className="p10-kpis">
        <div><small>سود و زیان خالص تحقق‌یافته</small><b className={report.realized_net_pnl_to_date>=0?"positive":"negative"}>{money(report.realized_net_pnl_to_date)} USDT</b></div>
        <div><small>ارزش نقدی پرتفوی</small><b>{money(report.cash_equity_to_date)} USDT</b></div>
        <div><small>نرخ معاملات برنده</small><b>{pct(report.win_rate_pct)}</b></div>
        <div><small>Profit Factor</small><b>{ratio(report.profit_factor)}</b></div>
        <div><small>حداکثر افت سرمایه</small><b className="negative">{money(report.max_drawdown_cash)} USDT · {pct(report.max_drawdown_pct)}</b></div>
        <div><small>تعداد معاملات بسته‌شده</small><b>{report.closed_trade_count}</b></div>
      </div>
      <div className="p10-submetrics">
        <div><small>Expectancy هر معامله</small><b>{money(report.expectancy_cash)} USDT</b></div>
        <div><small>میانگین معامله برنده</small><b className="positive">{money(report.average_win_cash)} USDT</b></div>
        <div><small>میانگین معامله بازنده</small><b className="negative">{money(report.average_loss_cash)} USDT</b></div>
        <div><small>Sharpe به‌ازای معامله</small><b>{ratio(report.sharpe_per_trade)}</b></div>
        <div><small>Sortino به‌ازای معامله</small><b>{ratio(report.sortino_per_trade)}</b></div>
        <div><small>مشاهدات R-multiple</small><b>{report.return_observations}</b></div>
      </div>
      <div className="p10-chart-card">
        <div className="p10-chart-title"><div><h3><TrendingUp size={16}/> منحنی سرمایه تحقق‌یافته</h3><small>بر اساس معاملات بسته‌شده · شروع از سرمایه اولیه</small></div><b>{money(report.initial_equity)} USDT</b></div>
        {chart?<div className="p10-chart-wrap"><svg viewBox={`0 0 ${chart.width} ${chart.height}`} role="img" aria-label="Realized equity curve">
          <line x1="12" y1="95" x2="888" y2="95" stroke="rgba(145,165,190,.22)" strokeDasharray="5 6"/>
          <polyline points={chart.points} fill="none" stroke="#43d6a1" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
        </svg><div className="p10-chart-range"><span>کمینه: {money(chart.min)}</span><span>بیشینه: {money(chart.max)}</span></div></div>:<div className="v11-empty">برای رسم منحنی سرمایه، حداقل یک معامله بسته‌شده لازم است.</div>}
      </div>
      <div className="p10-ranking">
        <div className="p10-ranking-head"><div><h3>رتبه‌بندی گروه‌های معاملاتی</h3><small>گروه‌بندی بر اساس نماد و جهت معامله؛ نه شناسه استراتژی</small></div><span>{report.cohort_ranking.length} گروه</span></div>
        {report.cohort_ranking.length?<div className="v11-tablewrap"><table className="v11-table"><thead><tr><th>گروه</th><th>معاملات</th><th>سود خالص</th><th>Win rate</th><th>Profit factor</th><th>Expectancy</th><th>میانگین R</th></tr></thead><tbody>{report.cohort_ranking.map(row=><tr key={row.group}><td><b>{row.group}</b></td><td>{row.closed_trades}</td><td className={row.net_pnl>=0?"positive":"negative"}>{money(row.net_pnl)}</td><td>{pct(row.win_rate_pct)}</td><td>{ratio(row.profit_factor)}</td><td>{money(row.expectancy_cash)}</td><td>{ratio(row.average_r)}</td></tr>)}</tbody></table></div>:<div className="v11-empty">هنوز معامله بسته‌شده‌ای برای رتبه‌بندی وجود ندارد.</div>}
      </div>
      <div className="p10-quality">
        <span className={report.sample_quality==="larger_sample"?"p10-sample-good":"p10-sample-low"}>{report.sample_quality==="larger_sample"?"نمونه بزرگ‌تر":report.sample_quality==="limited"?"نمونه محدود":"نمونه آماری ناکافی"}</span>
        <span>{report.closed_trade_count} معامله بسته‌شده از حداکثر {report.trades_returned} رکورد دریافت‌شده</span>
        {report.truncated&&<span>برای مشاهده کل سابقه، محدودیت ۵۰۰ رکورد اعمال شده است.</span>}
      </div>
      <div className="p10-limitations"><b><AlertTriangle size={15}/> محدودیت‌های آماری</b><ul>{report.limitations.map((x,i)=><li key={i}>{x}</li>)}</ul></div>
      <small className="p10-updated">آخرین به‌روزرسانی: {updated}</small>
    </>}
    {!report&&!loading&&!error&&<div className="v11-empty"><Activity size={20}/> گزارش هنوز داده‌ای ندارد.</div>}
  </section>;
}

