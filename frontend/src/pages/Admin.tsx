import { Activity, ArrowRight, Beaker, Database, Gauge, KeyRound, Radio, Server, ShieldAlert, Terminal } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Layout, Notice, Status } from '../components/Layout'
import { api } from '../lib/api'

type Metrics={health:{redis:boolean;postgres:boolean};instances:Record<string,boolean|null>;metrics:Record<string,number|null>;demo_mode:boolean;bot_screening:string}
type Result={test:string;attempted:number;succeeded:number;rejected:number;duplicate_tickets:number;duplicate_logical_charges:number;duration_ms:number;passed:boolean;details:Record<string,unknown>}
const cards=[
  ['rps','Requests per second','/s'],['p50_ms','p50 latency',' ms'],['p95_ms','p95 latency',' ms'],['cache_ratio','Seat-map cache hit ratio','%'],
  ['queue','Waiting in queue',''],['admitted','Admitted sessions',''],['admissions_per_minute','Admissions per minute',''],['active_holds','Active holds',''],
  ['available','Available seats',''],['sold','Sold seats',''],['expired_holds','Expired holds',''],['bot_blocks','Bot blocks',''],
  ['payments_succeeded','Payment successes',''],['payments_failed','Payment failures',''],['requests','Total requests',''],
] as const
const tests=[
  ['single-seat','100 users, one seat','Launch 100 simultaneous holds against one available seat.'],
  ['overlap','Overlapping six-seat holds','Check that competing groups never receive partial allocations.'],
  ['payment-replay','Replay payment confirmation','Verify a single logical charge and one set of tickets.'],
  ['payment-failure','Payment provider timeout','Check the provider failure path and persisted charge records.'],
  ['expiry','Reservation expiry','Release test inventory and reject payment after expiry.'],
  ['bots','Suspicious bot traffic','Send a high-frequency request burst through screening.'],
  ['reconnect','Snapshot reconciliation','Verify a fresh snapshot reflects missed seat updates.'],
  ['load','Bounded cache load','Run 250 concurrent reads against isolated inventory.'],
  ['queue','Persistent FIFO queue','Verify queue identity and ordered admission.'],
] as const

export default function Admin(){
  const [token,setToken]=useState(''),[credential,setCredential]=useState('')
  const [data,setData]=useState<Metrics|null>(null),[error,setError]=useState('')
  const [result,setResult]=useState<Result|null>(null),[active,setActive]=useState('')
  const [history,setHistory]=useState<number[]>([])
  const busy=useRef(false)
  useEffect(()=>{
    if(!token)return
    const ctl=new AbortController()
    let polling=false
    const poll=async()=>{
      if(polling)return
      polling=true
      try{
        const next=await api<Metrics>('/admin/metrics',undefined,{headers:{Authorization:'Bearer '+token},signal:ctl.signal})
        if(!ctl.signal.aborted){setData(next);setError('');if(next.metrics.rps!=null)setHistory(v=>[...v.slice(-23),next.metrics.rps!])}
      }catch(e){if(!ctl.signal.aborted)setError((e as Error).message)}
      finally{polling=false}
    }
    void poll()
    const interval=window.setInterval(()=>void poll(),2500)
    return()=>{ctl.abort();clearInterval(interval)}
  },[token])
  async function test(name:string){
    if(busy.current)return
    busy.current=true;setActive(name);setResult(null)
    try{setResult(await api<Result>('/admin/tests/'+name,{}, {headers:{Authorization:'Bearer '+token}}))}
    catch(e){setResult({test:name,attempted:0,succeeded:0,rejected:0,duplicate_tickets:0,duplicate_logical_charges:0,duration_ms:0,passed:false,details:{error:(e as Error).message}})}
    finally{busy.current=false;setActive('')}
  }
  const maximum=Math.max(1,...history)
  return <Layout admin><main className="shell flow admin">
    <div className="page-heading"><div><span className="eyebrow"><Activity size={15}/> SEATSURGE OPERATIONS</span><h1>Command center.</h1><p>Live booking health, traffic, and failure testing.</p></div>{data&&<Status kind={error?'warn':'good'}>{error?'Feed interrupted':'Live telemetry'}</Status>}</div>
    {!data?<form className="card admin-login" onSubmit={e=>{e.preventDefault();setToken(credential.trim())}}><span className="feature-icon"><KeyRound size={24}/></span><h2>Operations access</h2><label>Admin credential<input type="password" value={credential} onChange={e=>setCredential(e.target.value)} required autoComplete="off"/></label><button className="button primary">Open dashboard <ArrowRight size={17}/></button></form>:<>
    <div className="health-grid">{[[Database,'PostgreSQL',data.health.postgres],[Database,'Redis',data.health.redis],[Server,'Instance A',data.instances['api-a']],[Server,'Instance B',data.instances['api-b']]].map(([Icon,name,value])=>{const Glyph=Icon as typeof Server;return <div className="card health" key={String(name)}><Glyph size={18}/><strong>{String(name)}</strong><Status kind={value?'good':value===false?'warn':'muted'}>{value?'Healthy':value===false?'Unavailable':'N/A'}</Status></div>})}</div>
    <div className="admin-metrics">{cards.map(([name,label,unit])=>{const value=data.metrics[name];return <div className="card metric" key={name}><span>{label}</span><strong>{value==null?'N/A':(name==='cache_ratio'?(value*100).toFixed(1):Number(value.toFixed(2)).toLocaleString('en-IN'))+unit}</strong></div>})}</div>
    <div className="card traffic"><div><span className="eyebrow"><Gauge size={15}/> TRAFFIC HISTORY</span><h2>Request rate</h2><p>Ten-second average · sampled every 2.5 seconds</p></div><div className="spark" aria-label="Recent requests per second">{history.map((value,i)=><i key={i} style={{height:Math.max(4,value/maximum*100)+'%'}} title={value+' requests/s'}/>)}</div></div>
    <section className="card chaos"><div className="section-heading"><div><span className="eyebrow"><Beaker size={15}/> DEMO TESTING</span><h2>Chaos Arena</h2></div><Status kind={data.demo_mode?'good':'muted'}>{data.demo_mode?'Demo mode enabled':'Demo mode disabled'}</Status></div>
    <p><ShieldAlert size={16}/> Tests use isolated inventory and anonymous test sessions. Screening: {data.bot_screening}.</p>
    <div className="chaos-tests">{tests.map(([name,title,description])=><button key={name} className="test-button" disabled={!data.demo_mode||!!active} onClick={()=>void test(name)}><div><strong>{title}</strong><span>{description}</span></div>{active===name?<Radio size={17}/>:<ArrowRight size={17}/>}</button>)}</div>
    {result&&<div className="test-result"><div className="test-heading"><Terminal size={18}/><strong>{tests.find(([n])=>n===result.test)?.[1]}</strong><Status kind={result.passed?'good':'warn'}>{result.passed?'Passed':'Failed'}</Status></div>
    <dl>{Object.entries({Attempted:result.attempted,Succeeded:result.succeeded,Rejected:result.rejected,'Duplicate tickets':result.duplicate_tickets,'Duplicate charges':result.duplicate_logical_charges,'Duration':result.duration_ms+' ms'}).map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>{Object.entries(result.details).length>0&&<pre>{JSON.stringify(result.details,null,2)}</pre>}</div>}
    </section></>}
    {error&&<Notice>{error}</Notice>}
  </main></Layout>
}
