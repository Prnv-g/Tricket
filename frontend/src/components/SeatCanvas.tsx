import { Maximize, Minus, Plus } from 'lucide-react'
import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { type Occupied, seat } from '../lib/api'

const W=1000,H=625, X=44, Y=68, DX=185,DY=132, GAP=9
const positions=Array.from({length:5200},(_,index)=>{
  const section=Math.floor(index/260),within=index%260
  return [X+section%5*DX+(within%13)*GAP,Y+Math.floor(section/5)*DY+Math.floor(within/13)*5.05] as const
})
type View={z:number;x:number;y:number}
type Drag={x:number;y:number;id:number;moved:boolean}
type Props={occupied:Occupied;selected:number[];held:number[];onSelect:(id:number)=>void}
export default function SeatCanvas({occupied,selected,held,onSelect}:Props){
  const canvas=useRef<HTMLCanvasElement>(null)
  const data=useRef({occupied,selected,held})
  data.current={occupied,selected,held}
  const view=useRef<View>({z:1,x:0,y:0})
  const frame=useRef(0)
  const [hover,setHover]=useState(0)
  const [zoom,setZoom]=useState(1)
  const drag=useRef<Drag|null>(null)
  const touches=useRef(new Map<number,{x:number;y:number}>())
  const pinch=useRef(0)
  const metrics=()=>{
    const el=canvas.current!
    const r=el.getBoundingClientRect(),base=Math.min(r.width/W,r.height/H)
    return {r,base,ox:(r.width-W*base)/2,oy:(r.height-H*base)/2}
  }
  const paint=()=>{
    if(frame.current) return
    frame.current=requestAnimationFrame(()=>{
      frame.current=0
      const el=canvas.current,ctx=el?.getContext('2d')
      if(!el||!ctx) return
      const {r,base,ox,oy}=metrics(),dpr=Math.min(devicePixelRatio,2),{x,y,z}=view.current
      const width=Math.max(1,Math.round(r.width*dpr)),height=Math.max(1,Math.round(r.height*dpr))
      if(el.width!==width||el.height!==height){el.width=width;el.height=height}
      ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,r.width,r.height)
      ctx.translate(ox+x,oy+y);ctx.scale(base*z,base*z)
      ctx.fillStyle='#242b36';ctx.beginPath();ctx.roundRect(345,6,310,33,12);ctx.fill()
      ctx.strokeStyle='#3b444d';ctx.stroke()
      ctx.fillStyle='#e8e7dc';ctx.font='700 11px system-ui';ctx.textAlign='center';ctx.fillText('S T A G E',500,27)
      for(let i=0;i<20;i++){
        const px=X+i%5*DX-13,py=Y+Math.floor(i/5)*DY-14
        ctx.beginPath();ctx.roundRect(px,py,134,119,9);ctx.fillStyle='#141c27';ctx.fill()
        ctx.strokeStyle='#2b3743';ctx.stroke();ctx.fillStyle='#a5b2c0'
        ctx.font='700 10px system-ui';ctx.fillText('SECTION '+String(i+1).padStart(2,'0'),px+67,py+112)
      }
      const current=data.current,selectedSet=new Set(current.selected),heldSet=new Set(current.held)
      positions.forEach(([px,py],index)=>{
        const id=index+1,state=current.occupied[id]
        const own=heldSet.has(id),picked=selectedSet.has(id)
        ctx.fillStyle=own?'#d6ff86':picked?'#ff7058':state==='SOLD'?'#49505b':state==='HELD'?'#a46748':id<=1040?'#e9b573':id<=3120?'#77bfc1':'#7593b8'
        ctx.fillRect(px-2.7,py-1.6,5.4,3.3)
        if(state==='SOLD'||state==='HELD'||own||picked){
          ctx.strokeStyle=own||picked?'#f4f2eb':state==='SOLD'?'#141c27':'#f0b093'
          ctx.lineWidth=.65
          ctx.beginPath();ctx.moveTo(px-2.3,py+1.1);ctx.lineTo(px+2.3,py-1.1)
          if(state==='SOLD'){ctx.moveTo(px-2.3,py-1.1);ctx.lineTo(px+2.3,py+1.1)}
          ctx.stroke()
        }
      })
    })
  }
  useEffect(paint,[occupied,selected,held])
  const scale=(factor:number,clientX?:number,clientY?:number)=>{
    const {r,ox,oy}=metrics(),old=view.current
    const px=(clientX??(r.left+r.width/2))-r.left-ox,py=(clientY??(r.top+r.height/2))-r.top-oy
    const z=Math.min(7,Math.max(1,old.z*factor)),ratio=z/old.z
    view.current=z===1?{z,x:0,y:0}:{z,x:px-(px-old.x)*ratio,y:py-(py-old.y)*ratio}
    setZoom(z);paint()
  }
  useEffect(()=>{
    const el=canvas.current!
    const observer=new ResizeObserver(paint)
    observer.observe(el)
    const wheel=(event:WheelEvent)=>{event.preventDefault();scale(Math.exp(-event.deltaY*.0018),event.clientX,event.clientY)}
    el.addEventListener('wheel',wheel,{passive:false})
    return()=>{observer.disconnect();el.removeEventListener('wheel',wheel);cancelAnimationFrame(frame.current);frame.current=0}
  },[])
  const hit=(clientX:number,clientY:number)=>{
    const {r,base,ox,oy}=metrics(),{x,y,z}=view.current
    const px=(clientX-r.left-ox-x)/(base*z)-X,py=(clientY-r.top-oy-y)/(base*z)-Y
    const sx=Math.floor((px+4)/DX),sy=Math.floor((py+2.5)/DY)
    if(sx<0||sx>4||sy<0||sy>3) return 0
    const col=Math.round((px-sx*DX)/GAP),row=Math.round((py-sy*DY)/5.05)
    if(col<0||col>12||row<0||row>19) return 0
    return (sy*5+sx)*260+row*13+col+1
  }
  const down=(e:PointerEvent<HTMLCanvasElement>)=>{
    e.currentTarget.setPointerCapture(e.pointerId)
    touches.current.set(e.pointerId,{x:e.clientX,y:e.clientY})
    if(touches.current.size===1) drag.current={x:e.clientX,y:e.clientY,id:e.pointerId,moved:false}
    if(touches.current.size===2){const [a,b]=[...touches.current.values()];pinch.current=Math.hypot(a.x-b.x,a.y-b.y);if(drag.current)drag.current.moved=true}
  }
  const move=(e:PointerEvent<HTMLCanvasElement>)=>{
    if(touches.current.has(e.pointerId)) touches.current.set(e.pointerId,{x:e.clientX,y:e.clientY})
    if(touches.current.size===2){
      const [a,b]=[...touches.current.values()],distance=Math.hypot(a.x-b.x,a.y-b.y)
      if(pinch.current>0)scale(distance/pinch.current,(a.x+b.x)/2,(a.y+b.y)/2)
      pinch.current=distance;return
    }
    const start=drag.current
    if(start?.id===e.pointerId){
      const dx=e.clientX-start.x,dy=e.clientY-start.y
      if(start.moved||Math.hypot(dx,dy)>4){start.moved=true;start.x=e.clientX;start.y=e.clientY;if(view.current.z>1){view.current.x+=dx;view.current.y+=dy;paint()}}
      return
    }
    setHover(hit(e.clientX,e.clientY))
  }
  const end=(e:PointerEvent<HTMLCanvasElement>)=>{
    const start=drag.current
    if(start?.id===e.pointerId){
      if(e.type==='pointerup'&&!start.moved){const id=hit(e.clientX,e.clientY);if(id)onSelect(id)}
      drag.current=null
    }
    touches.current.delete(e.pointerId);pinch.current=0
  }
  const item=hover?seat(hover):null
  return <div className="canvas-wrap"><canvas ref={canvas} aria-label="Arena seat map. Use the accessible seat list below for keyboard selection." onPointerDown={down} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onPointerLeave={()=>setHover(0)}/>
    <div className="map-tools"><button className="icon" aria-label="Zoom in" onClick={()=>scale(1.35)}><Plus size={17}/></button><button className="icon" aria-label="Zoom out" onClick={()=>scale(1/1.35)}><Minus size={17}/></button><button className="icon" aria-label="Reset zoom" onClick={()=>scale(1/zoom)}><Maximize size={15}/></button></div>
    {item&&<div className="map-hover">Section {item.section} · Row {item.row} · Seat {item.number} · {held.includes(item.id)?'Held by you':selected.includes(item.id)?'Selected':occupied[item.id]??'Available'}</div>}
  </div>
}
