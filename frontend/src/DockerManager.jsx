import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, Boxes, CheckCircle2, ChevronDown, Clock3,
  Container, FileText, HardDrive, Layers, LoaderCircle, Network,
  Pause, Play, RefreshCw, RotateCw, Search, Server, ShieldCheck, Square, X
} from 'lucide-react';
import './docker-manager.css';

const sections = [
  { id: 'containers', name: 'Contenedores', icon: Container },
  { id: 'projects', name: 'Proyectos Compose', icon: Layers },
  { id: 'images', name: 'Imágenes', icon: Boxes },
  { id: 'volumes', name: 'Volúmenes', icon: HardDrive },
  { id: 'networks', name: 'Redes', icon: Network },
];
const actionLabels = { start: 'Iniciar', stop: 'Detener', restart: 'Reiniciar' };

function State({ good, children }) {
  return <span className={'dm-state ' + (good ? 'dm-state-on' : 'dm-state-off')}>
    <span className="dm-state-dot" />{children}
  </span>;
}
function Empty({ icon: Icon, heading, detail }) {
  return <div className="dm-empty"><Icon size={27}/><strong>{heading}</strong><span>{detail}</span></div>;
}
function ActionButtons({ container, onAction }) {
  const actions = container.allowed_actions || [];
  if (!actions.length) return <span className="dm-muted dm-restricted" title="Habilita este contenedor explícitamente en .env"><ShieldCheck size={14}/> Solo lectura</span>;
  return <div className="dm-actions">
    {container.state !== 'running' && <button title="Iniciar" onClick={() => onAction(container.name, 'start')}><Play size={15}/></button>}
    {container.state === 'running' && <button title="Detener" onClick={() => onAction(container.name, 'stop')}><Square size={15}/></button>}
    <button title="Reiniciar" onClick={() => onAction(container.name, 'restart')}><RotateCw size={15}/></button>
  </div>;
}
function InfoTable({ headings, rows, empty }) {
  return <div className="dm-table-scroll"><table className="dm-table"><thead><tr>{headings.map(x => <th key={x}>{x}</th>)}</tr></thead>
    <tbody>{rows.length ? rows : <tr><td colSpan={headings.length}><div className="dm-muted" style={{padding:22,textAlign:'center'}}>{empty}</div></td></tr>}</tbody>
  </table></div>;
}

export default function DockerManager({ request, csrf }) {
  const [inventory, setInventory] = useState(null);
  const [stats, setStats] = useState({});
  const [section, setSection] = useState('containers');
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [fetching, setFetching] = useState(false);
  const [loadingAction, setLoadingAction] = useState(false);
  const [action, setAction] = useState(null);
  const [showLogs, setShowLogs] = useState(null);
  const [logs, setLogs] = useState('');
  const [logsError, setLogsError] = useState('');
  const [logsLive, setLogsLive] = useState(true);
  const [tail, setTail] = useState(150);
  const [since, setSince] = useState('30m');
  const [lastUpdated, setLastUpdated] = useState(null);
  const [toast, setToast] = useState('');

  const refresh = useCallback(async (indicator = false) => {
    if (indicator) setFetching(true);
    try {
      const inv = await request('/api/docker/inventory');
      setInventory(inv);
      setError(inv.error || '');
      setLastUpdated(new Date());
    } catch(e) { setError(e.message || 'No se pudo contactar al agente'); }
    finally { if(indicator) setFetching(false); }
  }, [request]);

  const refreshStats = useCallback(async () => {
    try {
      const data = await request('/api/docker/stats');
      const keyed = {};
      for (const item of data.items || []) keyed[item.name] = item;
      setStats(keyed);
    } catch (_) { /* inventory remains usable if stats is unavailable */ }
  }, [request]);

  useEffect(() => {
    refresh(true); refreshStats();
    const invTimer = setInterval(() => refresh(false), 30000);
    const statsTimer = setInterval(refreshStats, 20000);
    return () => { clearInterval(invTimer); clearInterval(statsTimer); };
  }, [refresh, refreshStats]);

  const refreshLogs = useCallback(async () => {
    if (!showLogs) return;
    try {
      const r = await request('/api/docker/containers/' + encodeURIComponent(showLogs) +
        '/logs?tail=' + tail + '&since=' + since);
      setLogs(r.logs || '');
      setLogsError('');
    } catch(e) { setLogsError(e.message || 'No se pueden leer los logs'); }
  }, [request, showLogs, tail, since]);

  useEffect(() => {
    if (!showLogs) return;
    refreshLogs();
    if (!logsLive) return;
    const id = setInterval(refreshLogs, 5000);
    return () => clearInterval(id);
  }, [showLogs, logsLive, refreshLogs]);

  const containers = inventory?.containers || [];
  const projects = inventory?.projects || [];
  const active = containers.filter(c => c.state === 'running').length;
  const filtered = useMemo(() => containers.filter(c => {
    if (filter === 'running' && c.state !== 'running') return false;
    if (filter === 'stopped' && c.state === 'running') return false;
    const hay = [c.name, c.image, c.project, c.service, c.ports].join(' ').toLowerCase();
    return hay.includes(query.trim().toLowerCase());
  }), [containers, filter, query]);
  const matches = (text) => String(text || '').toLowerCase().includes(query.trim().toLowerCase());

  async function commitAction() {
    if (!action) return;
    setLoadingAction(true);
    setError('');
    try {
      const name = action.name;
      await request('/api/docker/containers/' + encodeURIComponent(name) + '/' + action.type,
        { method: 'POST', body: JSON.stringify({ confirm: true }) }, csrf);
      setToast('Operación ejecutada: ' + actionLabels[action.type] + ' · ' + name);
      setAction(null);
      await Promise.all([refresh(true), refreshStats()]);
    } catch(e) { setError(e.message || 'Falló la operación'); setAction(null); }
    finally { setLoadingAction(false); }
  }
  const viewLogs = name => { setShowLogs(name); setLogs(''); setLogsError(''); setLogsLive(true); };

  return <div className="dm-root">
    <div className="dm-heading">
      <div><div className="eyebrow">INFRAESTRUCTURA · DOCKER MANAGER 2.0</div>
        <h2>Docker y contenedores</h2>
        <p>Administra y observa tu infraestructura sin salir de HomeLab OS.</p>
      </div>
      <button className="dm-button dm-outline" onClick={() => { refresh(true); refreshStats(); }} disabled={fetching}>
        <RefreshCw size={16} className={fetching ? 'spin' : ''}/> Actualizar
      </button>
    </div>
    <div className="dm-summary">
      {[
        { label:'Contenedores', value: inventory?.connected ? containers.length : '—', icon:Container },
        { label:'En ejecución', value: inventory?.connected ? active : '—', icon:CheckCircle2 },
        { label:'Proyectos Compose', value: inventory?.connected ? projects.length : '—', icon:Layers },
        { label:'Imágenes', value: inventory?.connected ? inventory.images.length : '—', icon:Boxes }
      ].map(({label,value,icon:Icon}) => <div className="dm-summary-card" key={label}>
        <div className="dm-summary-label">{label}<Icon size={17}/></div><strong>{value}</strong>
      </div>)}
    </div>
    {!!error && <div className="dm-message dm-message-error"><AlertTriangle size={17}/>{error}<button onClick={() => setError('')}><X size={16}/></button></div>}
    {!!toast && <div className="dm-message dm-message-ok"><CheckCircle2 size={17}/>{toast}<button onClick={() => setToast('')}><X size={16}/></button></div>}
    <section className="dm-panel">
      <div className="dm-toolbar">
        <div className="dm-tabs" role="tablist" aria-label="Recursos de Docker">
          {sections.map(({id,name,icon:Icon}) => <button key={id} role="tab"
            aria-selected={section === id} className={section === id ? 'dm-tab-active' : ''}
            onClick={() => {setSection(id);setQuery('');}}>
            <Icon size={15}/>{name}
          </button>)}
        </div>
        <div className="dm-filter-row">
          <label className="dm-search"><Search size={15}/><input aria-label="Filtrar recursos Docker" value={query}
            placeholder="Buscar por nombre, imagen, proyecto…" onChange={e=>setQuery(e.target.value)}/></label>
          {section === 'containers' && <select aria-label="Estado de contenedor" value={filter} onChange={e=>setFilter(e.target.value)}>
            <option value="all">Todos</option><option value="running">En ejecución</option><option value="stopped">Detenidos</option>
          </select>}
        </div>
      </div>
      {!inventory && !error && <div className="dm-wait"><LoaderCircle className="spin" size={20}/> Cargando inventario real…</div>}
      {inventory && !inventory.connected && <Empty icon={Server} heading="Docker no disponible" detail={inventory.error || 'Comprueba el agente Fedora y el acceso a Docker.'}/>}
      {inventory?.connected && section === 'containers' && <InfoTable headings={['Contenedor / imagen','Estado','CPU','Memoria','Proyecto','Operaciones']} empty="No hay contenedores que coincidan con la búsqueda."
        rows={filtered.map(c => <tr key={c.name}>
          <td><div className="dm-name-cell"><div className={'dm-container-icon ' + (c.state === 'running' ? 'on' : '')}><Container size={19}/></div>
            <div><button className="dm-name-button" title="Ver logs" onClick={() => viewLogs(c.name)}>{c.name}</button>
              <span className="dm-muted dm-image">{c.image}</span>
              {c.ports && <span className="dm-muted dm-image">{c.ports}</span>}
            </div></div></td>
          <td><State good={c.state==='running'}>{c.state === 'running' ? 'Activo' : c.state}</State></td>
          <td><span className="dm-mono">{stats[c.name]?.cpu || '—'}</span></td>
          <td><div className="dm-mono">{stats[c.name]?.memory || '—'}</div>
              {stats[c.name]?.memory_percent && <span className="dm-muted">{stats[c.name].memory_percent}</span>}</td>
          <td><span className="dm-project-name">{c.project || 'Independiente'}</span>
            {c.service && <span className="dm-muted dm-image">{c.service}</span>}</td>
          <td><div className="dm-inline-ops">
            <button className="dm-log-button" onClick={() => viewLogs(c.name)} title="Ver logs"><FileText size={14}/> Logs</button>
            <ActionButtons container={c} onAction={(name,type)=>setAction({name,type})}/>
          </div></td>
        </tr>)} />}
      {inventory?.connected && section === 'projects' && (projects.filter(p=>matches(p.name) || p.containers.some(matches)).length ?
        <div className="dm-project-grid">{projects.filter(p=>matches(p.name) || p.containers.some(matches)).map(p=>
          <div className="dm-project" key={p.name}>
            <div className="dm-project-title"><div className="dm-project-icon"><Layers size={20}/></div>
              <div><strong>{p.name}</strong><small>{p.services.length} servicios · {p.total} contenedores</small></div>
              <State good={p.running===p.total}>{p.running}/{p.total} activos</State>
            </div>
            <div className="dm-project-children">{p.containers.map(name => {
              const c=containers.find(x=>x.name===name);
              return c && <div className="dm-project-child" key={name}><Container size={15}/><span>{name}</span>
                <State good={c.state === 'running'}>{c.state === 'running' ? 'Activo' : c.state}</State>
                <button onClick={()=>viewLogs(name)} title="Ver logs"><FileText size={16}/></button>
              </div>;
            })}</div>
          </div>)}</div> : <Empty icon={Layers} heading="Sin proyectos Compose" detail="Detectamos proyectos automáticamente mediante etiquetas de Docker Compose. Los contenedores independientes aparecen en la pestaña Contenedores."/>)}
      {inventory?.connected && section === 'images' && <InfoTable headings={['Repositorio','Etiqueta','Identificador','Tamaño','Creación']} empty="No se encontraron imágenes."
        rows={inventory.images.filter(i=>matches(i.repository+' '+i.tag+' '+i.id)).map((i,index)=><tr key={i.id+'-'+index}><td><strong>{i.repository}</strong></td>
          <td className="dm-mono">{i.tag}</td><td className="dm-muted dm-mono">{i.id}</td><td className="dm-mono">{i.size}</td><td className="dm-muted">{i.created}</td></tr>)} />}
      {inventory?.connected && section === 'volumes' && <InfoTable headings={['Volumen','Driver']} empty="No se encontraron volúmenes."
        rows={inventory.volumes.filter(v=>matches(v.name+' '+v.driver)).map((v,index)=><tr key={v.name+'-'+index}><td><div className="dm-name-cell"><HardDrive size={17}/><strong>{v.name}</strong></div></td><td className="dm-muted">{v.driver}</td></tr>)} />}
      {inventory?.connected && section === 'networks' && <InfoTable headings={['Red','Driver','Ámbito','ID']} empty="No se encontraron redes."
        rows={inventory.networks.filter(n=>matches(n.name+' '+n.driver+' '+n.id)).map((n,index)=><tr key={n.id+'-'+index}><td><div className="dm-name-cell"><Network size={17}/><strong>{n.name}</strong></div></td><td>{n.driver}</td><td className="dm-muted">{n.scope}</td><td className="dm-mono dm-muted">{n.id}</td></tr>)} />}
    </section>
    <div className="dm-bottom">
      <span><ShieldCheck size={15}/> Solo lectura por defecto. Las operaciones requieren lista autorizada y confirmación.</span>
      <span><Clock3 size={15}/> {lastUpdated ? 'Última actualización: '+lastUpdated.toLocaleTimeString('es-CR') : 'Esperando al agente'}</span>
    </div>

    {showLogs && <div className="dm-overlay" onMouseDown={e=>e.target===e.currentTarget&&setShowLogs(null)}>
      <div className="dm-log-dialog" role="dialog" aria-modal="true" aria-label={'Logs de '+showLogs}>
        <div className="dm-dialog-head"><div><div className="eyebrow">SALIDA DE CONTENEDOR</div><h3><FileText size={19}/> {showLogs}</h3></div>
          <button className="dm-x" aria-label="Cerrar logs" onClick={()=>setShowLogs(null)}><X size={20}/></button></div>
        <div className="dm-log-controls">
          <label>Intervalo<select value={since} onChange={e=>setSince(e.target.value)}>
            <option value="5m">5 minutos</option><option value="30m">30 minutos</option><option value="1h">1 hora</option><option value="24h">24 horas</option><option value="all">Todo el historial</option>
          </select></label>
          <label>Líneas<select value={tail} onChange={e=>setTail(Number(e.target.value))}><option value={50}>50</option><option value={150}>150</option><option value={300}>300</option><option value={500}>500</option></select></label>
          <button className={'dm-button '+(logsLive?'dm-live':'dm-outline')} onClick={()=>setLogsLive(v=>!v)}>
            {logsLive?<Activity size={15}/>:<Pause size={15}/>} {logsLive?'En vivo · 5 s':'Pausado'}
          </button>
          <button className="dm-button dm-outline" onClick={refreshLogs}><RefreshCw size={15}/> Recargar</button>
        </div>
        {stats[showLogs] && <div className="dm-log-metrics">
          <span><b>CPU</b> {stats[showLogs].cpu}</span>
          <span><b>RAM</b> {stats[showLogs].memory}</span>
          <span><b>Red E/S</b> {stats[showLogs].network}</span>
          <span><b>Disco E/S</b> {stats[showLogs].disk_io}</span>
          <span><b>Procesos</b> {stats[showLogs].pids}</span>
        </div>}
        {logsError && <div className="dm-message dm-message-error"><AlertTriangle size={15}/>{logsError}</div>}
        <pre className="dm-log-output">{logs || 'No hay líneas disponibles para este intervalo.'}</pre>
        <div className="dm-log-foot"><ShieldCheck size={14}/> Los logs se consultan en el agente; no se guardan en HomeLab OS.</div>
      </div>
    </div>}
    {action && <div className="dm-overlay" onMouseDown={e=>e.target===e.currentTarget&&setAction(null)}>
      <div className="dm-confirm" role="dialog" aria-modal="true" aria-label="Confirmar operación Docker">
        <div className="dm-warning"><AlertTriangle size={24}/></div>
        <h3>¿{actionLabels[action.type]} contenedor?</h3>
        <p>Se ejecutará <strong>{action.type}</strong> sobre <strong>{action.name}</strong> en tu Fedora.
          {action.type==='stop' && ' Esto interrumpirá el servicio y su política de reinicio podría volver a iniciarlo.'}
          {action.type==='restart' && ' El servicio quedará temporalmente interrumpido.'}</p>
        <div className="dm-confirm-actions"><button className="dm-button dm-outline" onClick={()=>setAction(null)} disabled={loadingAction}>Cancelar</button>
          <button className="dm-button dm-danger-button" onClick={commitAction} disabled={loadingAction}>{loadingAction?'Aplicando…':'Confirmar '+actionLabels[action.type].toLowerCase()}</button></div>
      </div>
    </div>}
  </div>;
}
