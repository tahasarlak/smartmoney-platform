"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

type Candidate = {
  symbol: string;
  direction: "long" | "short";
  entry: string;
  stop: string;
  quality_score: string;
  correlation_group: string;
};
type RiskSnapshot = {
  equity: number;
  position_count: number;
  total_open_risk_cash: number;
  total_open_risk_pct: number;
  gross_notional: number;
  gross_notional_pct_of_equity: number;
  remaining_risk_budget_cash: number;
  remaining_position_slots: number;
  risk_limit_pct: number;
  per_trade_limit_pct: number;
  status: "healthy" | "warning" | "blocked";
  blockers: string[];
  warnings: string[];
  risk_by_symbol: Record<string, {risk_cash:number; risk_pct:number}>;
};
type Allocation = {
  symbol: string; direction: string; entry: number; stop: number;
  quality_score: number; risk_cash: number; risk_pct: number;
  quantity: number; notional: number; correlation_group: string;
};
type AllocationResult = {
  equity: number; budget_cash: number; allocated_risk_cash?: number;
  unallocated_risk_cash?: number; allocations: Allocation[];
  rejected: {symbol?:string;reason:string}[];
  allocation_method?: string; execution_allowed: false; note?: string;
};

const blank = (): Candidate => ({
  symbol: "", direction: "long", entry: "", stop: "", quality_score: "70", correlation_group: ""
});
const money = (v:number) => new Intl.NumberFormat("en-US",{maximumFractionDigits:2}).format(Number.isFinite(v)?v:0);

export default function CapitalAllocator({token, portfolioId}:{token:string;portfolioId:string}) {
  const [risk,setRisk] = useState<RiskSnapshot|null>(null);
  const [rows,setRows] = useState<Candidate[]>([blank()]);
  const [budget,setBudget] = useState("");
  const [result,setResult] = useState<AllocationResult|null>(null);
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");

  const request = useCallback(async (path:string, init:RequestInit={}) => {
    const headers = new Headers(init.headers || {});
    headers.set("Content-Type","application/json");
    headers.set("Authorization",`Bearer ${token}`);
    const response = await fetch(`${API}${path}`,{...init,headers,cache:"no-store"});
    const body = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(body.detail || `API ${response.status}`);
    return body;
  },[token]);

  const loadRisk = useCallback(async () => {
    if (!token || !portfolioId) { setRisk(null); return; }
    setLoading(true); setError("");
    try {
      const data = await request(`/api/v1/v11/portfolios/${encodeURIComponent(portfolioId)}/risk`);
      setRisk(data);
      setBudget(String(data.risk_limit_pct ?? ""));
    } catch(e) {
      setError(e instanceof Error ? e.message : "Could not load portfolio risk");
    } finally { setLoading(false); }
  },[token,portfolioId,request]);

  useEffect(()=>{void loadRisk();setResult(null);},[loadRisk]);

  function update(index:number,key:keyof Candidate,value:string) {
    setRows(current=>current.map((row,i)=>i===index?{...row,[key]:value}:row));
  }
  function addRow() {
    if (rows.length < 10) setRows(current=>[...current,blank()]);
  }
  function removeRow(index:number) {
    setRows(current=>current.length===1?current:current.filter((_,i)=>i!==index));
  }
  async function calculate(e:React.FormEvent) {
    e.preventDefault(); setError(""); setNotice(""); setResult(null);
    if (!portfolioId) { setError("ابتدا یک پرتفوی انتخاب کنید."); return; }
    const candidates = rows.map(r=>({
      symbol:r.symbol.trim().toUpperCase(),
      direction:r.direction,
      entry:Number(r.entry),
      stop:Number(r.stop),
      quality_score:Number(r.quality_score),
      correlation_group:r.correlation_group.trim() || null
    }));
    if (candidates.some(c=>!c.symbol || !Number.isFinite(c.entry) || c.entry<=0 || !Number.isFinite(c.stop) || c.stop<=0 || !Number.isFinite(c.quality_score))) {
      setError("اطلاعات تمام کاندیداها را با مقادیر معتبر تکمیل کنید."); return;
    }
    setLoading(true);
    try {
      const payload:any={candidates};
      if (budget.trim()) payload.requested_budget_pct=Number(budget);
      const data=await request(`/api/v1/v11/portfolios/${encodeURIComponent(portfolioId)}/risk/allocate`,{
        method:"POST",body:JSON.stringify(payload)
      });
      setResult(data);
      setNotice("محاسبه تخصیص انجام شد؛ هیچ معامله‌ای ایجاد یا اجرا نشده است.");
    } catch(e) {
      setError(e instanceof Error ? e.message : "Allocation calculation failed");
    } finally { setLoading(false); }
  }

  return <section id="capital-allocation" className="p7-allocator card">
    <div className="p7-head">
      <div><span className="v11-eyebrow">PHASE 7 · CAPITAL INTELLIGENCE</span>
        <h2><Activity size={18}/> تخصیص هوشمند سرمایه</h2>
        <p className="muted">بودجه ریسک آزاد پرتفوی را بین کاندیداها، بر اساس امتیاز کیفیت و سقف ریسک هر معامله تقسیم می‌کند.</p>
      </div>
      <button type="button" className="v11-iconbtn" onClick={()=>void loadRisk()} disabled={loading} title="به‌روزرسانی ریسک"><RefreshCw size={16}/></button>
    </div>
    {!portfolioId && <div className="v11-error">برای استفاده از تخصیص سرمایه، یک پرتفوی انتخاب کنید.</div>}
    {error && <div className="v11-error">{error}</div>}
    {notice && <div className="v11-success">{notice}</div>}
    {risk && <>
      <div className="p7-metrics">
        <div><small>ارزش فعلی پرتفوی</small><b>{money(risk.equity)} USDT</b></div>
        <div><small>ریسک باز فعلی</small><b>{money(risk.total_open_risk_cash)} USDT · {risk.total_open_risk_pct.toFixed(2)}٪</b></div>
        <div><small>بودجه ریسک باقی‌مانده</small><b>{money(risk.remaining_risk_budget_cash)} USDT</b></div>
        <div><small>ظرفیت موقعیت جدید</small><b>{risk.remaining_position_slots}</b></div>
      </div>
      <div className={`p7-risk-state ${risk.status}`}>
        {risk.status==="healthy"?<ShieldCheck size={17}/>:<AlertTriangle size={17}/>}
        <div><b>{risk.status==="healthy"?"وضعیت ریسک سالم":risk.status==="warning"?"نزدیک‌شدن به سقف ریسک":"محدودیت ریسک فعال است"}</b>
          <small>سقف ریسک کل: {risk.risk_limit_pct}% · سقف هر معامله: {risk.per_trade_limit_pct}% · موقعیت‌های باز: {risk.position_count}</small>
        </div>
      </div>
      {risk.blockers?.length>0&&<ul className="p7-warning-list">{risk.blockers.map((x,i)=><li key={i}>{x}</li>)}</ul>}
      {risk.warnings?.length>0&&<ul className="p7-warning-list">{risk.warnings.map((x,i)=><li key={i}>{x}</li>)}</ul>}
    </>}
    <form onSubmit={calculate} className="p7-form">
      <div className="p7-form-head"><h3>کاندیداهای تخصیص</h3><button type="button" className="v11-link" onClick={addRow} disabled={rows.length>=10}><Plus size={14}/> افزودن کاندیدا</button></div>
      {rows.map((row,i)=><div className="p7-candidate" key={i}>
        <div className="p7-candidate-title"><b>کاندیدا {i+1}</b><button type="button" className="v11-iconbtn" onClick={()=>removeRow(i)} disabled={rows.length===1} aria-label="حذف کاندیدا"><Trash2 size={14}/></button></div>
        <div className="p7-fields">
          <label>نماد<input value={row.symbol} onChange={e=>update(i,"symbol",e.target.value.toUpperCase())} placeholder="BTCUSDT" required maxLength={40}/></label>
          <label>جهت<select value={row.direction} onChange={e=>update(i,"direction",e.target.value as Candidate["direction"])}><option value="long">Long</option><option value="short">Short</option></select></label>
          <label>قیمت ورود<input type="number" min="0.00000001" step="any" value={row.entry} onChange={e=>update(i,"entry",e.target.value)} required/></label>
          <label>حد ضرر<input type="number" min="0.00000001" step="any" value={row.stop} onChange={e=>update(i,"stop",e.target.value)} required/></label>
          <label>امتیاز کیفیت<input type="number" min="0" max="100" step="1" value={row.quality_score} onChange={e=>update(i,"quality_score",e.target.value)} required/></label>
          <label>گروه همبستگی (اختیاری)<input value={row.correlation_group} onChange={e=>update(i,"correlation_group",e.target.value)} placeholder="مثلاً BTC ecosystem"/></label>
        </div>
      </div>)}
      <div className="p7-budget"><label>بودجه درخواستی ریسک (% از سرمایه)<input type="number" min="0.01" max={risk?.risk_limit_pct || 100} step="0.01" value={budget} onChange={e=>setBudget(e.target.value)}/></label>
        <small>این مقدار نباید از سقف ریسک کل پرتفوی بیشتر باشد.</small>
      </div>
      <button className="btn" disabled={loading || !portfolioId}>{loading?"در حال محاسبه…":"محاسبه تخصیص سرمایه"}</button>
    </form>
    {result && <div className="p7-results">
      <div className="p7-result-head"><h3>نتیجه تخصیص</h3><span className="v11-badge">محاسباتی · بدون اجرا</span></div>
      <div className="p7-metrics">
        <div><small>بودجه ریسک</small><b>{money(result.budget_cash)} USDT</b></div>
        <div><small>ریسک تخصیص‌یافته</small><b>{money(result.allocated_risk_cash||0)} USDT</b></div>
        <div><small>ریسک تخصیص‌نیافته</small><b>{money(result.unallocated_risk_cash||0)} USDT</b></div>
        <div><small>تعداد تخصیص‌ها</small><b>{result.allocations.length}</b></div>
      </div>
      {result.allocations.length>0?<div className="v11-tablewrap"><table className="v11-table"><thead><tr><th>نماد</th><th>جهت</th><th>حجم پیشنهادی</th><th>ارزش اسمی</th><th>ریسک نقدی</th><th>ریسک %</th></tr></thead><tbody>{result.allocations.map((a,i)=><tr key={`${a.symbol}-${i}`}><td><b>{a.symbol}</b><small>Quality {a.quality_score}</small></td><td>{a.direction.toUpperCase()}</td><td>{a.quantity}</td><td>{money(a.notional)}</td><td>{money(a.risk_cash)}</td><td>{a.risk_pct.toFixed(3)}٪</td></tr>)}</tbody></table></div>:<div className="v11-empty">با توجه به بودجه و ظرفیت فعلی، تخصیصی انجام نشد.</div>}
      {result.rejected.length>0&&<div className="p7-rejected"><b>موارد ردشده</b>{result.rejected.map((x,i)=><p key={i}>{x.symbol||"—"}: {x.reason}</p>)}</div>}
      {result.note&&<p className="p7-note">{result.note}</p>}
      <p className="p7-disclaimer">این خروجی پیشنهاد محاسباتی بر اساس امتیاز کیفیت و محدودیت ریسک است؛ همبستگی واقعی در این تخصیص اعمال نشده و هیچ سفارش یا پوزیشن جدیدی ثبت نشده است.</p>
    </div>}
  </section>;
}
