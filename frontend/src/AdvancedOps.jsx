import React, {useEffect,useMemo,useState,useCallback} from 'react';
import {Activity,AlertTriangle,ArrowDownRight,ArrowRight,Box,CheckCircle2,
 Clock3,Database,Download,HardDrive,HeartPulse,Layers,RefreshCw,
 Server,ShieldAlert,ShieldCheck,TrendingUp,X} from 'lucide-react';
import './advanced-ops.css';

function Status({state}) {
 const name={healthy:'Saludable',degraded:'Degradado',critical:'Crítico',
 down:'Detenido',unknown:'Desconocido'}[state]||state;
 return <span className={'ao-status ao-'+state}>{name}</span>;
}
function SmallPlot({items,keyName,color='#80d5bb'}) {
 if(items.length<2)return <div className="ao-empty">Se necesitan más muestras para mostrar el historial.</div>;
 const points=items.map((x,i)=>{
   const v=Number(x[keyName])||0;
   const max=Math.max(100,...items.map(y=>Number(y[keyName])||0));
   return (i?'L':'M')+(12+i*(596/Math.max(1,items.length-1))).toFixed(2)+' '+
      (141-Math.min(1,v/max)*128).toFixed(2);
 }).join(' ');
 return <svg viewBox="0 0 620 154" preserveAspectRatio="none" role="img" aria-label={'Evolución '+keyName} className="ao-plot">
   {[0,1,2,3,4].map(n=><line key={n} x1={0} x2={620} y1={15+n*30} y2={15+n*30} stroke="#334954" strokeDasharray="3 7"/>)}
   <path d={points} stroke={color} strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
 </svg>;
}
export default function AdvancedOps({request,csrf,mode='health'}) {
 const [overview,setOverview]=useState(null);
 const [history,setHistory]=useState([]);
 const [period,setPeriod]=useState(168);
 const [error,setError]=useState('');
 const [loading,setLoading]=useState(false);
 const [containers,setContainers]=useState([]);
 const [name,setName]=useState('');
 const [plan,setPlan]=useState(null);
 const [typed,setTyped]=useState('');
 const [jobs,setJobs]=useState([]);
 const [notice,setNotice]=useState('');
 const reload=useCallback(async()=>{
    setLoading(true);setError('');
    try {
      if(mode==='health')setOverview(await request('/api/observability/overview'));
      if(mode==='analytics'){
        const result=await request('/api/observability/trends/host?hours='+period);
        setHistory(result.items||[]);
      }
      if(mode==='images'){
        const [inv,job]=await Promise.all([
          request('/api/docker/inventory'),request('/api/image-updates/jobs')]);
        setContainers((inv.containers||[]).filter(c=>(c.allowed_actions||[]).length));
        setJobs(job.items||[]);
      }
    }catch(e){setError(e.message||'No fue posible consultar la infraestructura');}
    finally{setLoading(false);}
 },[request,mode,period]);
 useEffect(()=>{reload();},[reload]);
 useEffect(()=>{
   if(mode!=='images')return;
   const interval=setInterval(async()=>{
      try{const r=await request('/api/image-updates/jobs');setJobs(r.items||[]);}catch(e){}
   },10000);
   return ()=>clearInterval(interval);
 },[request,mode]);
 const graph=overview?.topology||{nodes:[],links:[]};
 const groups=useMemo(()=>{
   const projects=graph.nodes.filter(n=>n.type==='project');
   const containers=graph.nodes.filter(n=>n.type==='container');
   return [...projects.map(p=>({project:p,children:containers.filter(c=>c.project===p.label)})),
           {project:{id:'unassigned',label:'Independientes',state:'unknown'},
            children:containers.filter(c=>!c.project)}].filter(g=>g.children.length);
 },[graph]);
 const forecast=useMemo(()=>{
   if(history.length<12)return null;
   const span=(history.at(-1).timestamp-history[0].timestamp)/3600;
   if(span<12)return null;
   let data={};
   for(const key of ['cpu','memory','disk']){
     const count=Math.max(3,Math.floor(history.length/5));
     const first=history.slice(0,count).reduce((s,x)=>s+(Number(x[key])||0),0)/count;
     const last=history.slice(-count).reduce((s,x)=>s+(Number(x[key])||0),0)/count;
     data[key]={current:last,projected:Math.min(100,Math.max(0,last+(last-first)*24/span)),
       drift:(last-first)*24/span};
   }
   return data;
 },[history]);
 async function preview(container){
   setName(container);setTyped('');setPlan(null);setError('');setNotice('');
   try{setPlan(await request('/api/image-updates/'+encodeURIComponent(container)+'/preview'));}
   catch(e){setError(e.message||'No se puede comprobar esta imagen');}
 }
 async function confirm(){
   if(!plan||typed!==plan.confirmation_phrase)return;
   setLoading(true);setError('');
   try{
     await request('/api/image-updates/'+encodeURIComponent(name)+'/pull',{
       method:'POST',body:JSON.stringify({confirm:true,confirmation_text:typed,
       running_image_id:plan.running_image_id})},csrf);
     setPlan(null);setTyped('');
     setNotice('Descarga iniciada. El contenedor activo no se modificará.');
     const r=await request('/api/image-updates/jobs');setJobs(r.items||[]);
   }catch(e){setError(e.message||'No se pudo autorizar la descarga');}
   finally{setLoading(false);}
 }
 return <div className="ao-root">
  <header className="ao-header">
   <div><div className="eyebrow">HOMELAB OS · v0.6.5</div>
    <h2>{mode==='health'?'Salud global y topología':mode==='images'?'Imágenes Docker':'Históricos y tendencias'}</h2>
    <p>{mode==='health'?'Estado consolidado y mapa de proyectos Compose; dependencias indicativas.':
    mode==='images'?'Descarga supervisada de imágenes. No reemplaza ni reinicia automáticamente servicios.':
    'Historial de CPU, memoria y disco; proyecciones orientativas de 24 horas.'}</p></div>
   <button className="ao-button" onClick={reload} disabled={loading}><RefreshCw size={16}/> Actualizar</button>
  </header>
  {error&&<div className="ao-note ao-danger"><AlertTriangle size={17}/>{error}</div>}
  {notice&&<div className="ao-note"><CheckCircle2 size={17}/>{notice}</div>}
  {mode==='health'&&<>{overview&&<>
   <div className="ao-kpis">
    <div><small>Estado global</small><Status state={overview.health.status}/><span>{overview.health.verified_sources} fuentes verificadas</span></div>
    <div><small>Contenedores activos</small><strong>{overview.counts.running}/{overview.counts.containers}</strong><span>Docker</span></div>
    <div><small>PostgreSQL detectados</small><strong>{overview.counts.postgres}</strong><span>Verificados mediante pg_isready</span></div>
    <div><small>Incidentes abiertos</small><strong>{overview.counts.incidents}</strong><span>Según el monitor de alertas</span></div>
   </div>
   <section className="ao-panel"><div className="ao-panel-title"><h3><HeartPulse size={18}/> Problemas que requieren atención</h3></div>
    {(overview.health.findings||[]).length?
     <div className="ao-findings">{overview.health.findings.map((x,i)=><div key={i}>
       <AlertTriangle size={16}/><span>{x.title}</span><span className="ao-muted">{x.severity}</span>
     </div>)}</div>:
     <div className="ao-empty"><CheckCircle2 size={22}/> Sin hallazgos en las fuentes disponibles.</div>}
    <small className="ao-footnote">{overview.health.notes}</small>
   </section>
   <section className="ao-panel"><div className="ao-panel-title"><h3><Layers size={18}/> Topología de proyectos Compose</h3>
    <p>Las relaciones son descriptivas; no se utilizan para operar contenedores.</p></div>
    {groups.length?<div className="ao-topology">
     {groups.map(group=><article key={group.project.id} className="ao-project">
       <header><Layers size={16}/><strong>{group.project.label}</strong><Status state={group.project.state}/></header>
       <div className="ao-containers">
        {group.children.map(c=><div key={c.id} className="ao-container">
         <Box size={16}/><div><strong>{c.label}</strong><small>{c.image}</small></div>
         <Status state={c.state}/></div>)}
       </div>
       {graph.links.filter(x=>x.inferred&&group.children.some(c=>c.id===x.source)).length>0&&
        <div className="ao-dependencies"><strong>Posibles dependencias (inferidas)</strong>
         {graph.links.filter(x=>x.inferred&&group.children.some(c=>c.id===x.source)).slice(0,15).map((e,i)=>
          <div key={i}><span>{e.source.replace('container:','')}</span><ArrowRight size={14}/>
           <span>{e.target.replace('container:','')}</span></div>)}
        </div>}
      </article>)}
    </div>:<div className="ao-empty">No se encontraron contenedores o Docker está desconectado.</div>}
    <small className="ao-footnote">{graph.note}</small>
   </section>
   <section className="ao-panel"><div className="ao-panel-title"><h3><ShieldCheck size={18}/> Cobertura de fuentes</h3></div>
    <div className="ao-source-list">{Object.entries(overview.sources||{}).map(([key,value])=><div key={key}>
     <span>{key}</span><Status state={value?'healthy':'unknown'}/></div>)}</div>
   </section>
  </>}</>}
  {mode==='analytics'&&<>
   <section className="ao-panel">
    <div className="ao-panel-title"><h3><Activity size={18}/> Datos históricos</h3>
     <select value={period} onChange={e=>setPeriod(Number(e.target.value))}>
      {[1,6,24,168,720].map(n=><option key={n} value={n}>{n===720?'30 días':n===168?'7 días':n+' horas'}</option>)}
     </select></div>
    {[['cpu','CPU','#7bd8b6'],['memory','Memoria','#97b0f8'],['disk','Disco','#edc690']].map(([key,label,color])=>
     <div className="ao-chart" key={key}><header><strong>{label}</strong><span>
      {history.length?Number(history.at(-1)[key]).toFixed(1)+'%':'Sin datos'}</span></header>
      <SmallPlot items={history} keyName={key} color={color}/></div>)}
    <small className="ao-footnote">{history.length} intervalos agregados. Los datos se retienen hasta 30 días. La recolección continúa cada cinco minutos sin necesidad de abrir el navegador.</small>
   </section>
   <section className="ao-panel"><div className="ao-panel-title"><h3><TrendingUp size={18}/> Tendencia de las próximas 24 horas</h3></div>
    {forecast?<div className="ao-projections">{Object.entries(forecast).map(([key,item])=>
     <div key={key}><small>{key==='cpu'?'CPU':key==='memory'?'Memoria':'Disco'}</small>
      <strong>{item.projected.toFixed(1)}%</strong>
      <span>{item.drift>=0?'+':''}{item.drift.toFixed(1)} puntos / 24h</span>
     </div>)}</div>:<div className="ao-empty">Se necesitan al menos 12 horas de historial y 12 intervalos de datos.</div>}
    <small className="ao-footnote">Extrapolación lineal indicativa, no pronóstico de machine learning. No activa cambios automáticos.</small>
   </section>
  </>}
  {mode==='images'&&<>
   <div className="ao-note"><ShieldCheck size={17}/> Por seguridad, solo se pueden descargar imágenes de contenedores autorizados en HOMELAB_ALLOWED_CONTAINERS. Descargar una imagen NO actualiza el contenedor; deberás planificar su recreación mediante Docker Compose.</div>
   <section className="ao-panel"><div className="ao-panel-title"><h3><Download size={18}/> Seleccionar contenedor</h3></div>
    {containers.length?containers.map(c=><div className="ao-image-row" key={c.name}>
     <div><strong>{c.name}</strong><small>{c.image} · {c.state}</small></div>
     <button className="ao-button" disabled={loading} onClick={()=>preview(c.name)}>Revisar descarga</button>
    </div>):<div className="ao-empty">No hay contenedores autorizados. Configura HOMELAB_ALLOWED_CONTAINERS y reinstala el agente.</div>}
   </section>
   <section className="ao-panel"><div className="ao-panel-title"><h3><Clock3 size={18}/> Historial de descargas de esta sesión</h3></div>
    {jobs.length?jobs.map(job=><div className="ao-image-row" key={job.id}>
     <div><strong>{job.container} · {job.image}</strong>
      <small>{job.state==='success'?job.changed?'Nueva versión descargada; falta recrear el contenedor':'La etiqueta no cambió':
      job.state==='failed'?'Falló: '+job.error:'Descarga en progreso'}</small></div>
     <Status state={job.state==='success'?'healthy':job.state==='failed'?'critical':'unknown'}/>
    </div>):<div className="ao-empty">Todavía no hay descargas registradas desde este arranque del agente.</div>}
   </section>
  </>}
  {plan&&<div className="ao-modal-backdrop" onClick={e=>{if(e.target===e.currentTarget)setPlan(null)}}>
   <div className="ao-modal" role="dialog" aria-modal="true" aria-label="Confirmar descarga Docker">
    <div className="ao-panel-title"><h3>Descargar imagen de {name}</h3>
     <button onClick={()=>setPlan(null)} aria-label="Cerrar"><X size={18}/></button></div>
    <p>Imagen: <strong>{plan.image}</strong></p>
    <p>ID ejecutándose: <code>{plan.running_image_id?.slice(0,24)}…</code></p>
    <p>Docker puede descargar una versión más reciente de esta etiqueta. El contenedor actual permanecerá intacto. Antes de desplegarla revisa compatibilidad y respaldos.</p>
    <label>Escribe <strong>{plan.confirmation_phrase}</strong>
     <input autoComplete="off" value={typed} onChange={e=>setTyped(e.target.value)} /></label>
    <div className="ao-modal-actions"><button className="ao-button" onClick={()=>setPlan(null)}>Cancelar</button>
     <button className="ao-button ao-primary" disabled={typed!==plan.confirmation_phrase||loading}
      onClick={confirm}>Autorizar descarga</button></div>
   </div>
  </div>}
 </div>;
}
