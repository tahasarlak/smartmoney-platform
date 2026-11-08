"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, GitBranch, ShieldCheck } from "lucide-react";

const API=(process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000").replace(/\/$/,"");
type Metric={trade_count:number;mean_r:number|null;median_r:number|null;win_rate_pct:number|null;profit_factor_r:number|null};
type Fold={fold:number;train:Metric;out_of_sample:Metric;train_start:string;train_end:string;test_start:string;test_end:string;out_of_sample_positive_expectancy:boolean};
type Report={status:string;portfolio_name:string;valid_closed_trade_count:number;skipped_trade_count:number;initial_train_trade_count:number;out_of_sample_trade_count:number;completed_folds:number;sample_quality:string;in_sample:Metric;out_of_sample:Metric;positive_oos_folds:number;oos_positive_fold_pct:number|null;folds:Fold[];limitations:string[];execution_allowed:false;truncated:boolean};

const fmt=(v:number|null|undefined,d=3)=>v==null?"—":v.toFixed(d);
const date=(v:string)=>{try{return new Date(v).toLocaleDateString("fa-IR")}catch{return v}};

export default function WalkForwardValidation({token,portfolioId}:{token:string;portfolioId:string}){
 const [report,setReport]=useState<Report|null>(null);
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState("");
 const load=useCallback(async()=>{
  if(!token||!portfolioId){setReport(null);return;}
  setLoading(true);setError("");
  try{
   const res=await fetch(`${API}/api/v1/v11/portfolios/${encodeURIComponent(portfolioId)}/walk-forward?limit=500&folds=4&min_train_fraction=0.5`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
   const body=await res.json().catch(()=>({}));
   if(!res.ok)throw new Error(body.detail||`API ${res.status}`);
   setReport(body);
  }catch(e){setError(e instanceof Error?e.message:"گزارش Walk-Forward دریافت نشد.");}
  finally{setLoading(false);}
 },[token,portfolioId]);
 useEffect(()=>{void load()},[load]);
 const positive=report?.status==="oos_positive_across_folds";
 return <section id="walk-forward-validation" className="p12-wf card">
  <div className="p12-wf-head"><div><span className="v11-eyebrow">PHASE 12 · WALK-FORWARD / OOS</span><h2><GitBranch size={19}/> ارزیابی زمانی خارج از نمونه</h2><p className="muted">معاملات بسته‌شده به ترتیب زمان تقسیم می‌شوند؛ بخش‌های آینده برای ارزیابی کنار گذاشته می‌شوند.</p></div><button className="v11-iconbtn" onClick={()=>void load()} disabled={loading} title="به‌روزرسانی"><RefreshCw size={16}/></button></div>
  {error&&<div className="v11-error">{error}</div>}
  {!portfolioId&&<div className="v11-empty">ابتدا یک پرتفوی انتخاب کنید.</div>}
  {loading&&!report&&<div className="v11-empty">در حال محاسبه Foldها…</div>}
  {report&&<>
   <div className="p12-wf-status"><b className={positive?"positive":"p12-warn"}>{report.status==="oos_positive_across_folds"?"مثبت در تمام Foldها":report.status==="mixed_oos"?"نتایج ترکیبی خارج از نمونه":report.status==="oos_not_positive"?"میانگین خارج از نمونه مثبت نیست":"نمونه ناکافی"}</b><span>{report.valid_closed_trade_count} معامله معتبر · {report.out_of_sample_trade_count} معامله OOS · {report.completed_folds} Fold</span></div>
   <div className="p12-wf-grid">
    <article><small>میانگین داخل نمونه</small><strong>{fmt(report.in_sample.mean_r)} R</strong><span>{report.in_sample.trade_count} معامله</span></article>
    <article><small>میانگین خارج از نمونه</small><strong className={(report.out_of_sample.mean_r||0)>=0?"positive":"negative"}>{fmt(report.out_of_sample.mean_r)} R</strong><span>{report.out_of_sample.trade_count} معامله</span></article>
    <article><small>Foldهای مثبت OOS</small><strong>{report.oos_positive_fold_pct==null?"—":`${fmt(report.oos_positive_fold_pct,1)}٪`}</strong><span>{report.positive_oos_folds} از {report.completed_folds}</span></article>
    <article><small>Win Rate خارج از نمونه</small><strong>{report.out_of_sample.win_rate_pct==null?"—":`${fmt(report.out_of_sample.win_rate_pct,1)}٪`}</strong><span>بر مبنای R خالص</span></article>
   </div>
   <div className="p12-folds"><h3>جزئیات Foldها</h3><div className="p12-fold-table"><div className="p12-fold-row p12-fold-label"><span>Fold</span><span>بازه آموزش</span><span>بازه آزمون</span><span>میانگین OOS</span></div>{report.folds.map(f=><div className="p12-fold-row" key={f.fold}><b>{f.fold}</b><span>{date(f.train_start)} – {date(f.train_end)}</span><span>{date(f.test_start)} – {date(f.test_end)}</span><strong className={(f.out_of_sample.mean_r||0)>=0?"positive":"negative"}>{fmt(f.out_of_sample.mean_r)} R</strong></div>)}</div></div>
   {report.truncated&&<p className="p12-warn">محدودیت ۵۰۰ رکورد اعمال شده؛ ممکن است تمام سابقه در این گزارش نباشد.</p>}
   <details className="p11-details"><summary>محدودیت‌های روش</summary><ul>{report.limitations.map((x,i)=><li key={i}>{x}</li>)}</ul></details>
  </>}
  <p className="p12-wf-disclaimer"><AlertTriangle size={14}/> این گزارش Walk-Forward روی نتایج معاملات آزمایشی ثبت‌شده انجام می‌شود؛ استراتژی را روی کندل‌های تاریخی دوباره اجرا یا پارامترها را آموزش نمی‌دهد. بنابراین جایگزین بک‌تست واقعی بازار و اثبات سودآوری نیست. <ShieldCheck size={14}/> اجرای واقعی غیرفعال است.</p>
 </section>;
}
