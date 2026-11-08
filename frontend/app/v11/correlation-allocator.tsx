"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, RefreshCw, ShieldCheck, Plus, Trash2 } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
type Candidate = {symbol:string;direction:"long"|"short";entry:string;stop:string;quality_score:string};
type Allocation = {
  symbol:string;direction:string;entry:number;stop:number;quantity:number;notional:number;
  risk_cash:number;risk_pct:number;quality_score:number;adjusted_allocation_score:number;
  average_effective_correlation:number|null;positive_correlation_crowding:number;
  correlation_penalty_factor:number;
};
type Result = {
  equity:number;budget_cash:number;allocated_risk_cash:number;unallocated_risk_cash:number;
  allocations:Allocation[];rejected:{symbol?:string;reason:string}[];
  correlation:{return_observations:number;penalty_strength:number;matrix:Record<string,Record<string,number|null>>};
  candidate_diagnostics:Record<string,{original_quality_score:number;adjusted_allocation_score:number;positive_correlation_crowding:number;correlation_penalty_factor:number}>;
  execution_allowed:false;note:string;
};
const blank=():Candidate=>({symbol:"",direction:"long",entry:"",stop:"",quality_score:"70"});
const money=(n:number)=>new Intl.NumberFormat("en-US",{maximumFractionDigits:3}).format(Number.isFinite(n)?n:0);

export default function CorrelationAllocator({token,portfolioId}:{token:string;portfolioId:string}) {
  const [rows,setRows]=useState<Candidate[]>([blank(),{...blank(),symbol:"ETHUSDT"}]);
  const [interval,setInterval]=useState("1h");
  const [limit,setLimit]=useState("300");
  const [budget,setBudget]=useState("");
  const [penalty,setPenalty]=useState("1");
  const [risk,setRisk]=useState<any>(null);
  const [result,setResult]=useState<Result|null>(null);
  const [loading,setLoading]=useState(false);
  const [progress,setProgress]=useState("");
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");

  const request=useCallback(async(path:string,init:RequestInit={})=>{
    const headers=new Headers(init.headers||{});
    headers.set("Authorization",`Bearer ${token}`);
    if(init.body) headers.set("Content-Type","application/json");
    const response=await fetch(`${API}${path}`,{...init,headers,cache:"no-store"});
    const body=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(body.detail||`API ${response.status}`);
    return body;
  },[token]);

  const loadRisk=useCallback(async()=>{
    if(!token||!portfolioId){setRisk(null);return;}
    try{
      const data=await request(`/api/v1/v11/portfolios/${encodeURIComponent(portfolioId)}/risk`);
      setRisk(data);
      setBudget(String(data.risk_limit_pct??""));
    }catch(e){setRisk(null);}
  },[token,portfolioId,request]);

  useEffect(()=>{void loadRisk();setResult(null);},[loadRisk]);

  function update(index:number,key:keyof Candidate,value:string){
    setRows(current=>current.map((r,i)=>i===index?{...r,[key]:value}:r));
  }
  function add(){
    if(rows.length<8)setRows(current=>[...current,blank()]);
  }
  function remove(index:number){
    if(rows.length>2)setRows(current=>current.filter((_,i)=>i!==index));
  }

  async function calculate(){
    setError("");setNotice("");setResult(null);
    if(!portfolioId){setError("ابتدا یک پرتفوی انتخاب کنید.");return;}
    const candidates=rows.map(r=>({
      symbol:r.symbol.trim().toUpperCase(),direction:r.direction,
      entry:Number(r.entry),stop:Number(r.stop),quality_score:Number(r.quality_score)
    }));
    if(candidates.some(c=>!c.symbol||!Number.isFinite(c.entry)||c.entry<=0||!Number.isFinite(c.stop)||c.stop<=0||!Number.isFinite(c.quality_score)||c.quality_score<0||c.quality_score>100)){
      setError("اطلاعات نمادها، ورود، حد ضرر و امتیاز کیفیت را بررسی کنید.");return;
    }
    if(new Set(candidates.map(c=>c.symbol)).size!==candidates.length){
      setError("هر نماد باید فقط یک بار وارد شود.");return;
    }
    const n=Number(limit),strength=Number(penalty),budgetPct=Number(budget);
    if(!Number.isInteger(n)||n<50||n>1000||!Number.isFinite(strength)||strength<0||strength>5){
      setError("مقادیر تعداد کندل یا شدت جریمه همبستگی نامعتبر است.");return;
    }
    setLoading(true);
    try{
      const series:Record<string,Map<number,number>>={};
      for(let i=0;i<candidates.length;i++){
        const symbol=candidates[i].symbol;
        setProgress(`دریافت تاریخچه ${symbol} (${i+1}/${candidates.length})`);
        const response=await request("/api/v1/market/binance/klines",{
          method:"POST",body:JSON.stringify({symbol,interval,limit:n})
        });
        const candles=(response.candles||[]).slice(0,-1);
        series[symbol]=new Map(candles.map((c:any)=>[Number(c.time),Number(c.close)]));
      }
      const first=series[candidates[0].symbol];
      const common=[...first.keys()].filter(t=>candidates.every(c=>series[c.symbol].has(t))).sort((a,b)=>a-b);
      if(common.length<21)throw new Error(`داده‌های هم‌زمان کافی نیست؛ فقط ${common.length} قیمت مشترک دریافت شد.`);
      const prices_by_symbol:Record<string,number[]>={};
      for(const c of candidates)prices_by_symbol[c.symbol]=common.map(t=>series[c.symbol].get(t)!);
      setProgress("محاسبه تخصیص با تعدیل همبستگی در Backend");
      const payload:any={
        candidates,prices_by_symbol,
        correlation_penalty_strength:strength,
        min_observations:20
      };
      if(budget.trim())payload.requested_budget_pct=budgetPct;
      const data=await request(`/api/v1/v11/portfolios/${encodeURIComponent(portfolioId)}/risk/allocate-correlated`,{
        method:"POST",body:JSON.stringify(payload)
      });
      setResult(data);
      setNotice("تخصیص با لحاظ همبستگی محاسبه شد؛ هیچ سفارش یا پوزیشنی ایجاد نشده است.");
    }catch(e){
      setError(e instanceof Error?e.message:"محاسبه تخصیص همبستگی‌محور ناموفق بود.");
    }finally{setLoading(false);setProgress("");}
  }

  return <section id="correlation-allocation" className="p9-correlated card">
    <div className="p9-head">
      <div><span className="v11-eyebrow">PHASE 9 · CORRELATION-AWARE ALLOCATION</span>
        <h2><Activity size={19}/> تخصیص سرمایه با تعدیل همبستگی</h2>
        <p className="muted">امتیاز کیفیت، جهت معامله و همبستگی تاریخی بازده‌ها را برای کاهش تمرکز معاملات هم‌جهت ترکیب می‌کند.</p>
      </div>
      <button type="button" className="v11-iconbtn" onClick={()=>void loadRisk()} disabled={loading} title="به‌روزرسانی ریسک"><RefreshCw size={16}/></button>
    </div>
    {risk&&<div className="p9-risk-strip">
      <div><small>ارزش پرتفوی</small><b>{money(risk.equity)} USDT</b></div>
      <div><small>ریسک باز فعلی</small><b>{money(risk.total_open_risk_cash)} USDT · {money(risk.total_open_risk_pct)}%</b></div>
      <div><small>بودجه باقی‌مانده</small><b>{money(risk.remaining_risk_budget_cash)} USDT</b></div>
      <div><small>وضعیت</small><b>{risk.status}</b></div>
    </div>}
    {!portfolioId&&<div className="v11-error">برای ادامه، یک پرتفوی انتخاب کنید.</div>}
    {error&&<div className="v11-error">{error}</div>}
    {notice&&<div className="v11-success">{notice}</div>}
    <div className="p9-candidate-head"><h3>فرصت‌های معاملاتی</h3><button type="button" className="v11-link" onClick={add} disabled={rows.length>=8}><Plus size={14}/> افزودن نماد</button></div>
    {rows.map((r,i)=><div className="p9-candidate" key={i}>
      <div className="p9-candidate-title"><b>فرصت {i+1}</b><button className="v11-iconbtn" type="button" onClick={()=>remove(i)} disabled={rows.length<=2} aria-label="حذف"><Trash2 size={14}/></button></div>
      <div className="p9-fields">
        <label>نماد<input value={r.symbol} onChange={e=>update(i,"symbol",e.target.value.toUpperCase())} placeholder="BTCUSDT"/></label>
        <label>جهت<select value={r.direction} onChange={e=>update(i,"direction",e.target.value as Candidate["direction"])}><option value="long">Long</option><option value="short">Short</option></select></label>
        <label>قیمت ورود<input type="number" min="0.00000001" step="any" value={r.entry} onChange={e=>update(i,"entry",e.target.value)}/></label>
        <label>حد ضرر<input type="number" min="0.00000001" step="any" value={r.stop} onChange={e=>update(i,"stop",e.target.value)}/></label>
        <label>امتیاز کیفیت<input type="number" min="0" max="100" value={r.quality_score} onChange={e=>update(i,"quality_score",e.target.value)}/></label>
      </div>
    </div>)}
    <div className="p9-settings">
      <label>تایم‌فریم<select value={interval} onChange={e=>setInterval(e.target.value)}><option value="15m">15 دقیقه</option><option value="1h">1 ساعت</option><option value="4h">4 ساعت</option><option value="1d">روزانه</option></select></label>
      <label>تعداد کندل<select value={limit} onChange={e=>setLimit(e.target.value)}><option value="100">100</option><option value="200">200</option><option value="300">300</option><option value="500">500</option><option value="1000">1000</option></select></label>
      <label>شدت جریمه همبستگی<input type="number" min="0" max="5" step="0.1" value={penalty} onChange={e=>setPenalty(e.target.value)}/></label>
      <label>بودجه ریسک کل (%)<input type="number" min="0.01" max={risk?.risk_limit_pct||100} step="0.01" value={budget} onChange={e=>setBudget(e.target.value)}/></label>
    </div>
    {progress&&<div className="p9-progress"><Activity size={15}/>{progress}</div>}
    <button type="button" className="btn p9-calculate" disabled={loading||!portfolioId||!token} onClick={()=>void calculate()}>{loading?"در حال محاسبه…":"محاسبه تخصیص هوشمند"}</button>
    {result&&<>
      <div className="p9-result-title"><h3>نتیجه تخصیص تعدیل‌شده</h3><span className="v11-badge">بدون اجرای سفارش</span></div>
      <div className="p9-risk-strip">
        <div><small>بودجه ریسک</small><b>{money(result.budget_cash)} USDT</b></div>
        <div><small>ریسک تخصیص‌یافته</small><b>{money(result.allocated_risk_cash)} USDT</b></div>
        <div><small>ریسک استفاده‌نشده</small><b>{money(result.unallocated_risk_cash)} USDT</b></div>
        <div><small>مشاهدات تاریخی</small><b>{result.correlation.return_observations}</b></div>
      </div>
      {result.allocations.length>0?<div className="v11-tablewrap"><table className="v11-table"><thead><tr><th>نماد</th><th>جهت</th><th>حجم</th><th>ریسک</th><th>امتیاز تعدیل‌شده</th><th>جریمه همبستگی</th></tr></thead><tbody>{result.allocations.map(a=><tr key={a.symbol}><td><b>{a.symbol}</b></td><td>{a.direction.toUpperCase()}</td><td>{a.quantity}</td><td>{money(a.risk_cash)} USDT</td><td>{a.adjusted_allocation_score.toFixed(2)}</td><td>{a.correlation_penalty_factor.toFixed(3)}x</td></tr>)}</tbody></table></div>:<div className="v11-empty">با محدودیت‌های فعلی تخصیصی انجام نشد.</div>}
      <div className="p9-diagnostics"><h3>تشخیص تمرکز همبستگی</h3>{Object.entries(result.candidate_diagnostics).map(([symbol,d])=><div key={symbol}><b>{symbol}</b><span>همبستگی مثبت مؤثر: {d.positive_correlation_crowding.toFixed(3)}</span><span>امتیاز: {d.original_quality_score.toFixed(1)} ← {d.adjusted_allocation_score.toFixed(2)}</span></div>)}</div>
      {result.rejected.length>0&&<div className="p9-rejected">{result.rejected.map((x,i)=><p key={i}>{x.symbol||"—"}: {x.reason}</p>)}</div>}
      <p className="p9-note">{result.note}</p>
    </>}
    <p className="p9-disclaimer"><AlertTriangle size={14}/> این یک روش وزن‌دهی ابتکاری بر پایه همبستگی تاریخی است، نه بهینه‌سازی کامل ماتریس کوواریانس. همبستگی ممکن است تغییر کند. خروجی صرفاً تحلیلی است و هیچ معامله‌ای اجرا نمی‌شود.</p>
  </section>;
}
