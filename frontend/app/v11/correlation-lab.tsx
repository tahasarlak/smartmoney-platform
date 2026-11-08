"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, BarChart3, RefreshCw, ShieldCheck } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

type Candle = { time:number; close:number };
type Pair = { symbol_a:string; symbol_b:string; correlation:number|null; relationship:string };
type MatrixResult = {
  symbols:string[];
  return_observations:number;
  method:string;
  matrix:Record<string,Record<string,number|null>>;
  pairs:Pair[];
  note:string;
};
type Risk = {
  risk_by_symbol?:Record<string,{risk_cash:number;risk_pct:number}>;
  positions?:{symbol:string;direction:string;risk_cash:number;risk_pct:number;notional:number}[];
  status?:string;
  total_open_risk_pct?:number;
};
const DEFAULT_SYMBOLS = "BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT";
const fmt = (n:number) => new Intl.NumberFormat("en-US",{maximumFractionDigits:3}).format(n);
const corrLabel = (v:number|null) => v===null ? "ناموجود" : v>=0.75 ? "مثبت قوی" : v>=0.4 ? "مثبت متوسط" : v<=-0.75 ? "منفی قوی" : v<=-0.4 ? "منفی متوسط" : "ضعیف";
function corrColor(v:number|null) {
  if (v===null) return "rgba(125,145,168,.12)";
  const strength=Math.min(1,Math.abs(v));
  return v>=0 ? `rgba(239,105,119,${.08+strength*.42})` : `rgba(54,191,151,${.08+strength*.42})`;
}

export default function CorrelationLab({token,portfolioId}:{token:string;portfolioId:string}) {
  const [symbolsText,setSymbolsText]=useState(DEFAULT_SYMBOLS);
  const [interval,setInterval]=useState("1h");
  const [limit,setLimit]=useState("300");
  const [minObs,setMinObs]=useState("30");
  const [risk,setRisk]=useState<Risk|null>(null);
  const [result,setResult]=useState<MatrixResult|null>(null);
  const [loading,setLoading]=useState(false);
  const [progress,setProgress]=useState("");
  const [error,setError]=useState("");
  const [updatedAt,setUpdatedAt]=useState("");

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
      const held=Object.keys(data.risk_by_symbol||{});
      if(held.length>=2) setSymbolsText(held.slice(0,8).join(", "));
      else if(held.length===1) setSymbolsText(`${held[0]}, ETHUSDT, BNBUSDT`);
    }catch{
      setRisk(null);
    }
  },[token,portfolioId,request]);

  useEffect(()=>{void loadRisk();setResult(null);},[loadRisk]);

  const symbols=useMemo(()=>Array.from(new Set(symbolsText.split(/[,\s]+/).map(x=>x.trim().toUpperCase()).filter(Boolean))),[symbolsText]);
  const avgAbs=useMemo(()=>{
    if(!result?.pairs.length)return null;
    const values=result.pairs.map(p=>p.correlation).filter((v):v is number=>v!==null);
    return values.length?values.reduce((a,b)=>a+Math.abs(b),0)/values.length:null;
  },[result]);
  const strongest=useMemo(()=>result?.pairs.filter(p=>p.correlation!==null).slice().sort((a,b)=>Math.abs(b.correlation!)-Math.abs(a.correlation!))[0]||null,[result]);
  const highPairs=useMemo(()=>result?.pairs.filter(p=>p.correlation!==null&&Math.abs(p.correlation)>=.75).length||0,[result]);

  async function analyze(){
    setError("");setResult(null);setUpdatedAt("");
    if(!token){setError("ابتدا وارد حساب کاربری شوید.");return;}
    if(symbols.length<2||symbols.length>12){setError("بین ۲ تا ۱۲ نماد یکتا وارد کنید.");return;}
    const candleLimit=Number(limit), min=Number(minObs);
    if(!Number.isInteger(candleLimit)||candleLimit<50||candleLimit>1000){setError("تعداد کندل باید بین ۵۰ تا ۱۰۰۰ باشد.");return;}
    if(!Number.isInteger(min)||min<3||min>5000){setError("حداقل مشاهدات نامعتبر است.");return;}
    setLoading(true);
    try{
      const series:Record<string,Map<number,number>>={};
      for(let i=0;i<symbols.length;i++){
        const symbol=symbols[i];
        setProgress(`دریافت داده ${symbol} (${i+1}/${symbols.length})`);
        const data=await request("/api/v1/market/binance/klines",{
          method:"POST",
          body:JSON.stringify({symbol,interval,limit:candleLimit})
        });
        const candles:Candle[]=(data.candles||[]).slice(0,-1);
        series[symbol]=new Map(candles.map(c=>[Number(c.time),Number(c.close)]));
      }
      const first=series[symbols[0]];
      const common=[...first.keys()].filter(t=>symbols.every(s=>series[s].has(t))).sort((a,b)=>a-b);
      if(common.length<min+1) throw new Error(`داده هم‌زمان کافی نیست؛ ${common.length} قیمت مشترک پیدا شد و حداقل ${min+1} مورد لازم است.`);
      const prices_by_symbol:Record<string,number[]>={};
      for(const symbol of symbols) prices_by_symbol[symbol]=common.map(t=>series[symbol].get(t)!);
      setProgress("محاسبه ماتریس همبستگی");
      const data=await request("/api/v1/v11/risk/correlation",{
        method:"POST",
        body:JSON.stringify({prices_by_symbol,min_observations:min})
      });
      setResult(data);
      setUpdatedAt(new Date().toLocaleString());
      setProgress("");
    }catch(e){
      setError(e instanceof Error?e.message:"تحلیل همبستگی انجام نشد.");
      setProgress("");
    }finally{setLoading(false);}
  }

  return <section id="correlation-lab" className="p8-correlation card">
    <div className="p8-head">
      <div><span className="v11-eyebrow">PHASE 8 · PORTFOLIO DIVERSIFICATION</span>
        <h2><BarChart3 size={19}/> تحلیل همبستگی و تنوع پرتفوی</h2>
        <p className="muted">همبستگی بازده تاریخی دارایی‌ها را از کندل‌های هم‌زمان محاسبه می‌کند؛ داده‌های ناقص یا غیرهم‌زمان وارد محاسبه نمی‌شوند.</p>
      </div>
      <button type="button" className="v11-iconbtn" onClick={()=>void loadRisk()} title="به‌روزرسانی ریسک"><RefreshCw size={16}/></button>
    </div>

    {risk&&<div className="p8-current-risk">
      <div><small>ریسک باز فعلی پرتفوی</small><b>{fmt(risk.total_open_risk_pct||0)}٪</b></div>
      <div><small>نمادهای دارای ریسک باز</small><b>{Object.keys(risk.risk_by_symbol||{}).length}</b></div>
      <div><small>وضعیت کنترل ریسک</small><b className={risk.status==="healthy"?"p8-good":risk.status==="blocked"?"p8-bad":"p8-warn"}>{risk.status||"نامشخص"}</b></div>
    </div>}

    <div className="p8-controls">
      <label className="p8-symbols">نمادها (با کاما جدا کنید)
        <input value={symbolsText} onChange={e=>setSymbolsText(e.target.value.toUpperCase())} placeholder="BTCUSDT, ETHUSDT, SOLUSDT"/>
        <small>{symbols.length} نماد یکتا · حداکثر ۱۲ نماد</small>
      </label>
      <label>تایم‌فریم
        <select value={interval} onChange={e=>setInterval(e.target.value)}>
          <option value="15m">15 دقیقه</option><option value="1h">1 ساعت</option>
          <option value="4h">4 ساعت</option><option value="1d">روزانه</option>
        </select>
      </label>
      <label>تعداد کندل
        <select value={limit} onChange={e=>setLimit(e.target.value)}>
          <option value="100">100</option><option value="200">200</option><option value="300">300</option><option value="500">500</option><option value="1000">1000</option>
        </select>
      </label>
      <label>حداقل بازده‌های مشترک
        <select value={minObs} onChange={e=>setMinObs(e.target.value)}>
          <option value="20">20</option><option value="30">30</option><option value="50">50</option><option value="100">100</option>
        </select>
      </label>
      <button className="btn p8-run" type="button" disabled={loading||!token||!portfolioId} onClick={()=>void analyze()}>
        {loading?"در حال تحلیل…":"محاسبه همبستگی"}
      </button>
    </div>
    {!portfolioId&&<div className="v11-error">برای تحلیل پرتفوی، ابتدا یک پرتفوی انتخاب کنید.</div>}
    {progress&&<div className="p8-progress"><Activity size={15}/>{progress}</div>}
    {error&&<div className="v11-error">{error}</div>}

    {result&&<>
      <div className="p8-summary">
        <div><small>تعداد بازده‌های مشترک</small><b>{result.return_observations}</b></div>
        <div><small>میانگین قدر مطلق همبستگی</small><b>{avgAbs===null?"—":`${(avgAbs*100).toFixed(1)}٪`}</b></div>
        <div><small>جفت‌های با همبستگی قوی</small><b>{highPairs}</b></div>
        <div><small>بیشترین همبستگی مطلق</small><b>{strongest?`${strongest.correlation!.toFixed(3)}`:"—"}</b></div>
      </div>
      <div className="p8-method"><ShieldCheck size={16}/><span>روش: Pearson روی بازده ساده کندل‌های بسته‌شده · آخرین کندل ناقص حذف شده · محاسبه در Backend انجام شده است.</span></div>
      <div className="p8-matrix-wrap"><table className="p8-matrix">
        <thead><tr><th>نماد</th>{result.symbols.map(s=><th key={s}>{s}</th>)}</tr></thead>
        <tbody>{result.symbols.map(a=><tr key={a}><th>{a}</th>{result.symbols.map(b=>{
          const value=result.matrix[a]?.[b]??null;
          return <td key={b} style={{background:corrColor(value)}} title={`${a} / ${b}: ${value===null?"N/A":value.toFixed(4)}`}>{value===null?"—":value.toFixed(2)}</td>;
        })}</tr>)}</tbody>
      </table></div>
      <div className="p8-pairs">
        <h3>جفت‌های مهم همبستگی</h3>
        {result.pairs.slice().sort((a,b)=>Math.abs(b.correlation??0)-Math.abs(a.correlation??0)).map(p=><div className="p8-pair" key={`${p.symbol_a}-${p.symbol_b}`}>
          <b>{p.symbol_a} / {p.symbol_b}</b><span>{corrLabel(p.correlation)}</span><strong>{p.correlation===null?"—":p.correlation.toFixed(3)}</strong>
        </div>)}
      </div>
      <p className="p8-note">{result.note} میانگین قدر مطلق همبستگی صرفاً شاخص توصیفی این مجموعه است و به‌تنهایی ریسک پرتفوی یا تنوع بهینه را اثبات نمی‌کند.</p>
      <small className="p8-updated">آخرین محاسبه: {updatedAt}</small>
    </>}
    {!result&&!loading&&<div className="v11-empty"><BarChart3 size={22}/><span>نمادها را انتخاب کنید تا ماتریس همبستگی محاسبه شود.</span></div>}
    <p className="p8-disclaimer"><AlertTriangle size={14}/> همبستگی تاریخی ثابت نیست و در شرایط پرنوسان تغییر می‌کند. این گزارش توصیه سرمایه‌گذاری یا مجوز اجرای معامله نیست؛ تخصیص سرمایه فعلاً بر اساس همین ماتریس تعدیل نمی‌شود.</p>
  </section>;
}
