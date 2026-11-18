import React, {useCallback,useEffect,useMemo,useState} from 'react';
import {
  Activity,AlertTriangle,Bell,BellOff,CheckCircle2,Clock3,
  Database,HardDrive,HeartPulse,MessageCircle,PauseCircle,
  PlayCircle,RefreshCw,Save,Server,Settings2,ShieldCheck,
  Thermometer,Timer,Wifi,XCircle
} from 'lucide-react';
import './alerts-center.css';

const names={
  containers:'Contenedores Docker',postgres:'PostgreSQL',http:'Servicios HTTP',
  cpu:'CPU',memory:'Memoria RAM',disk:'Espacio en disco',
  temperature:'Temperatura',tls:'Certificados TLS',backup:'Respaldos'
};
const icons={
  containers:Server,postgres:Database,http:Wifi,cpu:Activity,
  memory:HeartPulse,disk:HardDrive,temperature:Thermometer,
  tls:ShieldCheck,backup:HardDrive
};
const thresholds={
  cpu:'%',memory:'%',disk:'%',temperature:'°C',tls:'días',backup:'horas'
};
const when=val=>val?new Date(val*1000).toLocaleString('es-CR'):'—';
const duration=(value)=>value>0?when(value):'Sin silenciamiento';
function Status({type,children}){
  return <span className={'al-status al-'+type}>{children}</span>;
}

export default function AlertsCenter({request,csrf}){
  const [snapshot,setSnapshot]=useState(null);
  const [draft,setDraft]=useState(null);
  const [busy,setBusy]=useState(true);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');
  const [tab,setTab]=useState('incidents');
  const [silenceChoice,setSilenceChoice]=useState({});
  const [showAll,setShowAll]=useState(false);

  const reload=useCallback(async()=>{
    try{
      const result=await request('/api/alerts/status');
      setSnapshot(result);
      setDraft(prev=>prev||result.rules);
      setError('');
    }catch(e){setError(e.message||'No se pudieron consultar las alertas');}
    finally{setBusy(false);}
  },[request]);
  useEffect(()=>{
    reload();
    const interval=setInterval(reload,20000);
    return ()=>clearInterval(interval);
  },[reload]);

  const cfg=draft||snapshot?.rules;
  const incidents=snapshot?.incidents||[];
  const events=snapshot?.events||[];
  const checks=snapshot?.checks||[];
  const last=snapshot?.last_run;
  const changed=cfg&&snapshot?.rules&&JSON.stringify(cfg)!==JSON.stringify(snapshot.rules);
  const activeCount=incidents.length;
  const danger=incidents.filter(i=>i.severity==='critical').length;
  const grouped=useMemo(()=>Object.entries(names).map(([id,label])=>({
    id,label,Icon:icons[id],
    recent:checks.filter(check=>check.category===id),
    active:incidents.filter(incident=>incident.category===id)
  })),[checks,incidents]);

  function set(key,value){setDraft(p=>({...p,[key]:value}));}
  function checkToggle(kind,flag){setDraft(p=>({...p,checks:{...p.checks,[kind]:flag}}));}
  function threshold(kind,value){setDraft(p=>({...p,thresholds:{...p.thresholds,[kind]:Number(value)}}));}
  async function save(){
    if(!cfg)return;
    setSaving(true);setError('');
    try{
      const updated=await request('/api/alerts/rules',
        {method:'PUT',body:JSON.stringify({rules:cfg})},csrf);
      setSnapshot(p=>({...p,rules:updated}));
      setDraft(updated);
      setMessage('Reglas guardadas en Fedora. El timer debe estar habilitado para monitoreo periódico.');
    }catch(e){setError(e.message||'Error al guardar las reglas');}
    finally{setSaving(false);}
  }
  async function action(path,payload,success){
    setSaving(true);setError('');setMessage('');
    try{
      await request('/api/alerts/'+path,{
        method:'POST',body:JSON.stringify(payload)
      },csrf);
      setMessage(success);await reload();
    }catch(e){setError(e.message||'Operación rechazada');}
    finally{setSaving(false);}
  }
  async function incident(id,verb,minutes=0){
    await action('incidents/'+id+'/'+verb,{minutes},
      verb==='acknowledge'?'Incidencia reconocida.':
      verb==='silence'?'Notificaciones de incidencia silenciadas.':'Notificaciones reactivadas.');
  }
  const expected=cfg?.expected_containers||[];
  const [newContainer,setNewContainer]=useState('');

  return <div className="al-root">
    <div className="al-header">
      <div><div className="eyebrow">MONITOREO PROACTIVO · FASE E v0.6</div>
        <h2>Alertas y automatizaciones</h2>
        <p>Reglas de monitoreo, detección de incidentes, recuperación y notificaciones Telegram con protección contra duplicados.</p>
      </div>
      <button className="al-button" onClick={reload} disabled={busy}>
        <RefreshCw size={15} className={busy?'spin':''}/> Actualizar
      </button>
    </div>
    {error&&<div className="al-note al-error"><AlertTriangle size={17}/>{error}</div>}
    {message&&<div className="al-note"><CheckCircle2 size={17}/>{message}</div>}
    <div className="al-metrics">
      <div className="al-metric"><span>Incidencias abiertas</span>
        <strong>{activeCount}</strong><small>Consolidadas y sin duplicados</small></div>
      <div className="al-metric"><span>Prioridad crítica</span>
        <strong>{danger}</strong><small>Requieren revisión</small></div>
      <div className="al-metric"><span>Última evaluación</span>
        <strong>{last?when(last.timestamp):'Pendiente'}</strong>
        <small>{last?last.inspected+' comprobaciones · '+last.unknown+' desconocidas':'Ninguna evaluación registrada'}</small></div>
      <div className="al-metric"><span>Monitoreo programado</span>
        <strong>{snapshot?.timer?'Activo':'Desactivado'}</strong>
        <small>{cfg?.enabled?'Motor habilitado':'Motor en pausa'}</small></div>
    </div>
    <div className="al-tabs">
      {[['incidents','Incidentes',AlertTriangle],['rules','Reglas',Settings2],
        ['channels','Telegram y agenda',Bell],['history','Historial',Clock3]].map(([id,label,Icon])=>
        <button key={id} className={tab===id?'active':''} onClick={()=>setTab(id)}>
          <Icon size={15}/>{label}</button>)}
    </div>
    {tab==='incidents'&&<section className="al-card">
      <header className="al-card-header"><div><h3>Incidentes activos</h3>
        <p>Los eventos se abren tras fallos consecutivos y cierran automáticamente cuando el origen se recupera.</p></div>
        <button className="al-button" disabled={saving||!cfg?.enabled}
          onClick={()=>action('check',{confirm:true},
            'Comprobación manual ejecutada. La interfaz mostrará los nuevos resultados.')}>
          <PlayCircle size={16}/> Comprobar ahora
        </button></header>
      {incidents.length?incidents.map(i=><article key={i.id} className="al-incident">
        <div className="al-incident-body">
          <div className="al-incident-title">
            <Status type={i.severity==='critical'?'critical':'warning'}>
              {i.severity==='critical'?'Crítico':'Advertencia'}</Status>
            <strong>{i.title}</strong>
          </div>
          <div className="al-incident-detail">
            <span>{names[i.category]||i.category} · {i.subject}</span>
            <span>Desde: {when(i.opened_at)}</span>
            {i.acknowledged_at&&<Status type="good">Reconocida</Status>}
            {i.muted_until>Math.floor(Date.now()/1000)&&<Status type="info">
              Silenciada hasta {when(i.muted_until)}</Status>}
          </div>
        </div>
        <div className="al-incident-actions">
          <button className="al-button" disabled={saving||!!i.acknowledged_at}
            onClick={()=>incident(i.id,'acknowledge')}>
            <CheckCircle2 size={14}/> Reconocer
          </button>
          {i.muted_until>Math.floor(Date.now()/1000)?
            <button className="al-button" disabled={saving}
              onClick={()=>incident(i.id,'unsilence')}>
              <Bell size={14}/> Reactivar
            </button>:
            <div className="al-mute">
              <select aria-label={'Silenciamiento '+i.id}
                value={silenceChoice[i.id]||60}
                onChange={e=>setSilenceChoice(p=>({...p,[i.id]:Number(e.target.value)}))}>
                <option value="15">15 min</option><option value="60">1 hora</option>
                <option value="240">4 horas</option><option value="1440">24 horas</option>
              </select>
              <button className="al-button" disabled={saving}
                onClick={()=>incident(i.id,'silence',silenceChoice[i.id]||60)}>
                <BellOff size={14}/> Silenciar
              </button>
            </div>}
        </div>
      </article>):<div className="al-empty"><CheckCircle2 size={32}/>
        <strong>Sin incidentes abiertos</strong>
        <span>Los errores se consolidan tras las evaluaciones, siempre que el monitoreo esté habilitado.</span>
      </div>}
      <div className="al-card-footer">Origenes conocidos:
        {' '+checks.length+' comprobaciones registradas · '+checks.filter(c=>c.status==='unknown').length+' sin lectura'}
      </div>
    </section>}
    {tab==='rules'&&<section className="al-card">
      <header className="al-card-header"><div><h3>Reglas y umbrales</h3>
        <p>El monitoreo solo genera avisos cuando está habilitado y el timer de Fedora está activo.</p></div>
        <button className="al-button al-main" disabled={!changed||saving}
          onClick={save}><Save size={15}/> Guardar cambios</button></header>
      {cfg&&<div className="al-rules">
        <div className="al-switch-row">
          <div><strong>Motor de monitoreo</strong><small>Detiene evaluaciones y nuevas alertas cuando está desactivado.</small></div>
          <input type="checkbox" checked={cfg.enabled} onChange={e=>set('enabled',e.target.checked)}/>
        </div>
        <div className="al-switch-row">
          <div><strong>Notificaciones Telegram</strong><small>Requiere credenciales locales configuradas y permiso explícito.</small></div>
          <input type="checkbox" checked={cfg.notify_telegram} onChange={e=>set('notify_telegram',e.target.checked)}/>
        </div>
        <div className="al-switch-row">
          <div><strong>Avisar al recuperarse</strong><small>Envía un aviso cuando un incidente notificado vuelve a estar saludable.</small></div>
          <input type="checkbox" checked={cfg.notify_recovery} onChange={e=>set('notify_recovery',e.target.checked)}/>
        </div>
        <div className="al-rule-numbers">
          <label>Fallos consecutivos antes de abrir
            <input type="number" min="1" max="8" value={cfg.consecutive_failures}
              onChange={e=>set('consecutive_failures',Number(e.target.value))}/></label>
          <label>Repetir alertas abiertas cada (min)
            <input type="number" min="5" max="1440" value={cfg.cooldown_minutes}
              onChange={e=>set('cooldown_minutes',Number(e.target.value))}/></label>
        </div>
        <h4>Fuentes monitorizadas</h4>
        <div className="al-checks">
          {grouped.map(({id,label,Icon,recent,active})=>
            <div className="al-check-row" key={id}>
              <Icon size={19}/><div><strong>{label}</strong><small>
                {active.length+' incidentes · '+recent.length+' comprobaciones'}
              </small></div>
              {' '+(thresholds[id]?<label className="al-threshold">
                <input type="number" min="1" max={id==='backup'?720:115}
                  value={cfg.thresholds[id]}
                  onChange={e=>threshold(id,e.target.value)}/>{thresholds[id]}</label>:null)}
              <input type="checkbox" checked={cfg.checks[id]}
                onChange={e=>checkToggle(id,e.target.checked)}/>
            </div>)}
        </div>
        <h4>Contenedores esperados (supervisión Docker)</h4>
        <p className="al-small">Solo los contenedores que selecciones serán vigilados como servicios que deberían permanecer activos. No se detienen ni reinician automáticamente.</p>
        <div className="al-expected">
          {expected.map(name=><span className="al-chip" key={name}>{name}
            <button aria-label={'Eliminar '+name} onClick={()=>set('expected_containers',expected.filter(n=>n!==name))}>×</button>
          </span>)}
        </div>
        <div className="al-add">
          <input placeholder="Nombre Docker exacto" value={newContainer}
            onChange={e=>setNewContainer(e.target.value)}/>
          <button className="al-button" disabled={!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/.test(newContainer)}
            onClick={()=>{set('expected_containers',[...new Set([...expected,newContainer])].sort());setNewContainer('');}}>Agregar</button>
        </div>
        {changed&&<div className="al-note"><AlertTriangle size={16}/> Tienes cambios sin guardar. Guarda las reglas para aplicarlas.</div>}
      </div>}
    </section>}
    {tab==='channels'&&<section className="al-card">
      <header className="al-card-header"><div><h3>Telegram y automatizaciones</h3>
        <p>Credenciales privadas en Fedora, no en la base de datos del navegador ni en GitHub.</p></div>
        <Status type={snapshot?.telegram?.configured?'good':'warning'}>
          {snapshot?.telegram?.configured?'Telegram configurado':'Sin configurar'}
        </Status>
      </header>
      <div className="al-channel">
        <h4><MessageCircle size={17}/> Configuración Telegram</h4>
        <p>Configura tu bot de Telegram desde una terminal local. El comando solicita el token de forma oculta.</p>
        <pre>python3 scripts/alerts_setup.py --telegram</pre>
        {snapshot?.telegram?.error&&<div className="al-note al-error">
          <AlertTriangle size={16}/>{snapshot.telegram.error}
        </div>}
        <button className="al-button" disabled={!snapshot?.telegram?.configured||saving}
          onClick={()=>action('telegram/test',{confirm:true},
              'Mensaje de prueba enviado a Telegram.')}>
          <MessageCircle size={15}/> Enviar mensaje de prueba
        </button>
        <p className="al-small">Antes de probar, abre el chat del bot en Telegram y pulsa <strong>Iniciar</strong> o envía <code>/start</code>. Si cambiaste las credenciales, ejecuta <code>python3 scripts/alerts_setup.py --telegram --replace</code> y repite la prueba. Los incidentes continúan registrándose aunque Telegram esté desactivado.</p>
      </div>
      <div className="al-channel">
        <h4><Timer size={17}/> Programador de comprobaciones</h4>
        <p>Evaluación recurrente cada dos minutos mediante un timer systemd de usuario.</p>
        <pre>python3 scripts/alerts_setup.py --enable</pre>
        <p>Para desactivar las comprobaciones sin borrar el historial:</p>
        <pre>python3 scripts/alerts_setup.py --disable</pre>
        <Status type={snapshot?.timer?'good':'warning'}>
          {snapshot?.timer?'Timer habilitado':'Timer no habilitado'}
        </Status>
      </div>
      <div className="al-channel">
        <h4><ShieldCheck size={17}/> Mantenimiento autorizado · integridad restic</h4>
        <p>Verificación opcional y de solo lectura del repositorio cifrado, cada domingo a las 04:00. Se registra como trabajo de Backup & Recovery, y sus fallos pueden generar incidentes.</p>
        <pre>python3 scripts/maintenance_schedule.py --enable</pre>
        <p>Desactivar sin borrar snapshots:</p>
        <pre>python3 scripts/maintenance_schedule.py --disable</pre>
        <Status type={snapshot?.maintenance_timer?'good':'warning'}>
          {snapshot?.maintenance_timer?'Mantenimiento semanal habilitado':'Mantenimiento semanal desactivado'}
        </Status>
      </div>
      <div className="al-channel">
        <h4><PauseCircle size={17}/> Silenciamiento global</h4>
        <p>Suspende los avisos sin detener el monitoreo, conservará el historial y las incidencias.</p>
        <div className="al-mute-controls">
          {[0,1,4,24].map(hours=><button key={hours} className="al-button" disabled={saving||!cfg}
            onClick={()=>{
              const now=Math.floor(Date.now()/1000);
              set('silent_until',hours?now+hours*3600:0);
              setTab('rules');
              setMessage('Cambio pendiente: guarda las reglas para activar el silencio global.');
            }}>
            {hours?hours+' h':'Quitar silencio'}</button>)}
        </div>
        <p className="al-small">Hasta: {duration(cfg?.silent_until||0)}. Cambios requieren guardar las reglas.</p>
      </div>
    </section>}
    {tab==='history'&&<section className="al-card">
      <header className="al-card-header"><div><h3>Historial de incidentes y notificaciones</h3>
        <p>Eventos recientes; el motor conserva noventa días de historial.</p></div>
        <Status type="info">{events.length} eventos</Status></header>
      <div className="al-event-list">
        {events.length?events.map(event=><div className="al-event" key={event.id}>
          <span><Clock3 size={15}/>{when(event.timestamp)}</span>
          <strong>{event.event}</strong>
          <span>Incidencia #{event.incident_id} · {event.note}</span>
        </div>):<div className="al-empty"><Clock3 size={28}/>
          <strong>Sin eventos todavía</strong><span>Los incidentes aparecerán tras las próximas comprobaciones.</span>
        </div>}
      </div>
    </section>}
    <div className="al-footer"><ShieldCheck size={16}/>
      Este módulo no repara automáticamente servicios, cambia paquetes, ejecuta scripts ni reinicia contenedores.
      Las operaciones administrativas siguen requiriendo autorización explícita.
    </div>
  </div>;
}
