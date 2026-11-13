import { ArrowDown, ArrowRight, CalendarDays, Layers3, MapPin, Radio, ShieldCheck, Ticket } from 'lucide-react'
import { type Event, money, TIERS, PRICES } from '../lib/api'
import { Notice, Status } from '../components/Layout'

const tierDescriptions=['Closest to the stage, with a direct view of the show.','Lower-level seating with a wide view of the stage.','Elevated seating with a full view of the arena.']
export function Landing({event,book,error,pending}:{event:Event|null;book:()=>void;error:string;pending:boolean}){
  return <main className="shell landing" id="event">
    <section className="hero">
      <div className="hero-art" aria-hidden="true"><div className="arena-glow"/><div className="beam beam-a"/><div className="beam beam-b"/><div className="beam beam-c"/><div className="arena-horizon"/><div className="arena-grid"/></div>
      <div className="hero-content">
        <div className="hero-kicker"><Radio size={14}/> SEATSURGE ARENA PRESENTS</div>
        <h1>NEON<br/><em>NIGHTS</em></h1>
        <p className="hero-subtitle">Live at the arena</p>
        <div className="event-meta"><span><CalendarDays size={17}/> Sat, 19 Dec 2026 · 7:30 PM IST</span><span><MapPin size={17}/> Hyderabad, India</span></div>
        <div className="hero-actions"><button className="button primary" disabled={pending} onClick={book}><Ticket size={19}/>{pending?'Starting booking…':'Book tickets'}<ArrowRight size={18}/></button><a href="#tiers" className="button glass">Explore tiers <ArrowDown size={16}/></a></div>
        {error&&<Notice>{error}</Notice>}
      </div>
      <div className="hero-caption"><span>SEATSURGE ARENA</span><strong>HYD</strong></div>
    </section>
    <div className="event-strip">
      <div><span className="label">LIVE INVENTORY</span>{event?.available!=null?<Status>{event.available.toLocaleString('en-IN')} seats available</Status>:<Status kind="muted">Availability pending</Status>}</div>
      <div><span className="label">TICKETS FROM</span><strong>{money(1799)}</strong></div>
      <div><span className="label">ARENA CAPACITY</span><strong>{(event?.capacity??5200).toLocaleString('en-IN')}</strong></div>
      <div><span className="label">BOOKING ACCESS</span><span className="strip-detail"><ShieldCheck size={18}/> Verified waiting room</span></div>
    </div>
    <section id="tiers" className="tiers"><div className="section-heading"><div><span className="eyebrow"><Layers3 size={14}/> SEATING OPTIONS</span><h2>Find your spot.</h2></div><p>Three ticket tiers across 20 sections. All prices are per person.</p></div>
    <div className="tier-grid">{TIERS.map((tier,i)=><article className={'tier-card tier-'+i} key={tier}><span className="tier-symbol"><Ticket size={22}/></span><h3>{tier}</h3><p>{tierDescriptions[i]}</p><strong>{money(PRICES[i])}</strong></article>)}</div>
    </section>
    <section className="venue card"><div><span className="eyebrow"><MapPin size={14}/> THE VENUE</span><h2>SeatSurge Arena</h2><p>Hyderabad, India · 20 sections · 5,200 reserved seats</p></div><button className="button secondary" disabled={pending} onClick={book}>Join the waiting room <ArrowRight size={17}/></button></section>
  </main>
}
