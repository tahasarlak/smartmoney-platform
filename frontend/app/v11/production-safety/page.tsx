"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {ShieldCheck,ShieldAlert,Power,RefreshCw,KeyRound,Clock3,FlaskConical} from "lucide-react";
const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";
type Portfolio={id:string;name:string};
type Status={vault_ready:boolean;testnet_order_placement_enabled:boolean;global_kill_switch_enabled:boolean;live_trading_enabled:boolean};
export default function ProductionSafetyPage(){
 const [token,setToken]=useState("");const [portfolios,setPortfolios]=useState<Portfolio[]>([]);
 const [portfolio,setPortfolio]=useState("");const [status,setStatus]=useState<Status|null>(null);
 const [label,setLabel]=useState("Binance Testnet");const [apiKey,setApiKey]=useState("");const [apiSecret,setApiSecret]=useState("");
 const [ack,setAck]=useState(false);const [message,setMessage]=useState("");const [busy,setBusy]=useState(false);
 const [burnin,setBurnin]=useState<any>(null);const [kill,setKill]=useState<any>(null);
 useEffect(()=>{setToken(localStorage.getItem("smartmoney_v11_token")||"")},[]);
 async function request(path:string,method="GET",body?:unknown){
  const r=await fetch(`${API}/api/v1/v11/production${path}`,{method,headers:{"Authorization":`Bearer ${token}`,"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});
  const d=await r.json();if(!r.ok)throw new Error(d.detail?.message||d.detail||`HTTP ${r.status}`);return d;
 }
 async function refresh(){
  if(!token)return;
  try{
   const [s,p]=await Promise.all([
    request("/status"),
    fetch(`${API}/api/v1/v11/portfolios`,{headers:{Authorization:`Bearer ${token}`}}).then(async r=>{const d=await r.json();if(!r.ok)throw new Error("Portfolio loading failed");return d.items||d;})
   ]);
   setStatus(s);setPortfolios(p);if(!portfolio&&p[0])setPortfolio(p[0].id);
   const k=await request("/kill-switch");setKill(k);
   if(portfolio){try{setBurnin(await request(`/scheduler/paper-burnin/status?portfolio_id=${encodeURIComponent(portfolio)}`))}catch{}}
  }catch(e){setMessage(e instanceof Error?e.message:"Could not load safety status")}
 }
 useEffect(()=>{void refresh()},[token,portfolio]);
 async function saveKey(){
  setBusy(true);setMessage("");
  try{
   const d=await request("/exchange/testnet/credentials","POST",{portfolio_id:portfolio,label,api_key:apiKey,api_secret:apiSecret,acknowledge_testnet_only:ack});
   setApiKey("");setApiSecret("");setMessage(`Testnet key verified and stored. Fingerprint: ${d.key_fingerprint}`);await refresh();
  }catch(e){setMessage(e instanceof Error?e.message:"Credential setup failed")}finally{setBusy(false)}
 }
 async function switchOn(){
  setBusy(true);try{const d=await request("/kill-switch/activate?reason=User%20requested%20emergency%20stop","POST");setMessage(`Kill switch active. Cancelled: ${d.cancelled_order_ids.length}; failed: ${d.cancellation_failed_order_ids.length}`);await refresh()}catch(e){setMessage(e instanceof Error?e.message:"Kill switch request failed")}finally{setBusy(false)}
 }
 async function startBurnin(){
  setBusy(true);try{const d=await request("/scheduler/paper-burnin/start","POST",{portfolio_id:portfolio,interval_seconds:900});setMessage(`Paper burn-in scheduled. Job ${d.job_id}`);await refresh()}catch(e){setMessage(e instanceof Error?e.message:"Scheduler setup failed")}finally{setBusy(false)}
 }
 return <main className="pSafe"><header><Link href="/v11">TRADF / V11</Link><span> / Production Safety</span></header>
  <section className="pSafeHero"><span>PRODUCTION INFRASTRUCTURE · TESTNET ONLY</span><h1>امنیت و زیرساخت اجرای کنترل‌شده</h1><p>این پنل برای اتصال Binance Spot Testnet، کلید رمزنگاری‌شده، توقف اضطراری و آزمایش مداوم است. معامله زنده فعال نیست.</p></section>
  {!token?<p className="pSafeAlert">ابتدا وارد حساب TRADF شوید.</p>:null}
  <section className="pSafeGrid">
   <article><ShieldCheck/><span>Vault</span><b>{status?.vault_ready?"Encryption configured":"Encryption key missing"}</b></article>
   <article><FlaskConical/><span>Exchange</span><b>Binance Spot Testnet</b></article>
   <article><Power/><span>Global Kill Switch</span><b>{status?.global_kill_switch_enabled?"ENABLED":"DISABLED"}</b></article>
   <article><ShieldAlert/><span>Live Trading</span><b>DISABLED</b></article>
  </section>
  <section className="pSafeCard"><h2><KeyRound/> اتصال API آزمایشی</h2>
   <label>پرتفوی<select value={portfolio} onChange={e=>setPortfolio(e.target.value)}>{portfolios.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
   <label>نام اتصال<input value={label} onChange={e=>setLabel(e.target.value)}/></label>
   <label>Binance Testnet API Key<input autoComplete="off" value={apiKey} onChange={e=>setApiKey(e.target.value)} /></label>
   <label>Binance Testnet Secret<input type="password" autoComplete="new-password" value={apiSecret} onChange={e=>setApiSecret(e.target.value)}/></label>
   <label className="pSafeCheck"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/> تأیید می‌کنم این کلید فقط برای Testnet است و مجوز برداشت ندارد.</label>
   <button disabled={busy||!token||!portfolio||!ack||!apiKey||!apiSecret} onClick={()=>void saveKey()}>{busy?"در حال بررسی…":"اعتبارسنجی و ذخیره رمزنگاری‌شده"}</button>
   <small>کلیدها پس از ذخیره دوباره نمایش داده نمی‌شوند. کلید حساب اصلی صرافی را وارد نکنید.</small>
  </section>
  <section className="pSafeCard"><h2><Power/> توقف اضطراری</h2><p>فعال‌سازی، ثبت سفارش‌های جدید را متوقف می‌کند و برای سفارش‌های باز Testnet درخواست لغو می‌فرستد. دارایی‌هایی که قبلاً پر شده‌اند را نمی‌فروشد یا نمی‌بندد. در صورت خطای صرافی، وضعیت لغو باید در پنل صرافی بررسی شود.</p><button className="pSafeDanger" disabled={busy||!token} onClick={()=>void switchOn()}>فعال‌سازی Kill Switch</button><small>خاموش‌کردن Kill Switch نیازمند تأیید دستی از API است. Kill Switch سراسری با تنظیمات سرور کنترل می‌شود.</small></section>
  <section className="pSafeCard"><h2><Clock3/> آزمایش پایدار ۲۱ روزه</h2><p>برای جمع‌آوری نمونه‌های Paper Trading، Worker ابری باید فعال باشد.</p><div className="pSafeStats"><b>{burnin?.sample_count??0} <small>نمونه</small></b><b>{burnin?.observation_days??0} <small>روز مشاهده</small></b><b>{burnin?.status??"شروع نشده"}</b></div><button disabled={busy||!portfolio} onClick={()=>void startBurnin()}>شروع / ادامه آزمایش</button><small>تکمیل ۲۱ روز فقط شرط بررسی است، نه تضمین سود یا مجوز معامله زنده.</small></section>
  {message?<p className="pSafeAlert">{message}</p>:null}
  <button className="pSafeRefresh" onClick={()=>void refresh()}><RefreshCw size={15}/> بروزرسانی وضعیت</button>
  <footer>TRADF · SAFETY FIRST · LIVE EXECUTION DISABLED</footer>
 </main>
}
