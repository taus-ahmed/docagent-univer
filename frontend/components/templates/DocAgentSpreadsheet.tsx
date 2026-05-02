"use client";

import { useState, useRef, useCallback, useEffect, useMemo } from "react";

interface CellStyle {
  bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean;
  fontSize?: number; fontFamily?: string; fontColor?: string; bgColor?: string;
  align?: "left" | "center" | "right"; wrap?: boolean;
  borderAll?: boolean; borderOuter?: boolean;
}
interface Cell { value: string; style: CellStyle; mergeParent?: [number,number]; mergeSpan?: {rows:number;cols:number}; }
interface Props {
  initialColumns?: {name:string;type:string;order:number}[];
  initialSheetData?: any;
  onSheetsChange?: (data:any[]) => void;
  height?: number|string;
}

const ROWS=50, COLS=26, DCW=120, DRH=26, RHW=46, CHH=26;
const FONTS=["Arial","Calibri","Segoe UI","Times New Roman","Georgia","Courier New","Verdana"];
const SIZES=[8,9,10,11,12,14,16,18,20,22,24,28,32,36,48,72];
const COLORS=["#000000","#434343","#666666","#999999","#b7b7b7","#cccccc","#d9d9d9","#ffffff","#ff0000","#ff4500","#ff9900","#ffff00","#00ff00","#00ffff","#4a86e8","#0000ff","#9900ff","#ff00ff","#ea9999","#f9cb9c","#ffe599","#b6d7a8","#a2c4c9","#a4c2f4","#4285f4","#34a853","#fbbc05","#ea4335","#c27ba0","#674ea7","#e06666","#f6b26b"];
const ck=(r:number,c:number)=>`${r},${c}`;
const cl=(i:number)=>{let r="",n=i;do{r=String.fromCharCode(65+(n%26))+r;n=Math.floor(n/26)-1;}while(n>=0);return r;};

const SvgUndo=()=><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 10h10a8 8 0 0 1 8 8v2"/><path d="M3 10l6-6M3 10l6 6"/></svg>;
const SvgRedo=()=><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 10H11a8 8 0 0 0-8 8v2"/><path d="M21 10l-6-6m6 6l-6 6"/></svg>;
const SvgBold=()=><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M6 4h8a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"/><path d="M6 12h9a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"/></svg>;
const SvgItalic=()=><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="19" y1="4" x2="10" y2="4"/><line x1="14" y1="20" x2="5" y2="20"/><line x1="15" y1="4" x2="9" y2="20"/></svg>;
const SvgUnderline=()=><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 3v7a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3"/><line x1="4" y1="21" x2="20" y2="21"/></svg>;
const SvgStrike=()=><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="4" y1="12" x2="20" y2="12"/><path d="M17.5 7C17.5 5.067 15.538 3.5 13 3.5S8.5 5.067 8.5 7c0 1.373.97 2.565 2.5 3"/><path d="M6.5 17C6.5 18.933 8.462 20.5 11 20.5s4.5-1.567 4.5-3.5c0-1.373-.97-2.565-2.5-3"/></svg>;
const SvgAlignL=()=><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="18" y2="18"/></svg>;
const SvgAlignC=()=><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="6" y1="12" x2="18" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg>;
const SvgAlignR=()=><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="9" y1="12" x2="21" y2="12"/><line x1="6" y1="18" x2="21" y2="18"/></svg>;
const SvgBorderAll=()=><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="1"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/></svg>;
const SvgBorderOut=()=><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="1"/></svg>;
const SvgWrap=()=><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><path d="M3 12h15a3 3 0 0 1 0 6H8"/><polyline points="10 15 7 18 10 21"/></svg>;

export default function DocAgentSpreadsheet({initialColumns=[],initialSheetData,onSheetsChange,height=500}:Props) {
  const init=():Record<string,Cell>=>{
    if(initialSheetData?.cells) return initialSheetData.cells;
    const c:Record<string,Cell>={};
    initialColumns.forEach((col,i)=>{if(i<COLS)c[ck(0,i)]={value:col.name,style:{bold:true,bgColor:"#eff6ff",fontColor:"#1d4ed8",fontSize:11}};});
    return c;
  };

  const [cells,setCells]=useState<Record<string,Cell>>(init);
  const [colWidths,setColWidths]=useState<number[]>(()=>initialSheetData?.colWidths??Array(COLS).fill(DCW));
  const [merges,setMerges]=useState<Record<string,{rows:number;cols:number}>>(()=>initialSheetData?.merges??{});
  const [selR,setSelR]=useState(0);
  const [selC,setSelC]=useState(0);
  const [rng,setRng]=useState({r1:0,c1:0,r2:0,c2:0});
  const [editR,setEditR]=useState<number|null>(null);
  const [editC,setEditC]=useState<number|null>(null);
  const [editVal,setEditVal]=useState("");
  const [hist,setHist]=useState<Record<string,Cell>[]>([]);
  const [redo,setRedo]=useState<Record<string,Cell>[]>([]);
  const [fcp,setFcp]=useState(false);
  const [bcp,setBcp]=useState(false);
  const inputRef=useRef<HTMLInputElement>(null);
  const mouseDown=useRef(false);

  const notify=useCallback((c:Record<string,Cell>,m:Record<string,{rows:number;cols:number}>,cw:number[])=>{
    if(!onSheetsChange)return;
    const celldata=Object.entries(c).map(([key,cell])=>{const[r,col]=key.split(",").map(Number);return{r,c:col,v:{v:cell.value,s:cell.style}};});
    onSheetsChange([{celldata,merges:m,colWidths:cw,cells:c}]);
  },[onSheetsChange]);

  const cs:CellStyle=useMemo(()=>cells[ck(selR,selC)]?.style??{},[cells,selR,selC]);

  const ph=useCallback(()=>{setHist(h=>[...h.slice(-49),{...cells}]);setRedo([]);},[cells]);

  const upd=useCallback((next:Record<string,Cell>,nm?:Record<string,{rows:number;cols:number}>,ncw?:number[])=>{
    setCells(next);const m=nm??merges,cw=ncw??colWidths;
    if(nm)setMerges(nm);notify(next,m,cw);
  },[merges,colWidths,notify]);

  const applyStyle=useCallback((patch:Partial<CellStyle>)=>{
    ph();
    const r1=Math.min(selR,rng.r2),r2=Math.max(selR,rng.r2);
    const c1=Math.min(selC,rng.c2),c2=Math.max(selC,rng.c2);
    const next={...cells};
    for(let r=r1;r<=r2;r++)for(let c=c1;c<=c2;c++){
      const k=ck(r,c);next[k]={...(next[k]??{value:"",style:{}}),style:{...(next[k]?.style??{}),...patch}};
    }
    upd(next);
  },[cells,selR,selC,rng,ph,upd]);

  const doUndo=useCallback(()=>{
    if(!hist.length)return;setRedo(r=>[...r,cells]);
    const p=hist[hist.length-1];setHist(h=>h.slice(0,-1));setCells(p);notify(p,merges,colWidths);
  },[hist,cells,merges,colWidths,notify]);

  const doRedo=useCallback(()=>{
    if(!redo.length)return;setHist(h=>[...h,cells]);
    const n=redo[redo.length-1];setRedo(r=>r.slice(0,-1));setCells(n);notify(n,merges,colWidths);
  },[redo,cells,merges,colWidths,notify]);

  const commitEdit=useCallback(()=>{
    if(editR===null||editC===null)return;
    ph();const k=ck(editR,editC);
    const next={...cells,[k]:{...(cells[k]??{style:{}}),value:editVal}};
    setEditR(null);setEditC(null);setEditVal("");upd(next);
  },[editR,editC,editVal,cells,ph,upd]);

  const startEdit=useCallback((r:number,c:number,initChar?:string)=>{
    setEditR(r);setEditC(c);
    setEditVal(initChar!==undefined?initChar:(cells[ck(r,c)]?.value??""));
    setTimeout(()=>{
      const inp=inputRef.current;
      if(inp){inp.focus();const len=inp.value.length;inp.setSelectionRange(initChar!==undefined?len:0,len);}
    },0);
  },[cells]);

  const nav=useCallback((dr:number,dc:number)=>{
    const nr=Math.max(0,Math.min(ROWS-1,selR+dr));
    const nc=Math.max(0,Math.min(COLS-1,selC+dc));
    setSelR(nr);setSelC(nc);setRng({r1:nr,c1:nc,r2:nr,c2:nc});
  },[selR,selC]);

  useEffect(()=>{
    const h=(e:KeyboardEvent)=>{
      const a=document.activeElement as HTMLElement;
      if(a&&(a.tagName==="INPUT"||a.tagName==="SELECT"||a.tagName==="TEXTAREA")&&!a.dataset.grid)return;
      if(editR!==null)return;
      if(e.ctrlKey||e.metaKey){
        if(e.key==="z"){e.preventDefault();doUndo();return;}
        if(e.key==="y"){e.preventDefault();doRedo();return;}
        if(e.key==="b"){e.preventDefault();applyStyle({bold:!cs.bold});return;}
        if(e.key==="i"){e.preventDefault();applyStyle({italic:!cs.italic});return;}
        if(e.key==="u"){e.preventDefault();applyStyle({underline:!cs.underline});return;}
        return;
      }
      if(e.key==="ArrowUp"){e.preventDefault();nav(-1,0);}
      else if(e.key==="ArrowDown"){e.preventDefault();nav(1,0);}
      else if(e.key==="ArrowLeft"){e.preventDefault();nav(0,-1);}
      else if(e.key==="ArrowRight"){e.preventDefault();nav(0,1);}
      else if(e.key==="Tab"){e.preventDefault();nav(0,1);}
      else if(e.key==="Enter"){e.preventDefault();nav(1,0);}
      else if(e.key==="F2"){e.preventDefault();startEdit(selR,selC);}
      else if(e.key==="Delete"||e.key==="Backspace"){
        e.preventDefault();ph();
        const r1=Math.min(selR,rng.r2),r2=Math.max(selR,rng.r2),c1=Math.min(selC,rng.c2),c2=Math.max(selC,rng.c2);
        const next={...cells};
        for(let r=r1;r<=r2;r++)for(let c=c1;c<=c2;c++){const k=ck(r,c);if(next[k])next[k]={...next[k],value:""};}
        upd(next);
      }
      else if(e.key.length===1&&!e.ctrlKey&&!e.metaKey){e.preventDefault();startEdit(selR,selC,e.key);}
    };
    window.addEventListener("keydown",h);return()=>window.removeEventListener("keydown",h);
  },[editR,selR,selC,rng,cells,cs,nav,startEdit,applyStyle,doUndo,doRedo,ph,upd]);

  const mergeCells=useCallback(()=>{
    const r1=Math.min(selR,rng.r2),r2=Math.max(selR,rng.r2),c1=Math.min(selC,rng.c2),c2=Math.max(selC,rng.c2);
    if(r1===r2&&c1===c2)return;ph();
    const nm={...merges,[ck(r1,c1)]:{rows:r2-r1+1,cols:c2-c1+1}};
    const next={...cells};
    for(let r=r1;r<=r2;r++)for(let c=c1;c<=c2;c++){
      if(r!==r1||c!==c1)next[ck(r,c)]={...(next[ck(r,c)]??{style:{}}),value:"",mergeParent:[r1,c1]};
    }
    next[ck(r1,c1)]={...(next[ck(r1,c1)]??{style:{}}),value:next[ck(r1,c1)]?.value??"",mergeSpan:{rows:r2-r1+1,cols:c2-c1+1}};
    setSelR(r1);setSelC(c1);setRng({r1,c1,r2:r1,c2:c1});upd(next,nm);
  },[selR,selC,rng,cells,merges,ph,upd]);

  const splitCells=useCallback(()=>{
    const k=ck(selR,selC);if(!merges[k])return;ph();
    const{rows,cols}=merges[k];const nm={...merges};delete nm[k];
    const next={...cells};
    for(let r=selR;r<selR+rows;r++)for(let c=selC;c<selC+cols;c++){
      if(r!==selR||c!==selC){const nc={...(next[ck(r,c)]??{style:{}})};delete nc.mergeParent;next[ck(r,c)]=nc;}
    }
    const nc={...next[k]};delete nc.mergeSpan;next[k]=nc;upd(next,nm);
  },[selR,selC,cells,merges,ph,upd]);

  const startColResize=useCallback((e:React.MouseEvent,c:number)=>{
    e.preventDefault();e.stopPropagation();
    const sx=e.clientX,sw=colWidths[c];
    const mv=(ev:MouseEvent)=>{const nw=Math.max(30,sw+ev.clientX-sx);setColWidths(p=>{const n=[...p];n[c]=nw;return n;});};
    const up=()=>{document.removeEventListener("mousemove",mv);document.removeEventListener("mouseup",up);};
    document.addEventListener("mousemove",mv);document.addEventListener("mouseup",up);
  },[colWidths]);

  const inRange=(r:number,c:number)=>{
    const r1=Math.min(selR,rng.r2),r2=Math.max(selR,rng.r2),c1=Math.min(selC,rng.c2),c2=Math.max(selC,rng.c2);
    return r>=r1&&r<=r2&&c>=c1&&c<=c2;
  };

  const colCount=useMemo(()=>{let n=0;for(let c=0;c<COLS;c++)if(cells[ck(0,c)]?.value?.trim())n++;return n;},[cells]);

  const tb=(active=false):React.CSSProperties=>({
    display:"flex",alignItems:"center",justifyContent:"center",padding:"3px 7px",minWidth:28,height:28,
    borderRadius:5,border:`1px solid ${active?"#4f46e5":"transparent"}`,
    background:active?"#ede9fe":"transparent",color:active?"#4f46e5":"#374151",
    cursor:"pointer",userSelect:"none" as const,transition:"all 0.1s",fontSize:12,fontFamily:"inherit",
  });
  const sep:React.CSSProperties={width:1,height:20,background:"#e5e7eb",margin:"0 3px",flexShrink:0};

  const ColorPicker=({onPick,onClose}:{onPick:(c:string)=>void;onClose:()=>void})=>(
    <div style={{position:"absolute",top:34,left:0,zIndex:200,background:"#fff",border:"1px solid #e5e7eb",borderRadius:8,padding:8,boxShadow:"0 4px 16px rgba(0,0,0,0.12)",display:"grid",gridTemplateColumns:"repeat(8,22px)",gap:3,width:208}}>
      <div onClick={()=>{onPick("");onClose();}} style={{width:22,height:22,background:"#fff",border:"1px solid #ddd",borderRadius:3,cursor:"pointer",display:"flex",alignItems:"center",justifyContent:"center",fontSize:10,color:"#999"}} title="Clear">∅</div>
      {COLORS.map(c=>(
        <div key={c} onClick={()=>{onPick(c);onClose();}}
          style={{width:22,height:22,background:c,borderRadius:3,cursor:"pointer",border:c==="#ffffff"?"1px solid #ddd":"none"}}
          onMouseEnter={e=>(e.currentTarget.style.transform="scale(1.2)")}
          onMouseLeave={e=>(e.currentTarget.style.transform="scale(1)")}
        />
      ))}
    </div>
  );

  return (
    <div style={{height,display:"flex",flexDirection:"column",background:"#fff",userSelect:"none",fontSize:12,fontFamily:"Segoe UI,system-ui,sans-serif"}}
      onClick={()=>{setFcp(false);setBcp(false);}}>

      {/* TOOLBAR */}
      <div style={{flexShrink:0,background:"#f8f9fb",borderBottom:"1px solid #e5e7eb",padding:"4px 8px",display:"flex",alignItems:"center",gap:2,flexWrap:"wrap",minHeight:38}}>
        <button style={tb()} onClick={doUndo} title="Undo (Ctrl+Z)"><SvgUndo/></button>
        <button style={tb()} onClick={doRedo} title="Redo (Ctrl+Y)"><SvgRedo/></button>
        <div style={sep}/>
        <select value={cs.fontFamily??"Arial"} onChange={e=>applyStyle({fontFamily:e.target.value})}
          style={{height:28,border:"1px solid #e5e7eb",borderRadius:5,fontSize:12,padding:"0 4px",background:"#fff",cursor:"pointer",fontFamily:cs.fontFamily??"Arial",minWidth:100}}>
          {FONTS.map(f=><option key={f} style={{fontFamily:f}}>{f}</option>)}
        </select>
        <select value={cs.fontSize??11} onChange={e=>applyStyle({fontSize:parseInt(e.target.value)})}
          style={{height:28,width:54,border:"1px solid #e5e7eb",borderRadius:5,fontSize:12,padding:"0 4px",background:"#fff",cursor:"pointer"}}>
          {SIZES.map(s=><option key={s}>{s}</option>)}
        </select>
        <div style={sep}/>
        <button style={tb(!!cs.bold)} onClick={()=>applyStyle({bold:!cs.bold})} title="Bold (Ctrl+B)"><SvgBold/></button>
        <button style={tb(!!cs.italic)} onClick={()=>applyStyle({italic:!cs.italic})} title="Italic (Ctrl+I)"><SvgItalic/></button>
        <button style={tb(!!cs.underline)} onClick={()=>applyStyle({underline:!cs.underline})} title="Underline (Ctrl+U)"><SvgUnderline/></button>
        <button style={tb(!!cs.strike)} onClick={()=>applyStyle({strike:!cs.strike})} title="Strikethrough"><SvgStrike/></button>
        <div style={sep}/>
        {/* Font color picker */}
        <div style={{position:"relative"}} onClick={e=>e.stopPropagation()}>
          <button style={{...tb(),flexDirection:"column",gap:1}} onClick={()=>{setFcp(v=>!v);setBcp(false);}} title="Font color">
            <span style={{fontSize:13,fontWeight:700,color:cs.fontColor??"#000",lineHeight:1}}>A</span>
            <div style={{width:16,height:3,background:cs.fontColor??"#000",borderRadius:1}}/>
          </button>
          {fcp&&<ColorPicker onPick={c=>applyStyle({fontColor:c||undefined})} onClose={()=>setFcp(false)}/>}
        </div>
        {/* BG color picker */}
        <div style={{position:"relative"}} onClick={e=>e.stopPropagation()}>
          <button style={{...tb(),flexDirection:"column",gap:1}} onClick={()=>{setBcp(v=>!v);setFcp(false);}} title="Fill color">
            <div style={{width:16,height:12,background:cs.bgColor??"#ffff00",border:"1px solid #ccc",borderRadius:2}}/>
            <div style={{width:16,height:3,background:cs.bgColor??"#ffff00",borderRadius:1}}/>
          </button>
          {bcp&&<ColorPicker onPick={c=>applyStyle({bgColor:c||undefined})} onClose={()=>setBcp(false)}/>}
        </div>
        <div style={sep}/>
        <button style={tb(!cs.align||cs.align==="left")} onClick={()=>applyStyle({align:"left"})} title="Align left"><SvgAlignL/></button>
        <button style={tb(cs.align==="center")} onClick={()=>applyStyle({align:"center"})} title="Center"><SvgAlignC/></button>
        <button style={tb(cs.align==="right")} onClick={()=>applyStyle({align:"right"})} title="Align right"><SvgAlignR/></button>
        <div style={sep}/>
        <button style={tb(!!cs.borderAll)} onClick={()=>applyStyle({borderAll:!cs.borderAll,borderOuter:false})} title="All borders"><SvgBorderAll/></button>
        <button style={tb(!!cs.borderOuter)} onClick={()=>applyStyle({borderOuter:!cs.borderOuter,borderAll:false})} title="Outer border"><SvgBorderOut/></button>
        <div style={sep}/>
        <button style={tb()} onClick={mergeCells} title="Merge cells"><span style={{fontSize:11,fontWeight:500}}>Merge</span></button>
        <button style={tb()} onClick={splitCells} title="Split merged cell"><span style={{fontSize:11,fontWeight:500}}>Split</span></button>
        <div style={sep}/>
        <button style={tb(!!cs.wrap)} onClick={()=>applyStyle({wrap:!cs.wrap})} title="Wrap text"><SvgWrap/></button>
        <button style={{...tb(),color:"#6b7280",fontSize:11,marginLeft:4}} title="Clear all formatting"
          onClick={()=>applyStyle({bold:false,italic:false,underline:false,strike:false,fontColor:undefined,bgColor:undefined,align:undefined,borderAll:false,borderOuter:false,wrap:false,fontSize:11,fontFamily:undefined})}>
          Clear
        </button>
      </div>

      {/* FORMULA BAR */}
      <div style={{flexShrink:0,display:"flex",alignItems:"center",borderBottom:"1px solid #e5e7eb",background:"#fff",height:28}}>
        <div style={{width:72,textAlign:"center",borderRight:"1px solid #e5e7eb",fontSize:12,fontWeight:600,color:"#374151",height:"100%",display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}>
          {cl(selC)}{selR+1}
        </div>
        <div style={{width:32,borderRight:"1px solid #e5e7eb",height:"100%",display:"flex",alignItems:"center",justifyContent:"center",color:"#9ca3af",fontSize:13,fontStyle:"italic",flexShrink:0}}>ƒx</div>
        <div style={{flex:1,padding:"0 10px",fontSize:12,color:"#374151",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",display:"flex",alignItems:"center"}}>
          {editR!==null?editVal:(cells[ck(selR,selC)]?.value??"")}
        </div>
      </div>

      {/* GRID */}
      <div style={{flex:1,overflow:"auto"}} onMouseUp={()=>{mouseDown.current=false;}}>
        <table style={{borderCollapse:"collapse",tableLayout:"fixed",minWidth:"max-content"}}>
          <thead>
            <tr>
              <th style={{width:RHW,minWidth:RHW,height:CHH,background:"#f1f3f9",border:"1px solid #d1d5db",position:"sticky",top:0,left:0,zIndex:20}}/>
              {Array.from({length:COLS},(_,c)=>(
                <th key={c} style={{width:colWidths[c],minWidth:colWidths[c],height:CHH,background:"#f1f3f9",border:"1px solid #d1d5db",fontSize:11,fontWeight:600,color:"#6b7280",textAlign:"center",position:"sticky",top:0,zIndex:10,userSelect:"none",cursor:"pointer"}}
                  onClick={()=>{setSelR(0);setSelC(c);setRng({r1:0,c1:c,r2:ROWS-1,c2:c});}}>
                  <div style={{position:"relative",display:"flex",alignItems:"center",justifyContent:"center",height:"100%"}}>
                    {cl(c)}
                    <div onMouseDown={e=>startColResize(e,c)} style={{position:"absolute",right:0,top:0,width:5,height:"100%",cursor:"col-resize",zIndex:5}}/>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({length:ROWS},(_,r)=>(
              <tr key={r}>
                <td style={{width:RHW,minWidth:RHW,height:DRH,background:r===0?"#e8edff":"#f1f3f9",border:"1px solid #d1d5db",fontSize:r===0?10:11,color:r===0?"#4f46e5":"#6b7280",textAlign:"center",position:"sticky",left:0,zIndex:5,cursor:"pointer",userSelect:"none",fontWeight:r===0?700:400}}
                  onClick={()=>{setSelR(r);setSelC(0);setRng({r1:r,c1:0,r2:r,c2:COLS-1});}}>
                  {r===0?"HDR":r+1}
                </td>
                {Array.from({length:COLS},(_,c)=>{
                  const k=ck(r,c);const cell=cells[k];
                  if(cell?.mergeParent)return null;
                  const span=merges[k];const cs2=span?.cols??1,rs2=span?.rows??1;
                  const s=cell?.style??{};
                  const isEdit=editR===r&&editC===c;
                  const isSel=selR===r&&selC===c;
                  const ir=inRange(r,c);
                  const isHdr=r===0;
                  const tw=Array.from({length:cs2},(_,i)=>colWidths[c+i]??DCW).reduce((a,b)=>a+b,0);
                  const bg=s.bgColor??(isHdr?"#f0f4ff":ir?"rgba(79,70,229,0.06)":"#fff");
                  const bd=isSel?"2px solid #4f46e5":ir?"1px solid #a5b4fc":isHdr?"1px solid #c7d2fe":"1px solid #e5e7eb";
                  const finalBd=s.borderAll?"1px solid #374151":bd;
                  const ff=s.fontFamily??"Segoe UI,system-ui,sans-serif";
                  const fs=s.fontSize??(isHdr?11:11);
                  const fw=s.bold||isHdr?"600":"normal";
                  const fc=s.fontColor??(isHdr?"#1d4ed8":"#111827");
                  const td2=[s.underline&&"underline",s.strike&&"line-through"].filter(Boolean).join(" ")||"none";
                  return(
                    <td key={c} colSpan={cs2} rowSpan={rs2}
                      style={{width:tw,minWidth:tw,height:DRH,background:bg,border:finalBd,padding:0,cursor:"cell",position:"relative",verticalAlign:"middle"}}
                      onClick={e=>{if(e.shiftKey){setRng(p=>({...p,r2:r,c2:c}));}else{setSelR(r);setSelC(c);setRng({r1:r,c1:c,r2:r,c2:c});}}}
                      onDoubleClick={()=>startEdit(r,c)}
                      onMouseDown={e=>{if(e.button!==0)return;mouseDown.current=true;setSelR(r);setSelC(c);setRng({r1:r,c1:c,r2:r,c2:c});}}
                      onMouseEnter={()=>{if(mouseDown.current)setRng(p=>({...p,r2:r,c2:c}));}}
                    >
                      {isEdit?(
                        <input ref={inputRef} data-grid="true" value={editVal} onChange={e=>setEditVal(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={e=>{
                            if(e.key==="Enter"){e.preventDefault();commitEdit();nav(1,0);}
                            else if(e.key==="Tab"){e.preventDefault();commitEdit();nav(0,1);}
                            else if(e.key==="Escape"){setEditR(null);setEditC(null);setEditVal("");}
                          }}
                          style={{width:"100%",height:"100%",border:"none",outline:"none",padding:"0 6px",fontFamily:ff,fontSize:`${fs}px`,fontWeight:fw,fontStyle:s.italic?"italic":"normal",textDecoration:td2,background:"transparent",color:fc,textAlign:s.align??"left"}}
                        />
                      ):(
                        <div style={{padding:"0 6px",fontFamily:ff,fontSize:`${fs}px`,fontWeight:fw,fontStyle:s.italic?"italic":"normal",textDecoration:td2,color:fc,textAlign:s.align??"left",whiteSpace:s.wrap?"normal":"nowrap",overflow:"hidden",textOverflow:s.wrap?"clip":"ellipsis",height:"100%",display:"flex",alignItems:"center",justifyContent:s.align==="center"?"center":s.align==="right"?"flex-end":"flex-start"}}>
                          {cell?.value??""}
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* STATUS BAR */}
      <div style={{flexShrink:0,height:24,background:"#f8f9fb",borderTop:"1px solid #e5e7eb",display:"flex",alignItems:"center",padding:"0 12px",fontSize:11,color:"#9ca3af",gap:16}}>
        <span style={{color:"#6b7280",fontWeight:500}}>{cl(selC)}{selR+1}</span>
        <span>Row 1 = column headers</span>
        <span style={{marginLeft:"auto",color:colCount>0?"#059669":"#9ca3af",fontWeight:colCount>0?600:400}}>
          {colCount} column{colCount!==1?"s":""} defined
        </span>
      </div>
    </div>
  );
}
