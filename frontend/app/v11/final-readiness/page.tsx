"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ShieldAlert, RefreshCw, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Report = {
  status: string; release_decision: string; blockers: string[];
  gates: {gate:string;passed:boolean}[];
  lifecycle: {status:string}; burn_in: {status:string; integrity_issue_count:number; window_event_count:number};
  security: {status:string; missing_controls:string[]};
  operations: {status:string; blockers:string[]};
  live_trading_enabled: boolean; limitations: string[];
};

export default function FinalReadinessPage() {
  const [token,setToken]=useState("");
  const [portfolio,setPortfolio]=useState("");
  const [portfolios,setPortfolios]=useState<{id:string;name:string}[]>([]);
  const [report,setReport]=useState<Report|null>(null);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{setToken(localStorage.getItem("smartmoney_v11_token")||"");},[]);
  useEffect(()=>{if(!token)return; (async()=>{try{
    const r=await fetch(`${API}/api/v1/v11/portfolios`,{headers:{Authorization:`Bearer ${token}`}});
    const d=await r.json(); if(!r.ok)throw new Error(d.detail||"Portfolio request failed");
    const rows=d.items||d; setPortfolios(rows); if(rows[0])setPortfolio(rows[0].id);
  }catch(e){setError(e instanceof Error?e.message:"Could not load portfolios");}})();},[token]);
  async function run(){
    if(!token||!portfolio)return;
    setBusy(true);setError("");
    try{
      const r=await fetch(`${API}/api/v1/v11/portfolios/${encodeURIComponent(portfolio)}/final-readiness`,{headers:{Authorization:`Bearer ${token}`}});
      const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);
      setReport(d);
    }catch(e){setError(e instanceof Error?e.message:"Readiness check failed");}
    finally{setBusy(false);}
  }
  useEffect(()=>{if(portfolio)void run();},[portfolio]);
  return <main className="p39-shell">
    <header><Link href="/v11">TRADF / V11</Link><span> / Final Readiness Audit</span></header>
    <section className="p39-hero"><span>PHASE 39 · FINAL RELEASE GATE</span><h1>ممیزی آمادگی انتشار TRADF</h1>
      <p>این گزارش وضعیت دیتابیس، چرخه معاملات آزمایشی، Burn-in، امنیت و عملیات را بررسی می‌کند. این صفحه مجوز معامله زنده صادر نمی‌کند.</p>
      <label>پرتفوی<select value={portfolio} onChange={e=>setPortfolio(e.target.value)}>{portfolios.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <button onClick={()=>void run()} disabled={busy||!portfolio}><RefreshCw size={16}/>{busy?"در حال بررسی…":"اجرای ممیزی مجدد"}</button>
    </section>
    {!token&&<p className="p39-warning">برای مشاهده گزارش ابتدا وارد TRADF شوید.</p>}
    {error&&<p className="p39-warning"><AlertTriangle size={16}/>{error}</p>}
    {report&&<>
      <section className="p39-verdict"><ShieldAlert size={24}/><div><b>{report.status==="paper_release_candidate"?"آماده بررسی برای انتشار Paper":"هنوز آماده انتشار نیست"}</b><span>{report.release_decision}</span></div><strong>LIVE OFF</strong></section>
      <section className="p39-summary"><article><span>Lifecycle</span><b>{report.lifecycle.status}</b></article><article><span>Burn-in</span><b>{report.burn_in.status}</b></article><article><span>مغایرت‌ها</span><b>{report.burn_in.integrity_issue_count}</b></article><article><span>Operations</span><b>{report.operations.status}</b></article></section>
      <section className="p39-card"><h2>دروازه‌های انتشار</h2>{report.gates.map(g=><div className="p39-gate" key={g.gate}>{g.passed?<CheckCircle2 size={17}/>:<XCircle size={17}/>}<span>{g.gate}</span><b>{g.passed?"PASS":"BLOCKED"}</b></div>)}</section>
      <section className="p39-card"><h2>موانع انتشار</h2>{report.blockers.length?report.blockers.map(x=><p key={x}>• {x}</p>):<p>موانعی در چک‌لیست ثبت نشده است؛ این موضوع همچنان مجوز معامله زنده نیست.</p>}</section>
      <section className="p39-card"><h2>محدودیت‌ها</h2><ul>{report.limitations.map((x,i)=><li key={i}>{x}</li>)}</ul></section>
    </>}
    <footer>TRADF · FINAL AUDIT · PAPER MODE · LIVE TRADING DISABLED</footer>
  </main>;
}
