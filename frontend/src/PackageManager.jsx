import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, FileClock, ListChecks,
  Package, RefreshCw, Search, Shield, Terminal, X } from 'lucide-react';
import './package-manager.css';

const groups = [
  {key:'dnf',label:'DNF / RPM',phrase:'ACTUALIZAR DNF',hint:'Paquetes del sistema Fedora'},
  {key:'flatpak_user',label:'Flatpak personal',phrase:'ACTUALIZAR FLATPAK USUARIO',hint:'Aplicaciones instaladas en tu cuenta'},
  {key:'flatpak_system',label:'Flatpak sistema',phrase:'ACTUALIZAR FLATPAK SISTEMA',hint:'Aplicaciones compartidas del equipo'},
];
const kinds = {dnf:'dnf',flatpak_user:'flatpak-user',flatpak_system:'flatpak-system'};
const jobNames = {'dnf':'DNF', 'flatpak-user':'Flatpak personal', 'flatpak-system':'Flatpak sistema'};

function Result({type,children}) {
  return <div className={'pm-notice '+(type==='error'?'pm-error':'pm-ok')}>
    {type==='error'?<AlertTriangle size={16}/>:<CheckCircle2 size={16}/>}<span>{children}</span>
  </div>;
}

export default function PackageManager({request, csrf}) {
  const [data,setData] = useState(null);
  const [active,setActive] = useState('dnf');
  const [view,setView] = useState('updates');
  const [search,setSearch] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [approval,setApproval] = useState(null);
  const [typed,setTyped] = useState('');
  const [jobs,setJobs] = useState([]);
  const [message,setMessage] = useState('');
  const [jobBusy,setJobBusy] = useState(false);

  const refresh = useCallback(async (fresh=false)=>{
    setBusy(true);
    try {
      const result = await request('/api/packages/status'+(fresh?'?refresh=true':''));
      setData(result);setError('');
    } catch(e) {setError(e.message);}
    finally {setBusy(false);}
  },[request]);

  const loadJobs = useCallback(async ()=>{
    try {const r=await request('/api/packages/jobs');setJobs(r.items||[]);}
    catch(_) { /* retain last known jobs */ }
  },[request]);

  useEffect(()=>{
    refresh();loadJobs();
    const tick=setInterval(loadJobs,5000);
    return ()=>clearInterval(tick);
  },[refresh,loadJobs]);

  const selected=groups.find(g=>g.key===active);
  const detail=data?.[active];
  const items=view==='updates' ? detail?.updates||[] : detail?.installed||[];
  const filtered=useMemo(()=>items.filter(p=>
    [p.name,p.id,p.version,p.arch,p.repo,p.branch,p.origin].filter(Boolean)
      .join(' ').toLowerCase().includes(search.toLowerCase().trim())).slice(0,500),
    [items,search]);
  const running=jobs.find(j=>j.state==='running'||j.state==='queued');

  async function upgrade() {
    if(!approval)return;
    setJobBusy(true);setError('');
    try {
      await request('/api/packages/upgrade/'+kinds[approval.key],
                    {method:'POST',body:JSON.stringify({confirm:true,confirmation_text:typed})},csrf);
      setMessage('Actualización enviada. Revisa su progreso en el historial de trabajos.');
      setApproval(null);setTyped('');
      await loadJobs();
    } catch(e){setError(e.message);setApproval(null);}
    finally{setJobBusy(false);}
  }

  return <div className="pm">
    <div className="pm-heading">
      <div><div className="eyebrow">FEDORA · ADMINISTRACIÓN DE PAQUETES</div>
        <h2>Actualizaciones del sistema</h2>
        <p>Consulta DNF, Flatpak y el historial antes de autorizar cambios en tu Fedora.</p></div>
      <button className="pm-button" disabled={busy} onClick={()=>refresh(true)}>
        <RefreshCw className={busy?'spin':''} size={16}/> {busy?'Consultando…':'Buscar actualizaciones'}</button>
    </div>
    {error&&<Result type="error">{error}</Result>}
    {message&&<Result type="ok">{message}</Result>}
    <div className="pm-groups">
      {groups.map(group=>{
        const d=data?.[group.key];
        return <button key={group.key} className={'pm-group '+(active===group.key?'active':'')}
          onClick={()=>{setActive(group.key);setSearch('');setView('updates');}}>
          <div className="pm-group-heading"><Package size={20}/><span>{group.label}</span></div>
          <strong>{d?d.updates.length:'—'}</strong>
          <small>actualizaciones disponibles</small>
          <div className="pm-group-bottom">{d?.error? <span className="pm-warn">Revisar consulta</span>:
            d?.available? <span className="pm-ready">Disponible</span> : <span>No detectado</span>}
            <span>{group.hint}</span></div>
        </button>;
      })}
    </div>
    <div className="pm-grid">
      <section className="pm-card pm-main">
        <header className="pm-card-header">
          <div><h3>{selected.label}</h3><span>{selected.hint}</span></div>
          <div className="pm-tabs">
            <button className={view==='updates'?'selected':''} onClick={()=>setView('updates')}>Pendientes</button>
            <button className={view==='installed'?'selected':''} onClick={()=>setView('installed')}>Instalados</button>
            {active==='dnf' && <button className={view==='history'?'selected':''} onClick={()=>setView('history')}>Historial DNF</button>}
          </div>
        </header>
        {detail?.error&&<Result type="error">{detail.error}</Result>}
        <div className="pm-card-body">
          {view!=='history'?<>
            <div className="pm-search"><Search size={16}/><input aria-label="Buscar paquetes"
              placeholder="Buscar paquete o versión…" value={search} onChange={e=>setSearch(e.target.value)}/>
              <span>{filtered.length} resultados</span>
            </div>
            <div className="pm-table-wrap"><table className="pm-table">
              <thead><tr><th>Paquete</th><th>Versión / rama</th><th>Origen / arquitectura</th></tr></thead>
              <tbody>{filtered.length?filtered.map((item,i)=><tr key={(item.id||item.name)+'-'+i}>
                <td><strong>{item.name||item.id||'—'}</strong>{item.id&&<span>{item.id}</span>}</td>
                <td>{item.version||item.branch||'—'}</td><td>{item.repo||item.origin||item.arch||'—'}</td>
              </tr>):<tr><td colSpan="3" className="pm-empty">No hay paquetes que mostrar para esta consulta.</td></tr>}</tbody>
            </table></div>
            {items.length>500&&<p className="pm-muted">Se muestran los primeros 500 resultados. Usa el filtro para encontrar un paquete.</p>}
          </>:<pre className="pm-history">{detail?.history?.length?detail.history.join('\n'):'No hay historial disponible.'}</pre>}
        </div>
        <footer className="pm-card-footer">
          <div><Shield size={17}/><span>{detail?.upgrade_enabled?'Actualización autorizable':'Modo consulta: falta habilitar la operación'}</span></div>
          <button className="pm-apply" disabled={!detail?.available||!detail?.upgrade_enabled||!!running||jobBusy}
            onClick={()=>{setApproval(selected);setTyped('');}}>
            <ListChecks size={16}/> Actualizar {selected.label}
          </button>
        </footer>
      </section>
      <section className="pm-card pm-side">
        <header className="pm-card-header"><div><h3><Clock3 size={17}/> Trabajos de actualización</h3>
          <span>Historial de esta sesión del agente</span></div>
          <button className="pm-icon" onClick={loadJobs} title="Actualizar trabajos"><RefreshCw size={15}/></button>
        </header>
        {jobs.length?jobs.map(j=><div className="pm-job" key={j.id}>
          <div className="pm-job-heading"><span>{jobNames[j.kind]||j.kind}</span>
            <span className={'pm-job-state '+j.state}>{j.state}</span></div>
          <small>{j.created_at?new Date(j.created_at*1000).toLocaleString('es-CR'):'—'}</small>
          {j.output&&<details><summary>Salida de la operación</summary><pre>{j.output}</pre></details>}
        </div>):<div className="pm-no-jobs"><FileClock size={28}/>
          <strong>Sin operaciones registradas</strong><span>Solo se actualiza cuando autorizas una operación.</span></div>}
        <div className="pm-info"><AlertTriangle size={16}/>
          <p>Actualizar DNF puede requerir reiniciar el equipo; Flatpak puede reiniciar aplicaciones. No se actualiza ni reinicia nada automáticamente.</p>
        </div>
      </section>
    </div>
    <p className="pm-footnote">Modo lectura disponible sin privilegios adicionales. Las actualizaciones del sistema necesitan un helper root instalado manualmente. La actualización de Flatpak personal usa tu cuenta Fedora.</p>
    {approval&&<div className="pm-modal-overlay" onMouseDown={e=>e.target===e.currentTarget&&setApproval(null)}>
      <div className="pm-modal" role="dialog" aria-modal="true" aria-label="Autorizar actualización">
        <div className="pm-modal-icon"><AlertTriangle size={24}/></div>
        <h3>¿Actualizar {approval.label}?</h3>
        <p>Se instalarán todas las actualizaciones disponibles de esta categoría. La operación puede modificar servicios o aplicaciones y no tiene deshacer automático.</p>
        <label>Para autorizar, escribe exactamente <strong>{approval.phrase}</strong>
          <input value={typed} onChange={e=>setTyped(e.target.value)}
                 autoComplete="off" placeholder={approval.phrase}/></label>
        <div className="pm-modal-actions"><button className="pm-button" disabled={jobBusy} onClick={()=>setApproval(null)}>Cancelar</button>
          <button className="pm-apply" disabled={jobBusy||typed!==approval.phrase} onClick={upgrade}>Confirmar actualización</button></div>
      </div>
    </div>}
  </div>;
}
