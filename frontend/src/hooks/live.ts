import { useEffect, useRef, useState } from 'react'
import { api, EVENT, socket, type Occupied, type Queue, type Snapshot } from '../lib/api'

export function useSeatMap(enabled:boolean) {
  const [state,setState] = useState<Snapshot|null>(null)
  const [connected,setConnected] = useState(false)
  const [error,setError] = useState('')
  const ref = useRef<Snapshot|null>(null)
  const refresh = useRef<() => void>(()=>{})
  useEffect(()=>{
    if(!enabled) return
    let ws:WebSocket|undefined, stopped=false, pending=false, reconnect:number
    const ctl = new AbortController()
    const update = (next:Snapshot) => { ref.current=next; setState(next) }
    const reconcile = async () => {
      if(pending || stopped) return
      pending=true
      try {
        const version = await api<Omit<Snapshot,'occupied'>>('/seatmap/'+EVENT+'/version',undefined,{signal:ctl.signal})
        if(!ref.current || version.generation!==ref.current.generation || version.version>ref.current.version){
          const next=await api<Snapshot>('/seatmap/'+EVENT,undefined,{signal:ctl.signal})
          if(!stopped && (!ref.current || next.generation!==ref.current.generation || next.version>=ref.current.version)) update(next)
        }
        if(!stopped) setError('')
      } catch(e) { if(!stopped) setError((e as Error).message) }
      finally { pending=false }
    }
    refresh.current=()=>{void reconcile()}
    const connect = () => {
      ws=socket('/ws/seats/'+EVENT)
      ws.onopen=()=>{if(!stopped){setConnected(true); void reconcile()}}
      ws.onclose=()=>{if(!stopped){setConnected(false); reconnect=window.setTimeout(connect,1200)}}
      ws.onmessage=({data})=>{
        const delta=JSON.parse(data) as {generation:string; version:number; status:'HELD'|'SOLD'|'AVAILABLE';seats:number[];reset?:boolean}
        if(!delta.generation) return
        const current=ref.current
        if(delta.reset || !current || delta.generation!==current.generation || delta.version>current.version+1){void reconcile();return}
        if(delta.version<=current.version) return
        const occupied:Occupied={...current.occupied}
        for(const id of delta.seats){if(delta.status==='AVAILABLE') delete occupied[id]; else occupied[id]=delta.status}
        update({...current,version:delta.version,occupied})
      }
    }
    void reconcile()
    connect()
    const interval=window.setInterval(()=>{void reconcile()},1000)
    return ()=>{stopped=true;ctl.abort();clearTimeout(reconnect);clearInterval(interval);ws?.close();refresh.current=()=>{}}
  },[enabled])
  return {state,connected,error,refresh}
}

export function useQueue(enabled:boolean,onUpdate:(queue:Queue)=>void) {
  const update=useRef(onUpdate)
  update.current=onUpdate
  const [online,setOnline]=useState(false)
  useEffect(()=>{
    if(!enabled) return
    let ws:WebSocket|undefined, stopped=false, retry:number
    const ctl=new AbortController()
    const poll=()=>api<Queue>('/queue/status',undefined,{signal:ctl.signal}).then(data=>{
      if(!stopped) update.current(data)
    }).catch(()=>{})
    const connect=()=>{
      ws=socket('/ws/queue')
      ws.onopen=()=>{if(!stopped){setOnline(true);void poll()}}
      ws.onclose=()=>{if(!stopped){setOnline(false);retry=window.setTimeout(connect,1400)}}
      ws.onmessage=({data})=>{if(!stopped) update.current(JSON.parse(data) as Queue)}
    }
    connect()
    const interval=window.setInterval(()=>{void poll()},2000)
    return ()=>{stopped=true;ctl.abort();clearTimeout(retry);clearInterval(interval);ws?.close()}
  },[enabled])
  return online
}

export function useDeadline(deadline:number) {
  const [now,setNow]=useState(Date.now)
  useEffect(()=>{
    const id=window.setInterval(()=>setNow(Date.now()),250)
    return ()=>clearInterval(id)
  },[])
  return Math.max(0,Math.ceil((deadline-now)/1000))
}
