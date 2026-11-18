import React, {useCallback,useEffect,useMemo,useState} from 'react';
import {Activity,AlertTriangle,CheckCircle2,Clock3,Database,FileClock,
  GlobeLock,Layers,Network,Play,RefreshCw,RotateCw,Search,Server,
  ShieldCheck,Square,X} from 'lucide-react';
import './ops-extras.css';

const tabs=[
  {id:'postgres',label:'PostgreSQL',icon:Database},
  {id:'systemd',label:'Servicios systemd',icon:Server},
  {id:'trends',label:'Métricas históricas',icon:Activity},
  {id:'tls',label:'Certificados TLS',icon:GlobeLock},
];
function Note({children,error=false}){return <div className={'oe-note '+(error?'oe-note-error':'')}><AlertTriangle size={17}/>{children}</div>;}
function Status({value,positive}){return <span className={'oe-status '+(positive?'good':'warn')}>{value}</span>;}
function Trace({items,keyName,color,maxY}){
  if(items.length<2)return <div className="oe-chart-empty">Todavía no hay suficientes muestras. HomeLab OS registra estadísticas cada minuto.</div>;
  const w=600,h=150,pad=8;
  const path=items.map((x,i)=> {
    const xx=pad+(i/(items.length-1))*(w-2*pad);
    const yy=h-pad-(Math.min(maxY,Math.max(0,Number(x[keyName])||0))/maxY)*(h-2*pad);
    return (i?'L':'M')+xx.toFixed(1)+' '+yy.toFixed(1);
  }).join(' ');
  return <svg viewBox="0 0 600 150" preserveAspectRatio="none" className="oe-chart" role="img" aria-label={'Evolución '+keyName}>
    {[0,1,2,3,4].map(i=><line key={i} x1="0" y1={pad+(h-2*pad)/4*i} x2="600" y2={pad+(h-2*pad)/4*i} stroke="#304047" strokeDasharray="3 6"/>)}
    <path d={path} fill="none" stroke={color} strokeWidth="2.8" strokeLinejoin="round" strokeLinecap="round"/>
  </svg>;
}

export default function OpsExtras({request,csrf}) {
  const [tab,setTab]=useState('postgres');
  const [data,setData]=useState(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(false);
  const [phrase,setPhrase]=useState('');
  const [action,setAction]=useState(null);
  const [running,setRunning]=useState(false);
  const [toast,setToast]=useState('');
  const [container,setContainer]=useState('');
  const [candidates,setCandidates]=useState([]);
  const [hours,setHours]=useState(24);
  const [history,setHistory]=useState([]);
  const [loadingTrend,setLoadingTrend]=useState(false);
  const [search,setSearch]=useState('');

  const refresh=useCallback(async()=>{
    setLoading(true);
    try {
      const endpoint=tab==='postgres'?'/api/extras/postgres':
          tab==='systemd'?'/api/extras/systemd':
          tab==='tls'?'/api/extras/tls':'/api/docker/inventory';
      const r=await request(endpoint);
      setData(r);setError('');
      if(tab==='trends'){
        const list=r.containers||[];
        setCandidates(list);
        setContainer(prev=>list.some(c=>c.name===prev)?prev:(list[0]?.name||''));
      }
    } catch(e){setError(e.message||'Error de consulta');}
    finally{setLoading(false);}
  },[tab,request]);

  useEffect(()=>{setData(null);setError('');refresh();},[refresh]);
  useEffect(()=>{
    if(tab!=='trends'||!container)return;
    let cancelled=false;
    setLoadingTrend(true);
    request('/api/extras/containers/'+encodeURIComponent(container)+'/history?hours='+hours)
      .then(r=>{if(!cancelled)setHistory(r.items||[]);})
      .catch(e=>{if(!cancelled)setError(e.message);})
      .finally(()=>{if(!cancelled)setLoadingTrend(false);});
    return ()=>{cancelled=true;};
  },[tab,container,hours,request]);

  async function execute(){
    if(!action)return;
    setRunning(true);setError('');
    try {
      const r=await request('/api/extras/systemd/user/'+encodeURIComponent(action.name)+'/'+action.type,
        {method:'POST',body:JSON.stringify({confirm:true,confirmation_text:phrase})},csrf);
      if(!r.ok)throw Error(r.error||'Error de systemd');
      setToast('Operación aplicada a '+action.name);
      setAction(null);setPhrase('');
      await refresh();
    }catch(e){setError(e.message||'No se pudo ejecutar');}
    finally{setRunning(false);}
  }
  const filtered=useMemo(()=>{
    if(tab!=='systemd')return [];
    return (data?.groups||[]).flatMap(g=>(g.items||[]).map(x=>({...x,scope:g.scope})))
      .filter(x=>[x.name,x.description,x.active,x.scope].join(' ').toLowerCase().includes(search.toLowerCase()));
  },[data,tab,search]);
  const maxY=Math.max(100,...history.map(x=>Number(x.cpu_percent)||0));
  const current=history.at(-1);

  return <div className="oe-root">
    <div className="oe-heading">
      <div><div className="eyebrow">INFRAESTRUCTURA · HOME LAB</div>
        <h2>Servicios y diagnósticos</h2>
        <p>PostgreSQL, systemd, históricos Docker y certificados TLS en un solo lugar.</p></div>
      <button className="oe-btn" disabled={loading} onClick={refresh}><RefreshCw size={16} className={loading?'spin':''}/>{loading?'Consultando…':'Actualizar'}</button>
    </div>
    {error&&<Note error>{error}</Note>}
    {toast&&<div className="oe-success"><CheckCircle2 size={16}/>{toast}<button onClick={()=>setToast('')}><X size={15}/></button></div>}
    <section className="oe-panel">
      <div className="oe-tabs" role="tablist">{tabs.map(({id,label,icon:Icon})=>
        <button key={id} role="tab" aria-selected={tab===id} className={tab===id?'selected':''}
                onClick={()=>{setTab(id);setSearch('');}}><Icon size={16}/>{label}</button>)}</div>
      {loading&&!data&&<div className="oe-empty">Consultando el agente y los servicios…</div>}
      {tab==='postgres'&&data&&<div className="oe-content">
        <div className="oe-intro"><h3>Disponibilidad de PostgreSQL</h3>
          <p>Detección automática por imagen Docker. Se utiliza <code>pg_isready</code> dentro del contenedor; no se solicitan contraseñas ni se ejecutan consultas SQL.</p></div>
        {!data.available?<Note error>{data.error||'Docker no disponible'}</Note>:data.items?.length?
        <div className="oe-tiles">{data.items.map(x=><div className="oe-tile" key={x.container}>
          <div className="oe-tile-title"><Database size={19}/><strong>{x.container}</strong></div>
          <div><Status positive={x.status==='accepting'} value={x.status==='accepting'?'Acepta conexiones':x.status==='stopped'?'Detenido':x.status==='rejecting'?'No acepta conexiones':'No verificable'}/></div>
          <span>Proyecto: {x.project||'Independiente'}</span>
          {x.note&&<small>{x.note}</small>}
        </div>)}</div>:<div className="oe-empty">No se detectaron contenedores PostgreSQL por nombre de imagen. Los servicios no detectados no se consideran saludables.</div>}
      </div>}
      {tab==='systemd'&&data&&<div className="oe-content">
        <div className="oe-intro"><h3>Servicios systemd</h3>
          <p>Estado de servicios del sistema y de tu sesión. Solo puedes iniciar, detener o reiniciar unidades de usuario incluidas en <code>HOMELAB_ALLOWED_SYSTEMD_UNITS</code>.</p></div>
        <label className="oe-search"><Search size={16}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Filtrar unidades por nombre o descripción…"/></label>
        <div className="oe-table-scroll"><table className="oe-table"><thead><tr><th>Servicio</th><th>Ámbito</th><th>Estado</th><th>Acciones</th></tr></thead>
          <tbody>{filtered.slice(0,200).map(x=><tr key={x.scope+':'+x.name}>
            <td><strong>{x.name}</strong><small>{x.description}</small></td>
            <td>{x.scope==='user'?'Usuario':'Sistema'}</td>
            <td><Status positive={x.active==='active'} value={x.active+' / '+x.sub}/></td>
            <td>{x.manageable?<div className="oe-ops">
              {['start','stop','restart'].map(type=><button key={type} title={type} disabled={running}
                onClick={()=>{setAction({name:x.name,type});setPhrase('');}}>
                {type==='start'?<Play size={15}/>:type==='stop'?<Square size={15}/>:<RotateCw size={15}/>}</button>)}
            </div>:<span className="oe-readonly">Solo lectura</span>}</td>
          </tr>)}{filtered.length===0&&<tr><td colSpan="4" className="oe-empty">No se encontraron unidades con ese criterio.</td></tr>}</tbody>
        </table></div>
        {(data.groups||[]).filter(g=>!g.available).map(g=><Note error key={g.scope}>No se pudo consultar systemd {g.scope}: {g.error}</Note>)}
      </div>}
      {tab==='trends'&&data&&<div className="oe-content">
        <div className="oe-intro"><h3>Evolución de recursos Docker</h3>
          <p>Muestras periódicas guardadas en SQLite cada minuto, incluso cuando el dashboard no está abierto. Retención de 30 días.</p></div>
        <div className="oe-trend-controls">
          <label>Contenedor<select value={container} onChange={e=>setContainer(e.target.value)}>{candidates.map(c=><option key={c.name} value={c.name}>{c.name}</option>)}</select></label>
          <label>Periodo<select value={hours} onChange={e=>setHours(Number(e.target.value))}>
            <option value={1}>1 hora</option><option value={6}>6 horas</option><option value={24}>24 horas</option>
            <option value={168}>7 días</option><option value={720}>30 días</option>
          </select></label>
        </div>
        {loadingTrend?<div className="oe-empty">Consultando historial…</div>:<>
          <div className="oe-chart-card"><div className="oe-chart-title"><strong>CPU</strong><span>{current?current.cpu_percent+'%':'—'}</span></div><Trace items={history} keyName="cpu_percent" color="#74e7c4" maxY={maxY}/></div>
          <div className="oe-chart-card"><div className="oe-chart-title"><strong>Memoria</strong><span>{current?current.mem_percent+'%':'—'}</span></div><Trace items={history} keyName="mem_percent" color="#8daeff" maxY={100}/></div>
          <small className="oe-muted">{history.length} muestras en el periodo · CPU puede superar el 100% en múltiples núcleos</small>
        </>}
      </div>}
      {tab==='tls'&&data&&<div className="oe-content">
        <div className="oe-intro"><h3>Certificados TLS</h3>
          <p>Vencimiento, emisor y confianza de los certificados HTTPS configurados. No se leen claves privadas ni se renuevan certificados automáticamente.</p></div>
        {data.configured? <div className="oe-tiles">{(data.items||[]).map(x=><div className="oe-tile" key={x.host+':'+x.port}>
          <div className="oe-tile-title"><GlobeLock size={20}/><strong>{x.name}</strong></div>
          <div><Status positive={x.available&&x.trusted&&x.days_remaining>30}
            value={!x.available?'Sin respuesta':!x.trusted?'Cadena no confiable':x.days_remaining<=0?'Vencido':x.days_remaining<=30?'Por vencer':'Válido'}/></div>
          <span>{x.host}:{x.port}</span>
          <span>{x.days_remaining==null?'Vencimiento no disponible':x.days_remaining+' días restantes'}</span>
          {x.expires_at&&<small>Hasta: {new Date(x.expires_at).toLocaleDateString('es-CR')}</small>}
          {x.issuer&&<small title={x.issuer}>Emisor: {x.issuer}</small>}
          {x.error&&<small>{x.error}</small>}
        </div>)}</div>:<div className="oe-empty">No hay endpoints HTTPS configurados. HomeLab OS detecta los servicios con URL https:// en config/services.json y los dominios de config/tls_endpoints.json.</div>}
      </div>}
    </section>
    <div className="oe-foot"><ShieldCheck size={16}/> Los diagnósticos son de solo lectura. Las operaciones systemd necesitan una lista autorizada y confirmación escrita.</div>
    {action&&<div className="oe-overlay" onMouseDown={e=>e.target===e.currentTarget&&setAction(null)}>
      <div className="oe-modal" role="dialog" aria-modal="true" aria-label="Confirmar operación de systemd">
        <AlertTriangle size={26}/><h3>{action.type.toUpperCase()} {action.name}</h3>
        <p>Esta operación modificará el estado de un servicio de tu sesión de usuario. Confirma escribiendo la frase exacta:</p>
        <label><strong>{action.type.toUpperCase()} {action.name}</strong>
          <input autoComplete="off" value={phrase} onChange={e=>setPhrase(e.target.value)}/></label>
        <div className="oe-modal-buttons"><button onClick={()=>setAction(null)} className="oe-btn">Cancelar</button>
          <button disabled={running||phrase!==action.type.toUpperCase()+' '+action.name} className="oe-btn oe-danger" onClick={execute}>Aplicar</button></div>
      </div>
    </div>}
  </div>;
}
