"use client";
import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, ColorType, type IChartApi } from "lightweight-charts";
import { Activity, CandlestickChart, Plus, RefreshCw, Trash2, Wifi, WifiOff, Zap } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Candle = {time:number;open:number;high:number;low:number;close:number;volume:number};
type Analysis = {structure:string;directional_bias:string;quality_score:number;estimated_win_probability:number|null;probability_status:string;events:any[];zones:any[];last_price:number;disclaimer:string};
type LivePrice = {symbol:string;price:number;event_time:string;event_time_ms:number};

function MarketChart({data}:{data:Candle[]}) {
  const host=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!host.current || !data.length) return;
    const c=createChart(host.current,{layout:{background:{type:ColorType.Solid,color:"#0b1422"},textColor:"#8291a8"},grid:{vertLines:{color:"#172438"},horzLines:{color:"#172438"}},rightPriceScale:{borderColor:"#26364d"},timeScale:{borderColor:"#26364d",timeVisible:true},height:390});
    const s=c.addSeries(CandlestickSeries,{upColor:"#31d69a",downColor:"#ff647c",borderVisible:false,wickUpColor:"#31d69a",wickDownColor:"#ff647c"});
    s.setData(data.map(x=>({time:x.time as any,open:x.open,high:x.high,low:x.low,close:x.close})));
    c.timeScale().fitContent();
    const resize=()=>{if(host.current)c.applyOptions({width:host.current.clientWidth});};
    window.addEventListener("resize",resize); resize();
    return()=>{window.removeEventListener("resize",resize);c.remove();};
  },[data]);
  return <div ref={host} className="chartWrap"/>;
}

export default function Home(){
  const [symbol,setSymbol]=useState("BTCUSDT"),[interval,setInterval]=useState("15m");
  const [candles,setCandles]=useState<Candle[]>([]),[analysis,setAnalysis]=useState<Analysis|null>(null);
  const [loading,setLoading]=useState(false),[error,setError]=useState("");
  const [status,setStatus]=useState<any>(null),[prices,setPrices]=useState<LivePrice[]>([]);
  const [watchlist,setWatchlist]=useState<string[]>([]),[newSymbol,setNewSymbol]=useState("");
  const [monitorError,setMonitorError]=useState(""),[busy,setBusy]=useState(false);
  const [v8Status,setV8Status]=useState<any>(null),[v8Latest,setV8Latest]=useState<any>(null);
  const [v8Busy,setV8Busy]=useState(false),[v8Error,setV8Error]=useState("");


  async function scan(){
    setLoading(true);setError("");
    try{
      const m=await fetch(`${API}/api/v1/market/binance/klines`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({symbol,interval,limit:300})});
      if(!m.ok)throw new Error(`Market data: ${m.status} ${await m.text()}`);
      const md=await m.json();setCandles(md.candles);
      const a=await fetch(`${API}/api/v1/analysis/smc`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({symbol,candles:md.candles,swing_length:3,equal_level_tolerance_pct:0.05})});
      if(!a.ok)throw new Error(`Analysis: ${a.status} ${await a.text()}`);
      setAnalysis(await a.json());
    }catch(e:any){setError(e.message||"Could not load market data");}finally{setLoading(false);}
  }

  async function refreshMonitor(){
    try{
      const [s,p,w]=await Promise.all([
        fetch(`${API}/api/v1/monitor/live-price/status`,{cache:"no-store"}),
        fetch(`${API}/api/v1/monitor/live-price/market`,{cache:"no-store"}),
        fetch(`${API}/api/v1/monitor/live-price/watchlist`,{cache:"no-store"})
      ]);
      if(!s.ok||!p.ok||!w.ok)throw new Error("Live monitor API unavailable");
      const sd=await s.json(),pd=await p.json(),wd=await w.json();
      setStatus(sd);setPrices(pd.prices||[]);setWatchlist(wd.symbols||[]);setMonitorError("");
    }catch(e:any){setMonitorError(e.message||"Monitor error");}
  }

  async function changeWatchlist(value:string,method:"POST"|"DELETE"){
    setBusy(true);setMonitorError("");
    try{
      const r=await fetch(`${API}/api/v1/monitor/live-price/watchlist/${encodeURIComponent(value)}`,{method});
      const body=await r.json();
      if(!r.ok)throw new Error(body.detail||`Request failed: ${r.status}`);
      setWatchlist(body.symbols||[]);setNewSymbol("");await refreshMonitor();
    }catch(e:any){setMonitorError(e.message||"Watchlist update failed");}
    finally{setBusy(false);}
  }

  function v8Symbols(){
    return Array.from(new Set([...(status?.symbols||[]),...watchlist,symbol].map((x:string)=>String(x).toUpperCase()))).slice(0,30);
  }

  async function refreshV8(){
    try{
      const [s,l]=await Promise.all([
        fetch(`${API}/api/v1/intelligence/v8/status`,{cache:"no-store"}),
        fetch(`${API}/api/v1/intelligence/v8/latest`,{cache:"no-store"})
      ]);
      if(!s.ok||!l.ok)throw new Error("V8 API unavailable");
      const sd=await s.json(),ld=await l.json();
      setV8Status(sd);setV8Latest(ld.result||null);setV8Error("");
    }catch(e:any){setV8Error(e.message||"V8 status error");}
  }

  async function runV8Scan(){
    setV8Busy(true);setV8Error("");
    try{
      const r=await fetch(`${API}/api/v1/intelligence/v8/scan`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({symbols:v8Symbols(),limit:300,persist_signals:false})
      });
      const body=await r.json();
      if(!r.ok)throw new Error(body.detail||`V8 scan failed: ${r.status}`);
      setV8Latest(body);await refreshV8();
    }catch(e:any){setV8Error(e.message||"V8 scan failed");}
    finally{setV8Busy(false);}
  }

  async function startV8(){
    setV8Busy(true);setV8Error("");
    try{
      const r=await fetch(`${API}/api/v1/intelligence/v8/start`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({symbols:v8Symbols(),limit:300,interval_seconds:60,persist_signals:true})
      });
      const body=await r.json();
      if(!r.ok)throw new Error(body.detail||`V8 start failed: ${r.status}`);
      await refreshV8();
    }catch(e:any){setV8Error(e.message||"V8 start failed");}
    finally{setV8Busy(false);}
  }

  async function stopV8(){
    setV8Busy(true);setV8Error("");
    try{
      const r=await fetch(`${API}/api/v1/intelligence/v8/stop`,{method:"POST"});
      const body=await r.json();
      if(!r.ok)throw new Error(body.detail||`V8 stop failed: ${r.status}`);
      await refreshV8();
    }catch(e:any){setV8Error(e.message||"V8 stop failed");}
    finally{setV8Busy(false);}
  }

  useEffect(()=>{
    void scan();void refreshMonitor();void refreshV8();
    const timer=window.setInterval(()=>void refreshMonitor(),2000);
    const v8Timer=window.setInterval(()=>void refreshV8(),5000);
    return()=>{window.clearInterval(timer);window.clearInterval(v8Timer);};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);

  const events=analysis?.events||[],zones=analysis?.zones||[];
  return <main className="shell">
    <header className="topbar"><div className="brand"><div className="brandmark">SM</div><div>SMARTMONEY <span style={{color:"#6ca8ff"}}>INTELLIGENCE</span><div className="muted small" style={{letterSpacing:".18em",fontWeight:500}}>TRADING RESEARCH TERMINAL</div></div></div><div style={{display:"flex",gap:9,alignItems:"center"}}><span className="pill online">● API WORKSPACE</span><span className="pill">PAPER MODE</span><a className="v11-navlink" href="/v11">V11 WORKSPACE ↗</a></div></header>
    <div className="heading"><div><h1>Market overview</h1><div className="muted small">Multi-timeframe research · rule-based SMC engine · live public crypto candles</div></div><button className="btn" onClick={scan} disabled={loading}><Zap size={14} style={{display:"inline",marginRight:7}}/>{loading?"Scanning...":"Run market scan"}</button></div>

    <section className="grid stats">
      <div className="card"><div className="statlabel">Selected instrument</div><div className="statvalue mono">{symbol}</div><div className="muted small">Binance public feed</div></div>
      <div className="card"><div className="statlabel">Market structure</div><div className="statvalue" style={{fontSize:20}}>{analysis?.structure?.toUpperCase()||"—"}</div><div className="muted small">Current timeframe: {interval}</div></div>
      <div className="card"><div className="statlabel">Setup quality</div><div className="statvalue">{analysis?`${analysis.quality_score}/100`:"—"}</div><div className="muted small">Heuristic score, not win probability</div></div>
      <div className="card"><div className="statlabel">Estimated win probability</div><div className="statvalue">N/A</div><div className="muted small">Requires validated out-of-sample calibration</div></div>
    </section>
    {error&&<div className="notice" style={{marginBottom:14}}>Connection / analysis error: {error}</div>}

    <section className="card" style={{marginBottom:16}}>
      <div className="cardhead"><div><h2><Activity size={16} style={{display:"inline",marginRight:8,verticalAlign:"middle"}}/>Live market monitor</h2><div className="muted small" style={{marginTop:5}}>Binance WebSocket · runtime watchlist · latest trade prices</div></div>
        <div style={{display:"flex",gap:8,alignItems:"center"}}>{status?.connected?<span className="tag" style={{color:"#31d69a"}}><Wifi size={13} style={{display:"inline",marginRight:5}}/>CONNECTED</span>:<span className="tag warn"><WifiOff size={13} style={{display:"inline",marginRight:5}}/>DISCONNECTED</span>}<button className="btn" onClick={refreshMonitor}><RefreshCw size={14}/></button></div>
      </div>
      <div className="grid stats" style={{marginTop:12}}>
        <div><div className="statlabel">Messages received</div><div className="statvalue mono">{(status?.messages_received||0).toLocaleString()}</div></div>
        <div><div className="statlabel">Tracked symbols</div><div className="statvalue mono">{status?.symbols?.length||0}</div></div>
        <div><div className="statlabel">Cached prices</div><div className="statvalue mono">{status?.cached_prices||0}</div></div>
        <div><div className="statlabel">Signals updated</div><div className="statvalue mono">{status?.signals_updated||0}</div></div>
      </div>
      <div style={{display:"flex",gap:8,flexWrap:"wrap",margin:"18px 0 12px"}}>
        <input className="select" value={newSymbol} onChange={e=>setNewSymbol(e.target.value.toUpperCase())} onKeyDown={e=>{if(e.key==="Enter"&&newSymbol.trim())void changeWatchlist(newSymbol.trim(),"POST");}} placeholder="مثلاً ETHUSDT" aria-label="New Binance symbol" style={{minWidth:180}}/>
        <button className="btn" disabled={busy||!newSymbol.trim()} onClick={()=>void changeWatchlist(newSymbol.trim(),"POST")}><Plus size={14} style={{display:"inline",marginRight:6}}/>Add symbol</button>
      </div>
      {monitorError&&<div className="notice" style={{marginBottom:12}}>{monitorError}</div>}
      <h3 className="sectionTitle">Watchlist</h3>
      {watchlist.length?<div style={{display:"flex",gap:8,flexWrap:"wrap",margin:"10px 0 18px"}}>{watchlist.map(x=><div key={x} className="pill" style={{display:"flex",gap:8,alignItems:"center",padding:"8px 10px"}}><span className="mono">{x}</span><button onClick={()=>void changeWatchlist(x,"DELETE")} disabled={busy} title={`Remove ${x}`} style={{border:0,background:"transparent",color:"#ff647c",cursor:"pointer",padding:0,display:"inline-flex"}}><Trash2 size={14}/></button></div>)}</div>:<div className="muted small" style={{margin:"10px 0 18px"}}>No manually added symbols. Environment symbols and active journal signals may still be monitored.</div>}
      <h3 className="sectionTitle">Latest prices</h3>
      {prices.length?<div style={{overflowX:"auto",marginTop:8}}><table style={{width:"100%",borderCollapse:"collapse"}}><thead><tr className="muted small" style={{textAlign:"left"}}><th style={{padding:9}}>Symbol</th><th style={{padding:9}}>Last price</th><th style={{padding:9}}>Exchange time</th></tr></thead><tbody>{prices.map(x=><tr key={x.symbol} style={{borderTop:"1px solid #26364d"}}><td className="mono" style={{padding:10}}>{x.symbol}</td><td className="mono" style={{padding:10}}>{x.price.toLocaleString(undefined,{maximumFractionDigits:8})}</td><td className="muted small" style={{padding:10}}>{new Date(x.event_time).toLocaleTimeString()}</td></tr>)}</tbody></table></div>:<div className="muted small" style={{marginTop:8}}>Waiting for the first Binance trade tick...</div>}
      <div className="notice" style={{marginTop:14}}>Live order execution is disabled. Watchlist and cached prices are stored in memory and reset when the backend restarts.</div>
    </section>

    <section className="card" style={{marginBottom:16}}>
      <div className="cardhead">
        <div><h2><Zap size={16} style={{display:"inline",marginRight:8,verticalAlign:"middle"}}/>V8 Signal Intelligence</h2>
          <div className="muted small" style={{marginTop:5}}>4H · 1H · 15M · 5M · 1M · research-only signals</div>
        </div>
        <span className={v8Status?.running?"tag":"tag warn"}>{v8Status?.running?"AUTO SCAN RUNNING":"SCANNER IDLE"}</span>
      </div>
      <div style={{display:"flex",gap:8,flexWrap:"wrap",marginTop:14}}>
        <button className="btn" onClick={runV8Scan} disabled={v8Busy}>{v8Busy?"Working...":"Scan now"}</button>
        <button className="btn" onClick={startV8} disabled={v8Busy||v8Status?.running}>Start auto scan</button>
        <button className="btn" onClick={stopV8} disabled={v8Busy||!v8Status?.running}>Stop auto scan</button>
      </div>
      <div className="grid stats" style={{marginTop:14}}>
        <div><div className="statlabel">Completed scans</div><div className="statvalue mono">{v8Status?.scans_completed||0}</div></div>
        <div><div className="statlabel">Opportunities</div><div className="statvalue mono">{v8Latest?.summary?.opportunities||0}</div></div>
        <div><div className="statlabel">Ready for review</div><div className="statvalue mono">{v8Latest?.summary?.ready_for_review||0}</div></div>
        <div><div className="statlabel">Journaled</div><div className="statvalue mono">{v8Latest?.summary?.journaled||0}</div></div>
      </div>
      {v8Error&&<div className="notice" style={{marginTop:12}}>{v8Error}</div>}
      <div className="muted small" style={{marginTop:10}}>Symbols: {v8Symbols().join(", ")||"none"} · Last scan: {v8Status?.last_scan_at?new Date(v8Status.last_scan_at).toLocaleString():"not yet"} · Win probability is not calibrated.</div>
      {(v8Latest?.opportunities||[]).length?
        <div style={{display:"grid",gap:10,marginTop:14}}>
          {v8Latest.opportunities.slice(0,10).map((item:any,index:number)=>{
            const p=item.plan;
            return <div key={`${item.symbol}-${item.direction}-${index}`} className="zone" style={{display:"block",padding:12}}>
              <div style={{display:"flex",justifyContent:"space-between",gap:12,flexWrap:"wrap"}}>
                <strong className="mono">{item.symbol} · {String(item.direction).toUpperCase()}</strong>
                <span className="tag">{item.signal_state||item.state} · {item.quality_score}/100</span>
              </div>
              {p&&<div className="analysisList" style={{marginTop:8}}>
                <div className="analysisRow"><span>Entry / Stop</span><strong className="mono">{p.entry} / {p.stop_loss}</strong></div>
                <div className="analysisRow"><span>TP1 / TP2 / TP3</span><strong className="mono">{p.take_profits.map((t:any)=>t.price).join(" / ")}</strong></div>
              </div>}
              <div className="muted small" style={{marginTop:7}}>{(item.reasons||[]).join(" · ")}</div>
              {item.journal?.duplicate&&<div className="muted small">Existing active signal already journaled.</div>}
              {item.journal?.saved&&<div className="muted small">Saved to signal journal.</div>}
            </div>;
          })}
        </div>
      :<div className="muted small" style={{marginTop:14}}>No valid zone-based opportunities in the latest scan. The scanner can still report developing/watchlist scenarios in its API response.</div>}
      <div className="notice" style={{marginTop:14}}>Auto scan only creates research journal entries for confirmed triggers above the configured quality threshold. It never sends broker orders. Risk of loss remains; quality score is not win probability.</div>
    </section>

    <section className="grid mainGrid">
      <div className="card"><div className="cardhead"><div><h2><CandlestickChart size={16} style={{display:"inline",marginRight:8,verticalAlign:"middle"}}/>Price action</h2><div className="muted small" style={{marginTop:5}}>Candlesticks from public market data</div></div><div style={{display:"flex",gap:8}}><select className="select" value={symbol} onChange={e=>setSymbol(e.target.value)}><option>BTCUSDT</option><option>ETHUSDT</option><option>BNBUSDT</option><option>SOLUSDT</option><option>XRPUSDT</option></select><select className="select" value={interval} onChange={e=>setInterval(e.target.value)}><option>1m</option><option>5m</option><option>15m</option><option>1h</option><option>4h</option><option>1d</option></select></div></div>{candles.length?<MarketChart data={candles}/>:<div className="chartPlaceholder">{loading?"Loading market candles...":"Run scan to load chart"}</div>}</div>
      <div className="card"><div className="cardhead"><h2><Activity size={16} style={{display:"inline",marginRight:8,verticalAlign:"middle"}}/>Analysis engine</h2><span className="tag">RULE BASED</span></div><div className="analysisList"><div className="analysisRow"><span>Directional bias</span><strong>{analysis?.directional_bias?.toUpperCase()||"—"}</strong></div><div className="analysisRow"><span>Last price</span><strong className="mono">{analysis?.last_price?.toLocaleString()||"—"}</strong></div><div className="analysisRow"><span>Detected events</span><strong>{events.length}</strong></div><div className="analysisRow"><span>Detected zones</span><strong>{zones.length}</strong></div><div className="analysisRow"><span>Win probability</span><span className="tag warn">NOT CALIBRATED</span></div></div><div className="notice" style={{marginTop:14}}>{analysis?.disclaimer||"Analysis will appear after the first scan. No trade is executed by this dashboard."}</div></div>
    </section>
    <section className="grid bottomGrid">
      <div className="card"><h3 className="sectionTitle">Market events</h3>{events.length?events.slice(-8).reverse().map((e,i)=><div className="zone" key={i}><span>{e.type} · {e.direction}</span><strong className="mono">{Number(e.level).toFixed(4)}</strong></div>):<div className="muted small">No qualifying events detected on this scan.</div>}</div>
      <div className="card"><h3 className="sectionTitle">Smart money zones</h3>{zones.length?zones.slice(-8).reverse().map((z,i)=><div className="zone" key={i}><span>{z.type} · {z.direction}</span><strong className="mono">{z.low.toFixed(4)}–{z.high.toFixed(4)}</strong></div>):<div className="muted small">No zones detected on this scan.</div>}</div>
      <div className="card"><h3 className="sectionTitle">Execution & risk</h3><div className="analysisList"><div className="analysisRow"><span>Execution mode</span><span className="tag warn">PAPER ONLY</span></div><div className="analysisRow"><span>Live trading</span><span className="tag bad">DISABLED</span></div><div className="analysisRow"><span>Risk engine</span><span className="tag">API AVAILABLE</span></div></div><p className="muted small">Position sizing endpoint is available. Broker contract specifications must be supplied before sizing can be trusted for a real instrument.</p></div>
    </section>
    <div className="footer">SMARTMONEY INTELLIGENCE · FOUNDATION 0.1 · MARKET DATA IS PROVIDED BY BINANCE PUBLIC API · NOT FINANCIAL ADVICE</div>
  </main>;
}
