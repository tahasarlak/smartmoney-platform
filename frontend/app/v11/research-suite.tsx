"use client";
import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, RefreshCw, ShieldCheck } from "lucide-react";
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Props={token:string;portfolioId:string};
type Payload={status?:string;[key:string]:any};
async function get(path:string,token:string):Promise<Payload>{
 const r=await fetch(`${API}${path}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
 const j=await r.json().catch(()=>({detail:"Invalid API response"}));
 if(!r.ok) throw new Error(j.detail||`HTTP ${r.status}`); return j;
}
function metric(v:any){return v===null||v===undefined?"—":typeof v==="number"?v.toLocaleString("en-US",{maximumFractionDigits:3}):String(v)}
export default function ResearchSuite({token,portfolioId}:Props){
 const [mc,setMc]=useState<Payload|null>(null),[rob,setRob]=useState<Payload|null>(null),[audit,setAudit]=useState<Payload|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 const refresh=useCallback(async()=>{if(!token||!portfolioId)return;setBusy(true);setError("");try{const [a,b,c]=await Promise.all([
 get(`/api/v1/v11/portfolios/${portfolioId}/monte-carlo?limit=500&simulations=2000&horizon=100`,token),
 get(`/api/v1/v11/portfolios/${portfolioId}/robustness?limit=500&cost_stress_r=0.05&windows=4`,token),
 get(`/api/v1/v11/portfolios/${portfolioId}/research-audit?limit=500`,token)]);setMc(a);setRob(b);setAudit(c);}catch(e){setError(e instanceof Error?e.message:"Research request failed");}finally{setBusy(false);}},[token,portfolioId]);
 useEffect(()=>{void refresh()},[refresh]);
 if(!portfolioId)return <section className="card p1315"><h2>تحلیل تحقیقاتی پیشرفته</h2><p>ابتدا پرتفوی را انتخاب کنید.</p></section>;
 return <section className="card p1315" dir="rtl"><div className="p1315-head"><div><span className="p1315-kicker">RESEARCH & VALIDATION · PHASE 13–15</span><h2><Activity size={19}/> آزمایشگاه پایداری و ممیزی TRADF</h2><p>تحلیل سناریو، فشار هزینه و کیفیت داده‌های معاملات آزمایشی</p></div><button onClick={()=>void refresh()} disabled={busy} className="p1315-refresh"><RefreshCw size={15}/> {busy?"در حال بررسی":"بروزرسانی"}</button></div>
 {error&&<div className="p1315-error"><AlertTriangle size={16}/>{error}</div>}
 <div className="p1315-grid">
 <article><h3>Phase 13 · Monte Carlo</h3><b>{mc?.status||"—"}</b><p>تعداد معاملات معتبر: {metric(mc?.trade_count)}</p><p>احتمال پایان مثبت در شبیه‌سازی: {metric(mc?.positive_ending_probability_pct)}{mc?.positive_ending_probability_pct==null?"":"%"}</p><p>میانه نتیجه: {metric(mc?.ending_r_quantiles?.p50)} R</p><p>صدک ۹۵ افت: {metric(mc?.max_drawdown_r_quantiles?.p95)} R</p></article>
 <article><h3>Phase 14 · Robustness</h3><b>{rob?.status||"—"}</b><p>امتیاز تشخیصی پایداری: {metric(rob?.robustness_score)}{rob?.robustness_score==null?"":" / 100"}</p><p>میانگین R پایه: {metric(rob?.base_metrics?.mean_r)}</p><p>میانگین R تحت فشار هزینه: {metric(rob?.stressed_metrics?.mean_r)}</p><p>پنجره‌های مثبت: {metric(rob?.positive_windows)} از {metric(rob?.window_count)}</p></article>
 <article><h3>Phase 15 · Research Audit</h3><b>{audit?.status||"—"}</b><p><ShieldCheck size={14}/> بررسی‌ها: {metric(audit?.passed_count)} موفق</p><p>هشدارها: {metric(audit?.warning_count)}</p><p>معاملات معتبر: {metric(audit?.valid_closed_trade_count)}</p><p>اجرای واقعی: غیرفعال</p></article>
 </div>
 <div className="p1315-notes"><b>محدودیت روش‌شناسی</b><ul><li>Monte Carlo از بازنمونه‌گیری معاملات بسته‌شده استفاده می‌کند و پیش‌بینی بازار نیست.</li><li>Robustness آزمون حساسیت هزینه و پنجره‌های زمانی است؛ بهینه‌سازی پارامتر یا اجرای مجدد سیگنال روی OHLC نیست.</li><li>ممیزی فقط کیفیت داده‌های Paper را بررسی می‌کند؛ تأیید سودآوری یا آمادگی Live محسوب نمی‌شود.</li></ul></div>
 </section>;
}
