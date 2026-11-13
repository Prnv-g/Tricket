import { Activity, ArrowUpRight, Menu, Ticket, X, Zap } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

export function Brand(){return <a className="brand" href="/" aria-label="SeatSurge home"><span className="brand-icon"><Zap size={18} fill="currentColor"/></span>Seat<span>Surge</span></a>}
export function Layout({children,admin=false}:{children:ReactNode;admin?:boolean}){
  const [open,setOpen]=useState(false)
  return <><header className="topbar"><div className="nav shell"><Brand/><button className="icon nav-toggle" aria-label={open?'Close navigation':'Open navigation'} aria-expanded={open} onClick={()=>setOpen(!open)}>{open?<X/>:<Menu/>}</button><nav className={open?'nav-links open':'nav-links'} aria-label="Main navigation"><a href="/#event"><Ticket size={15}/> Event</a><a href="/#tiers">Ticket tiers</a><a className={admin?'nav-admin active':'nav-admin'} href="/admin"><Activity size={15}/> Operations <ArrowUpRight size={13}/></a></nav></div></header>{children}<footer className="shell footer"><Brand/><span>Live ticketing for SeatSurge Arena</span><a href="/admin">Operations <ArrowUpRight size={13}/></a></footer></>
}
export function Status({children,kind='good'}:{children:ReactNode;kind?:'good'|'warn'|'muted'}){return <span className={'status '+kind}><i/>{children}</span>}
export function Notice({children}:{children:ReactNode}){return <div className="notice" role="alert">{children}</div>}
export function Skeleton(){return <div className="skeleton" aria-label="Loading" role="status"/>}
