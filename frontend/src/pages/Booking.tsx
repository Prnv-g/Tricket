import { ArrowLeft, ArrowRight, Armchair, BadgeCheck, CalendarDays, Check, CircleHelp, Clock3, CreditCard, Fingerprint, MapPin, Printer, Radio, ShieldCheck, Sparkles, Ticket, WifiOff } from 'lucide-react'
import { useState } from 'react'
import SeatCanvas from '../components/SeatCanvas'
import { Notice, Skeleton, Status } from '../components/Layout'
import { useDeadline } from '../hooks/live'
import { date, money, seat, TIERS, type Booking as BookingData, type Hold, type Mode, type Occupied, type Queue, type Suggestion } from '../lib/api'

export function Waiting({queue,connected,error,challenge,onAnswer,onHome}:{queue:Queue|null;connected:boolean;error:string;challenge:string;onAnswer:(answer:string)=>void;onHome:()=>void}){
  const [answer,setAnswer]=useState('')
  const position=queue?.position
  return <main className="shell flow narrow"><button className="back" onClick={onHome}><ArrowLeft size={16}/> Event</button>
    <div className="card waiting"><span className="feature-icon"><Fingerprint size={28}/></span><span className="eyebrow">NEON NIGHTS · BOOKING ACCESS</span>
    <h1>{challenge?'Verify your session':queue?.status==='EXPIRED'?'Booking window ended':'You’re in the waiting room'}</h1>
    <p>{challenge?'Answer the security question to join the queue.':queue?.status==='EXPIRED'?'This session’s admission has expired.':"Your place is saved. You can refresh this page and keep your position."}</p>
    {challenge?<form className="challenge" onSubmit={e=>{e.preventDefault();onAnswer(answer)}}><label>{challenge}<input value={answer} onChange={e=>setAnswer(e.target.value)} inputMode="numeric" maxLength={8} required/></label><button className="button primary">Verify <ArrowRight size={16}/></button></form>:<>
    <div className="queue-stats"><div><span className="label">YOUR POSITION</span><strong>{position??'—'}</strong></div><div><span className="label">PEOPLE AHEAD</span><strong>{queue?.ahead??'—'}</strong></div><div><span className="label">EST. WAIT</span><strong>{queue?.eta_seconds!=null?(queue.eta_seconds<60?queue.eta_seconds+'s':Math.ceil(queue.eta_seconds/60)+'m'):'—'}</strong></div></div>
    <div className="queue-progress"><progress aria-label="Admission progress" max={100} value={position?Math.max(4,100/(position+1)):undefined}/></div>
    <div className="waiting-meta"><Status kind={connected?'good':'warn'}>{connected?'Live connection':'Reconnecting'}</Status><span><ShieldCheck size={16}/> {queue?.id?'Verified':'Verifying'}</span></div>
    <div className="queue-id"><span className="label">QUEUE ID</span><code>{queue?.id??'Pending'}</code></div></>}
    {error&&<Notice>{error}</Notice>}
    </div></main>
}

const empty:number[]=[]
const range=(n:number)=>Array.from({length:n},(_,i)=>i+1)
type SeatProps={occupied:Occupied|null;connected:boolean;error:string;selected:number[];hold:Hold|null;pending:boolean;onSelect:(id:number)=>void;onUse:(ids:number[])=>void;onHold:()=>void;onClear:()=>void;onBack:()=>void;onSuggest:(n:number,tier?:typeof TIERS[number])=>Promise<Suggestion[]>}

export function SeatPage(props:SeatProps){
  const {occupied,connected,error,selected,hold,pending,onSelect,onUse,onHold,onClear,onBack,onSuggest}=props
  const [section,setSection]=useState(1),[row,setRow]=useState(1),[showList,setShowList]=useState(false)
  const [count,setCount]=useState(2),[tier,setTier]=useState(''),[suggestions,setSuggestions]=useState<Suggestion[]|null>(null)
  const [finding,setFinding]=useState(false),[suggestError,setSuggestError]=useState('')
  const total=selected.reduce((sum,id)=>sum+seat(id).price,0)
  async function find(){
    setFinding(true);setSuggestError('')
    try{setSuggestions(await onSuggest(count,tier as typeof TIERS[number]||undefined))}
    catch(e){setSuggestError((e as Error).message)}
    finally{setFinding(false)}
  }
  return <main className="shell flow"><button className="back" onClick={onBack}><ArrowLeft size={16}/> Event</button><div className="page-heading"><div><span className="eyebrow"><Armchair size={15}/> NEON NIGHTS · SEAT SELECTION</span><h1>Choose your seats.</h1><p>Pick up to six adjacent seats in the same row.</p></div><Status kind={connected?'good':'warn'}>{connected?'Live inventory':'Reconnecting'}</Status></div>
    {error&&<Notice>{error}</Notice>}
    <div className="seating-layout"><div className="seating-main"><section className="card map-card">
      <div className="map-top"><div><h2>SeatSurge Arena</h2><p>Drag to pan after zooming. Scroll or pinch to zoom.</p></div><span><Radio size={15}/> 20 SECTIONS</span></div>
      {occupied?<SeatCanvas occupied={occupied} selected={selected} held={hold?.seat_ids??empty} onSelect={onSelect}/>:<Skeleton/>}
      <div className="legend"><span><i className="available"/> Available</span><span><i className="selected"/> Selected</span><span><i className="held-me"/> Held by you</span><span><i className="held"/> Held by others</span><span><i className="sold"/> Sold</span></div>
      <div className="list-picker"><button className="back" aria-expanded={showList} onClick={()=>setShowList(!showList)}><CircleHelp size={15}/> {showList?'Hide':'Open'} accessible seat list</button>
      {showList&&occupied&&<><div className="field-row"><label>Section<select value={section} onChange={e=>setSection(+e.target.value)}>{range(20).map(n=><option key={n}>{n}</option>)}</select></label><label>Row<select value={row} onChange={e=>setRow(+e.target.value)}>{range(20).map(n=><option key={n}>{n}</option>)}</select></label></div><div className="seat-list">{range(13).map(n=>{const id=(section-1)*260+(row-1)*13+n,chosen=selected.includes(id),status=occupied[id];return <button key={n} className={chosen?'active':''} aria-pressed={chosen} disabled={!!status&&!chosen} onClick={()=>onSelect(id)}>Seat {n}<small>{chosen?'Selected':status??money(seat(id).price)}</small></button>})}</div></>}
      </div>
    </section>
    <section className="card recommendation"><div><span className="eyebrow"><Sparkles size={15}/> GROUP SEATING</span><h2>Find adjacent seats</h2><p>Search available rows for your group.</p></div><div className="field-row"><label>Group size<select value={count} onChange={e=>setCount(+e.target.value)}>{range(6).map(n=><option key={n} value={n}>{n} {n===1?'seat':'seats'}</option>)}</select></label><label>Ticket tier<select value={tier} onChange={e=>setTier(e.target.value)}><option value="">Any tier</option>{TIERS.map(t=><option key={t}>{t}</option>)}</select></label><button className="button secondary" disabled={finding||!occupied} onClick={()=>void find()}>{finding?'Searching…':'Find seats'}</button></div>
    {suggestError&&<Notice>{suggestError}</Notice>}{suggestions?.length===0&&<p>No adjacent seats match those options.</p>}
    {suggestions&&<div className="suggestions">{suggestions.map(group=>{const first=seat(group.seat_ids[0]),last=seat(group.seat_ids.at(-1)!);return <button className="suggestion" key={first.id} onClick={()=>onUse(group.seat_ids)} disabled={group.seat_ids.some(id=>!!occupied?.[id])}><span>Section {first.section} · Row {first.row} · Seat{first.id!==last.id?'s':''} {first.number}{first.id!==last.id?'–'+last.number:''}</span><strong>{money(group.price)}</strong><ArrowRight size={15}/></button>})}</div>}
    </section></div>
    <aside className="card booking-tray"><div className="tray-heading"><span className="feature-icon small"><Ticket size={20}/></span><div><h2>Your selection</h2><p>{selected.length} of 6 seats</p></div></div>
      {selected.length?<div className="selected-list">{selected.map(id=>{const item=seat(id);return <div key={id}><span>Sec {item.section} · Row {item.row} · Seat {item.number}</span><strong>{money(item.price)}</strong></div>})}</div>:<p className="empty">Choose seats on the map or browse the accessible seat list.</p>}
      <div className="tray-total"><span>Total</span><strong>{money(total)}</strong></div>
      <button className="button primary wide" disabled={!selected.length||pending||!occupied} onClick={onHold}>{pending?'Reserving…':'Reserve & checkout'} <ArrowRight size={17}/></button>
      {selected.length>0&&<button className="back clear" disabled={pending} onClick={onClear}>Clear selection</button>}
    </aside></div></main>
}

function Countdown({deadline}:{deadline:number}){
  const left=useDeadline(deadline)
  return <span className={'countdown '+(left<20?'urgent':'')}><Clock3 size={18}/>{Math.floor(left/60)}:{String(left%60).padStart(2,'0')} remaining</span>
}

export function Checkout({hold,error,pending,onPay,onBack}:{hold:Hold;error:string;pending:boolean;onPay:(mode:Mode)=>void;onBack:()=>void}){
  const [mode,setMode]=useState<Mode>('success')
  const total=hold.seat_ids.reduce((sum,id)=>sum+seat(id).price,0)
  return <main className="shell flow"><button className="back" onClick={onBack} disabled={pending}><ArrowLeft size={16}/> Release hold and return to seats</button>
    <div className="page-heading"><div><span className="eyebrow"><ShieldCheck size={15}/> SECURE CHECKOUT</span><h1>Complete your booking.</h1><p>Your seats are held while you complete payment.</p></div><Countdown deadline={hold.expires_at}/></div>
    <div className="checkout-layout"><section className="card payment-card"><span className="feature-icon"><CreditCard size={27}/></span><h2>Simulated payment</h2><p>No real money moves and no card details are collected.</p><label>Simulation outcome<select disabled={pending} value={mode} onChange={e=>setMode(e.target.value as Mode)}><option value="success">Approve payment</option><option value="decline">Decline payment</option><option value="timeout">Provider timeout</option></select></label>
    {error&&<Notice>{error}</Notice>}<button className="button primary wide" disabled={pending} onClick={()=>onPay(mode)}>{pending?'Checking payment…':'Simulate payment · '+money(total)} <ArrowRight size={17}/></button></section>
    <aside className="card order-summary"><h2>Order summary</h2><p>Neon Nights · SeatSurge Arena</p><div className="selected-list">{hold.seat_ids.map(id=>{const item=seat(id);return <div key={id}><span>Sec {item.section} · Row {item.row} · Seat {item.number}</span><strong>{money(item.price)}</strong></div>})}</div><div className="tray-total"><span>Total</span><strong>{money(total)}</strong></div></aside></div></main>
}

export function Confirmation({booking}:{booking:BookingData}){
  return <main className="shell flow narrow printable"><div className="confirmation-heading"><span className="feature-icon"><BadgeCheck size={32}/></span><Status>Simulated payment confirmed</Status><h1>You’re going to Neon Nights.</h1><p>Booking reference</p><code>{booking.id}</code></div>
  <div className="tickets">{booking.tickets.map(ticket=><article className="digital-ticket" key={ticket.id}><div><span className="eyebrow"><Ticket size={15}/> DIGITAL TICKET</span><h2>{booking.title}</h2><p><MapPin size={15}/> {booking.venue}</p><p><CalendarDays size={15}/> {date(booking.starts_at)}</p><code>{ticket.id}</code></div><div className="stub"><span>{ticket.tier}</span><strong>{ticket.section} / {ticket.row_number} / {ticket.seat_number}</strong><small>SECTION / ROW / SEAT</small></div></article>)}</div>
  <div className="confirmation-actions"><button className="button primary" onClick={()=>window.print()}><Printer size={17}/> Print tickets</button><a className="button secondary" href="/"><Check size={17}/> Back to event</a></div></main>
}

export function ConnectionNotice({message}:{message:string}){return <Notice><WifiOff size={17}/> {message}</Notice>}
