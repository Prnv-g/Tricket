import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Layout, Skeleton } from './components/Layout'
import { useQueue, useSeatMap } from './hooks/live'
import { api, ApiError, EVENT, key, type Booking, type Event, type Hold, type Mode, type Payment, type Queue, type Suggestion } from './lib/api'
import { Checkout, Confirmation, SeatPage, Waiting } from './pages/Booking'
import { Landing } from './pages/Landing'

const Admin=lazy(()=>import('./pages/Admin'))
type Page='landing'|'waiting'|'seats'|'checkout'|'confirmation'
type Attempt={mode:Mode; idempotency_key:string}
type Turnstile={render:(element:HTMLElement,options:{sitekey:string;callback:(token:string)=>void;'error-callback':()=>void})=>string;remove:(widget:string)=>void}
declare global { interface Window {turnstile?:Turnstile} }

function TurnstileWidget({siteKey,token,onError}:{siteKey:string;token:(value:string)=>void;onError:()=>void}){
  const container=useRef<HTMLDivElement>(null)
  const callbacks=useRef({token,onError})
  callbacks.current={token,onError}
  useEffect(()=>{
    let widget:string|undefined,disposed=false
    const render=()=>{if(!disposed&&container.current&&window.turnstile) widget=window.turnstile.render(container.current,{sitekey:siteKey,callback:v=>callbacks.current.token(v),'error-callback':()=>callbacks.current.onError()})}
    if(window.turnstile) render()
    else {
      const script=document.createElement('script')
      script.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
      script.async=true;script.onload=render;script.onerror=()=>callbacks.current.onError()
      document.head.append(script)
    }
    return()=>{disposed=true;if(widget)window.turnstile?.remove(widget)}
  },[siteKey])
  return <div className="turnstile" ref={container}/>
}

function Customer(){
  const [page,setPage]=useState<Page>('landing')
  const [event,setEvent]=useState<Event|null>(null),[queue,setQueue]=useState<Queue|null>(null)
  const [hold,setHold]=useState<Hold|null>(null),[booking,setBooking]=useState<Booking|null>(null)
  const [selected,setSelected]=useState<number[]>([])
  const [error,setError]=useState(''),[challenge,setChallenge]=useState(''),[pending,setPending]=useState(false)
  const [turnstile,setTurnstile]=useState(false)
  const pendingAnswer=useRef<string|undefined>(undefined)
  const behavior=useRef({start:performance.now(),last:0,intervals:[] as number[],moves:0,clicks:0})
  const inFlight=useRef(false)
  const holdKey=useRef<{selection:string;key:string}|null>(null)
  const paymentAttempt=useRef<Attempt|null>(null)
  const current=useRef(page);current.current=page
  const seatmap=useSeatMap(page==='seats'||page==='checkout')
  function show(target:Page){
    setPage(target)
    window.scrollTo({top:0,behavior:'instant'})
  }
  async function recoverHold(id:string){
    const data=await api<Hold>('/holds/'+id)
    if(data.status==='ACTIVE'&&data.expires_at>Date.now()){
      setHold(data);setSelected(data.seat_ids);show('checkout')
      const saved=sessionStorage.getItem('seatsurge-payment-'+id)
      paymentAttempt.current=saved?JSON.parse(saved) as Attempt:null
      return true
    }
    return false
  }
  async function recoverPayment(reservation:string){
    const raw=sessionStorage.getItem('seatsurge-payment-'+reservation)
    if(!raw) return false
    const attempt=JSON.parse(raw) as Attempt
    const payment=await api<Payment>('/payments/simulate',{event_id:EVENT,reservation_id:reservation,...attempt})
    if(!payment.booking_id) return false
    await showBooking(payment.booking_id)
    return true
  }
  async function showBooking(id:string){
    const data=await api<Booking>('/bookings/'+id)
    sessionStorage.setItem('seatsurge-booking',data.id)
    sessionStorage.removeItem('seatsurge-active')
    setBooking(data);setError('');show('confirmation')
  }
  function updateQueue(next:Queue){
    setQueue(next)
    if(current.current==='waiting'&&next.status==='ADMITTED'){
      setError('')
      if(next.active_hold_id) void recoverHold(next.active_hold_id).then(found=>{if(!found)show('seats')}).catch(e=>setError(e.message))
      else show('seats')
    }
  }
  const liveQueue=useQueue(page==='waiting'&&!!queue?.id,updateQueue)

  useEffect(()=>{
    let disposed=false
    const load=()=>api<Event>('/events/'+EVENT).then(value=>{if(!disposed)setEvent(value)}).catch(()=>{})
    void load()
    const poll=window.setInterval(()=>{if(current.current==='landing')void load()},10000)
    void (async()=>{
      try {
        const saved=sessionStorage.getItem('seatsurge-booking')
        if(saved){await showBooking(saved);return}
        const status=await api<Queue>('/queue/status')
        if(disposed||inFlight.current)return
        setQueue(status)
        if(status.active_hold_id&&await recoverHold(status.active_hold_id))return
        if(status.booking_id){await showBooking(status.booking_id);return}
        const reservation=sessionStorage.getItem('seatsurge-active')
        if(status.status==='COMPLETED'&&reservation&&await recoverPayment(reservation))return
        if(status.status==='ADMITTED')show('seats')
        else if(status.status==='WAITING'||status.status==='EXPIRED')show('waiting')
      }catch(e){if(!disposed&&(!(e instanceof ApiError)||e.status!==401))setError((e as Error).message)}
    })()
    const movement=()=>{behavior.current.moves=Math.min(4000,behavior.current.moves+1)}
    const click=()=>{
      const b=behavior.current,now=performance.now()
      if(b.last&&b.intervals.length<32)b.intervals.push(Math.min(60000,Math.round(now-b.last)))
      b.last=now;b.clicks=Math.min(200,b.clicks+1)
    }
    window.addEventListener('pointermove',movement,{passive:true})
    window.addEventListener('pointerdown',click,{passive:true})
    return()=>{disposed=true;clearInterval(poll);window.removeEventListener('pointermove',movement);window.removeEventListener('pointerdown',click)}
  },[])

  useEffect(()=>{
    if(page!=='checkout'||!hold||pending)return
    const delay=Math.max(0,hold.expires_at-Date.now())
    const timeout=window.setTimeout(()=>{setHold(null);setSelected([]);setError('Your reservation expired. Select available seats to try again.');show('seats')},delay+200)
    return()=>clearTimeout(timeout)
  },[page,hold,pending])

  async function join(answer?:string,turnstileToken?:string){
    if(inFlight.current)return
    if(event?.turnstile_site_key&&!turnstileToken){pendingAnswer.current=answer;setTurnstile(true);return}
    inFlight.current=true;setPending(true);setError('');setTurnstile(false)
    try{
      await api('/session',{})
      const {start,intervals,moves,clicks}=behavior.current
      const next=await api<Queue>('/queue/join',{event_id:EVENT,behavior:{intervals,moves,clicks,elapsed_ms:Math.min(3600000,Math.round(performance.now()-start))},challenge_answer:answer,turnstile_token:turnstileToken})
      setChallenge('');setQueue(next)
      if(next.active_hold_id&&await recoverHold(next.active_hold_id))return
      if(next.status==='ADMITTED') show('seats')
      else if(next.status==='COMPLETED'){
        const saved=next.booking_id??sessionStorage.getItem('seatsurge-booking')
        if(saved)await showBooking(saved)
        else setError('This session has already completed its booking.')
      } else show('waiting')
    }catch(e){
      if(e instanceof ApiError&&e.code==='BOT_CHALLENGE'){setChallenge(e.message);show('waiting')}
      else setError((e as Error).message)
    }finally{inFlight.current=false;setPending(false)}
  }

  function select(id:number){
    if(pending||!seatmap.state)return
    setError('')
    if(selected.includes(id)){setSelected(selected.filter(item=>item!==id));return}
    if(seatmap.state.occupied[id]){setError('That seat is already held or sold.');return}
    if(selected.length===6){setError('A booking can include up to six seats.');return}
    setSelected([...selected,id].sort((a,b)=>a-b))
  }

  async function reserve(){
    if(inFlight.current||!selected.length)return
    const selection=selected.join(',')
    if(holdKey.current?.selection!==selection)holdKey.current={selection,key:key()}
    inFlight.current=true;setPending(true);setError('')
    try{
      const data=await api<Hold>('/holds',{event_id:EVENT,seat_ids:selected,idempotency_key:holdKey.current.key})
      if(data.status!=='ACTIVE'||data.expires_at<=Date.now())throw new ApiError(409,'HOLD_EXPIRED','This reservation expired. Select your seats again.')
      setHold(data);paymentAttempt.current=null;holdKey.current=null
      sessionStorage.setItem('seatsurge-active',data.id);show('checkout')
    }catch(e){
      if(e instanceof ApiError&&e.status===409){
        holdKey.current=null
        if(e.code==='SEAT_TAKEN'||e.code==='HOLD_EXPIRED')setSelected([])
        seatmap.refresh.current()
      }
      setError((e as Error).message)
    }finally{inFlight.current=false;setPending(false)}
  }

  async function checkout(mode:Mode){
    if(!hold||inFlight.current)return
    inFlight.current=true;setPending(true);setError('')
    if(!paymentAttempt.current)paymentAttempt.current={mode,idempotency_key:key()}
    const attempt=paymentAttempt.current
    sessionStorage.setItem('seatsurge-payment-'+hold.id,JSON.stringify(attempt))
    try{
      const result=await api<Payment>('/payments/simulate',{event_id:EVENT,reservation_id:hold.id,...attempt})
      if(result.status==='SUCCEEDED'&&result.booking_id)await showBooking(result.booking_id)
      else if(result.status==='FAILED'){
        sessionStorage.removeItem('seatsurge-payment-'+hold.id)
        paymentAttempt.current=null
        setError(result.mode==='timeout'?'The simulated provider timed out. No charge was recorded. You can retry before your hold expires.':'Payment was declined. You can retry before your hold expires.')
      } else setError('Payment is pending. Retry to check this attempt.')
    }catch(e){
      if(e instanceof ApiError&&e.code==='HOLD_EXPIRED'){setHold(null);setSelected([]);show('seats')}
      setError((e as Error).message)
    }finally{inFlight.current=false;setPending(false)}
  }

  async function release(){
    if(!hold||inFlight.current)return
    inFlight.current=true;setPending(true);setError('')
    try{
      await api('/holds/'+hold.id,undefined,{method:'DELETE'})
      sessionStorage.removeItem('seatsurge-active')
      sessionStorage.removeItem('seatsurge-payment-'+hold.id)
      setHold(null);setSelected([]);paymentAttempt.current=null;show('seats')
    }catch(e){setError((e as Error).message)}
    finally{inFlight.current=false;setPending(false)}
  }

  const home=()=>{setError('');show('landing')}
  let content
  if(page==='confirmation'&&booking)content=<Confirmation booking={booking}/>
  else if(page==='checkout'&&hold)content=<Checkout hold={hold} error={error} pending={pending} onPay={mode=>void checkout(mode)} onBack={()=>void release()}/>
  else if(page==='seats')content=<SeatPage occupied={seatmap.state?.occupied??null} connected={seatmap.connected} error={error||seatmap.error} selected={selected} hold={hold} pending={pending} onSelect={select} onUse={ids=>{if(!selected.length)setSelected(ids);else setError('Clear your current selection before using this suggestion.')}} onHold={()=>void reserve()} onClear={()=>{setSelected([]);setError('')}} onBack={home} onSuggest={(count,tier)=>api<Suggestion[]>('/seats/recommend',{event_id:EVENT,count,tier})}/>
  else if(page==='waiting')content=<Waiting queue={queue} connected={liveQueue} error={error} challenge={challenge} onAnswer={answer=>void join(answer)} onHome={home}/>
  else content=<Landing event={event} book={()=>void join()} error={error} pending={pending}/>
  return <Layout>{content}{turnstile&&event?.turnstile_site_key&&<TurnstileWidget siteKey={event.turnstile_site_key} token={value=>void join(pendingAnswer.current,value)} onError={()=>{setError('Security verification could not load.');setTurnstile(false)}}/>}</Layout>
}

export default function App(){
  return location.pathname==='/admin'?<Suspense fallback={<Layout admin><main className="shell flow"><Skeleton/></main></Layout>}><Admin/></Suspense>:<Customer/>
}
