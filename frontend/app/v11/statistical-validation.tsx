"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, BadgeCheck, BarChart3, RefreshCw } from "lucide-react";

const API=(process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000").replace(/\/$/,"");
type Report={
 status:string;mode:string;portfolio_name:string;closed_trade_count:number;valid_r_observations:number;
 sample_quality:string;mean_r:number|null;median_r:number|null;win_rate_pct:number|null;
 win_rate_ci95_pct:[number,number]|null;expectancy_r_ci95:[number,number]|null;
 bootstrap_positive_expectancy_share:number|null;bootstrap_iterations:number;bootstrap_ci_excludes_zero:boolean;
 profit_factor:number|null;longest_losing_streak:number;best_trade_r:number|null;worst_trade_r:number|null;
 p05_trade_r:number|null;p95_trade_r:number|null;warnings:string[];limitations:string[];execution_allowed:false;
};
const n=(v:number|null|undefined,d=3)=>v==null?"—":v.toFixed(d);

export default function StatisticalValidation({token,portfolioId}:{token:string;portfolioId:string}){
 const [report,setReport]=useState<Report|null>(null);
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState("");
 const [updated,setUpdated]=useState("");
 const load=useCallback(async()=>{
  if(!token||!portfolioId){setReport(null);return;}
  setLoading(true);setError("");
  try{
   const response=await fetch(`${API}/api/v1/v11/portfolios/${encodeURIComponent(portfolioId)}/validation?limit=500&bootstrap_iterations=2000`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
   const body=await response.json().catch(()=>({}));
   if(!response.ok)throw new Error(body.detail||`API ${response.status}`);
   setReport(body);setUpdated(new Date().toLocaleString());
  }catch(e){setError(e instanceof Error?e.message:"اعتبارسنجی آماری دریافت نشد.");}
  finally{setLoading(false);}
 },[token,portfolioId]);
 useEffect(()=>{void load();},[load]);
 const quality=report?.sample_quality==="larger_sample"?"نمونه بزرگ‌تر":report?.sample_quality==="preliminary"?"نمونه مقدماتی":"نمونه ناکافی";
 return <section id="statistical-validation" className="p11-validation card">
  <div className="p11-head"><div><span className="v11-eyebrow">PHASE 11 · STATISTICAL VALIDATION</span><h2><BarChart3 size={19}/> اعتبارسنجی آماری عملکرد</h2><p className="muted">بررسی عدم‌قطعیت نتایج معاملات بسته‌شده با بازنمونه‌گیری آماری؛ بدون پیش‌بینی سود آینده.</p></div>
   <button type="button" className="v11-iconbtn" onClick={()=>void load()} disabled={loading} title="به‌روزرسانی"><RefreshCw size={16}/></button></div>
  {error&&<div className="v11-error">{error}</div>}
  {!portfolioId&&<div className="v11-error">ابتدا یک پرتفوی انتخاب کنید.</div>}
  {loading&&!report&&<div className="v11-empty">در حال محاسبه اعتبارسنجی…</div>}
  {report&&<>
   <div className="p11-status"><div><small>کیفیت نمونه</small><b>{quality}</b></div><div><small>معاملات معتبر بسته‌شده</small><b>{report.closed_trade_count}</b></div><div><small>وضعیت شواهد</small><b className={report.bootstrap_ci_excludes_zero?"p11-positive":"p11-caution"}>{report.bootstrap_ci_excludes_zero?"بازه اطمینان بالای صفر":"شواهد مثبت قطعی نیست"}</b></div></div>
   <div className="p11-grid">
    <article><small>میانگین Expectancy</small><strong>{n(report.mean_r)} R</strong><span>بازه اطمینان ۹۵٪: {report.expectancy_r_ci95?`${n(report.expectancy_r_ci95[0])} تا ${n(report.expectancy_r_ci95[1])} R`:"—"}</span></article>
    <article><small>Win Rate</small><strong>{report.win_rate_pct==null?"—":`${n(report.win_rate_pct,1)}٪`}</strong><span>Wilson CI ۹۵٪: {report.win_rate_ci95_pct?`${n(report.win_rate_ci95_pct[0],1)}٪ تا ${n(report.win_rate_ci95_pct[1],1)}٪`:"—"}</span></article>
    <article><small>Profit Factor</small><strong>{n(report.profit_factor)}</strong><span>بر اساس سود و زیان خالص</span></article>
    <article><small>Bootstrap مثبت</small><strong>{report.bootstrap_positive_expectancy_share==null?"—":`${n(report.bootstrap_positive_expectancy_share*100,1)}٪`}</strong><span>{report.bootstrap_iterations.toLocaleString()} بازنمونه‌گیری</span></article>
    <article><small>Median R</small><strong>{n(report.median_r)} R</strong><span>صدک ۵: {n(report.p05_trade_r)} R</span></article>
    <article><small>بیشترین زنجیره زیان</small><strong>{report.longest_losing_streak}</strong><span>معامله متوالی</span></article>
   </div>
   <div className="p11-method"><BadgeCheck size={16}/><span>Expectancy بر مبنای R-multiple و بازه اطمینان با Bootstrap percentile محاسبه شده؛ Win Rate از Wilson score استفاده می‌کند.</span></div>
   <div className="p11-warnings"><h3><AlertTriangle size={16}/> تفسیر و محدودیت‌ها</h3>{report.warnings.map((w,i)=><p key={i}>{w}</p>)}</div>
   <details className="p11-details"><summary>روش‌شناسی کامل</summary><ul>{report.limitations.map((x,i)=><li key={i}>{x}</li>)}</ul></details>
   <small className="p11-updated">آخرین محاسبه: {updated} · فقط معاملات Paper</small>
  </>}
  <p className="p11-disclaimer"><AlertTriangle size={14}/> این گزارش اعتبارسنجی آماری نمونه معاملات ثبت‌شده است، نه اثبات سودآوری استراتژی. همبستگی زمانی معاملات، سوگیری انتخاب و تغییر رژیم بازار ممکن است نتایج را مخدوش کنند. اجرای واقعی غیرفعال است.</p>
 </section>;
}
