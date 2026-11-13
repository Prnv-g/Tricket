export const EVENT = 'neon-nights'
export type Occupied = Record<number, 'HELD' | 'SOLD'>
export type Snapshot = {generation: string; version: number; occupied: Occupied}
export type Event = {id:string; title:string; venue:string; starts_at:string; capacity:number; available:number|null; turnstile_site_key:string}
export type Queue = {id?:string; sequence?:number; status:'NOT_JOINED'|'WAITING'|'ADMITTED'|'EXPIRED'|'COMPLETED'; position?:number; ahead?:number; eta_seconds?:number; active_hold_id?:string; booking_id?:string}
export type Hold = {id:string; seat_ids:number[]; expires_at:number; status:'ACTIVE'|'COMMITTING'|'CONFIRMED'|'CANCELLED'|'EXPIRED'}
export type Mode = 'success'|'decline'|'timeout'
export type Payment = {id:string; mode:Mode; status:'SUCCEEDED'|'FAILED'|'PROCESSING'; booking_id:string|null; amount:number}
export type Booking = {id:string; title:string; venue:string; starts_at:string; amount:number; provider_reference:string; tickets:{id:string; seat_id:number; section:number; row_number:number; seat_number:number; tier:string; price:number}[]}
export type Suggestion = {seat_ids:number[]; price:number}
export const TIERS = ['Front Row', 'Lower Bowl', 'Upper Bowl'] as const
export const PRICES = [5499,3299,1799]
export const tierIndex = (id: number) => id<=1040 ? 0 : id<=3120 ? 1 : 2
export function seat(id:number) {
  const section = Math.floor((id-1)/260)+1
  const row = Math.floor((id-1)%260/13)+1
  const number = (id-1)%13+1
  const index = tierIndex(id)
  return {id, section, row, number, tier:TIERS[index], price:PRICES[index]}
}
export const money = (value:number) => '₹'+new Intl.NumberFormat('en-IN').format(value)
export const date = (value:string) => new Intl.DateTimeFormat('en-IN',{dateStyle:'long',timeStyle:'short',timeZone:'Asia/Kolkata'}).format(new Date(value))
export class ApiError extends Error {
  constructor(public status:number, public code:string, message:string) { super(message) }
}
export async function api<T>(path:string, body?:unknown, options:RequestInit = {}):Promise<T> {
  let response: Response
  try {
    response = await fetch('/api'+path, {
      ...options, method:options.method ?? (body === undefined ? 'GET' : 'POST'),
      credentials:'same-origin', headers:{...(body === undefined ? {} : {'Content-Type':'application/json'}), ...options.headers},
      body:body === undefined ? undefined : JSON.stringify(body),
      signal:options.signal ?? AbortSignal.timeout(15000),
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0,'CONNECTION','Connection interrupted. Check your network and try again.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status,data?.error?.code ?? 'SERVICE_UNAVAILABLE',data?.error?.message ?? 'SeatSurge is temporarily unavailable.')
  return data as T
}
export const socket = (path:string) => new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+path)
export const key = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2,'0')).join('')
