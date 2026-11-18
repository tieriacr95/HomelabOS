import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, Archive, CheckCircle2, ChevronDown, Clock3, Database,
  Download, FileClock, FolderLock, HardDrive, KeyRound, LockKeyhole,
  RefreshCw, RotateCcw, Server, ShieldCheck, Timer, XCircle
} from 'lucide-react';
import './backup-center.css';

const confirmations = {
  backup: 'EJECUTAR RESPALDO', verify: 'VERIFICAR RESPALDOS',
};
const labels = {backup:'Crear respaldo cifrado', verify:'Verificar repositorio',
                restore:'Recuperar archivos en zona aislada'};

const when = value => value ?
  new Date(typeof value === 'number' ? value*1000 : value).toLocaleString('es-CR') : '—';

function Pill({type,children}) {
  return <span className={'bk-pill bk-'+type}>{children}</span>;
}
function Info({kind='neutral',children}) {
  return <div className={'bk-info bk-info-'+kind}>
    {kind==='error'?<AlertTriangle size={17}/>:<ShieldCheck size={17}/>}
    <span>{children}</span>
  </div>;
}
function ResourceIcon({kind}) {
  const Icon = kind==='postgres' ? Database : kind==='volume' ? HardDrive :
               kind==='directory' ? FolderLock : Server;
  return <Icon size={19}/>;
}

export default function BackupCenter({request,csrf}) {
  const [status,setStatus] = useState(null);
  const [snapshots,setSnapshots] = useState([]);
  const [jobs,setJobs] = useState([]);
  const [busy,setBusy] = useState(true);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [dialog,setDialog] = useState(null);
  const [typed,setTyped] = useState('');
  const [submitting,setSubmitting] = useState(false);
  const [tab,setTab] = useState('snapshots');

  const getStatus = useCallback(async ()=>{
    try {
      const result=await request('/api/backup/status');
      setStatus(result);setJobs(result.jobs||[]);
      return result;
    }catch(e){setError(e.message||'No se pudo consultar el agente');return null;}
  },[request]);
  const getSnapshots = useCallback(async ()=>{
    try {
      const result=await request('/api/backup/snapshots');
      setSnapshots(result.items||[]);
    }catch(e){setSnapshots([]);}
  },[request]);
  const reload = useCallback(async ()=>{
    setBusy(true);
    const result=await getStatus();
    if(result?.configured) await getSnapshots();
    setBusy(false);
  },[getStatus,getSnapshots]);

  useEffect(()=>{
    reload();
    const timer=setInterval(async()=>{
      try{
        const response=await request('/api/backup/jobs');
        setJobs(response.items||[]);
        const active=response.items?.some(j=>['running','queued'].includes(j.state));
        if(!active){const fresh=await getStatus();if(fresh?.configured)await getSnapshots();}
      }catch(_){}
    },15000);
    return ()=>clearInterval(timer);
  },[reload,getStatus,getSnapshots,request]);

  const configured=!!status?.configured;
  const sources=status?.sources||[];
  const failures=jobs.filter(j=>j.state==='failed');
  const mostRecent=jobs[0];
  const sorted=useMemo(()=>[...snapshots].sort((a,b)=>String(b.time).localeCompare(String(a.time))),[snapshots]);
  const active=jobs.find(j=>j.state==='running'||j.state==='queued');
  const phrase=dialog?(dialog.action==='restore'?'RESTAURAR '+dialog.snapshot:confirmations[dialog.action]):'';

  function prepare(action,snapshot=null){
    setNotice('');setError('');setTyped('');setDialog({action,snapshot});
  }
  async function submit(){
    if(!dialog||typed!==phrase)return;
    setSubmitting(true);setError('');
    try {
      await request('/api/backup/'+dialog.action,{
        method:'POST',body:JSON.stringify({
          confirm:true,confirmation_text:phrase,snapshot:dialog.snapshot,
        })
      },csrf);
      setNotice('Operación aceptada. Su progreso aparecerá en el historial.');
      setDialog(null);setTyped('');
      await reload();
    }catch(e){setError(e.message||'No se pudo iniciar la operación');setDialog(null);}
    finally{setSubmitting(false);}
  }

  return <div className="bk-root">
    <div className="bk-heading">
      <div><div className="eyebrow">PROTECCIÓN DE DATOS · BACKUP & RECOVERY v0.5</div>
        <h2>Respaldos y recuperación</h2>
        <p>Cifrado con restic, copias programadas y recuperación aislada de datos de tus aplicaciones.</p>
      </div>
      <button className="bk-button bk-outline" onClick={reload} disabled={busy}>
        <RefreshCw size={16} className={busy?'spin':''}/> Actualizar</button>
    </div>
    {error&&<Info kind="error">{error}</Info>}
    {notice&&<Info kind="success">{notice}</Info>}
    {failures.length>0&&<Info kind="error">
      Hay {failures.length} operación(es) de respaldo o verificación fallida(s) en el historial.
      Revisa el trabajo más reciente antes de confiar en las copias.
    </Info>}
    <div className="bk-summary">
      {[
        {title:'Repositorio cifrado',value:configured?'Configurado':'Sin configurar',
         note:configured?'Contraseña fuera del panel':'Activación explícita requerida',icon:LockKeyhole},
        {title:'Snapshots',value:configured?sorted.length:'—',note:'Copias HomeLab OS visibles',icon:Archive},
        {title:'Recursos seleccionados',value:sources.length,note:'Nunca se seleccionan solos',icon:Database},
        {title:'Programación',value:status?.scheduled?'Activada':'Desactivada',
         note:'Timer systemd de usuario',icon:Timer},
      ].map(({title,value,note,icon:Icon})=>
        <div className="bk-summary-card" key={title}>
          <div><span>{title}</span><Icon size={18}/></div>
          <strong>{value}</strong><small>{note}</small>
        </div>)}
    </div>
    {!configured&&<section className="bk-card bk-setup">
      <div className="bk-section-head"><div><h3><KeyRound size={18}/> Configura el repositorio antes del primer respaldo</h3>
        <p>Este paso requiere acceso local a tu Fedora. HomeLab OS nunca recibe ni muestra la contraseña de restic.</p></div>
        <Pill type="warning">Acción manual</Pill></div>
      <pre>{'sudo dnf install restic\ncd ~/Documents/Proyectos/HomelabOS\npython3 scripts/setup_backups.py --include-discovered-postgres'}</pre>
      <p>El comando agrega HomeLab OS y los PostgreSQL detectados. Puedes agregar volúmenes específicos con
        <code> --include-volume NOMBRE</code>, y luego ajustar <code>~/.config/homelabos/backup.json</code>.
        El repositorio local es útil para comenzar, pero para recuperación ante fallo de disco debes
        guardar también una copia cifrada fuera del equipo y respaldar la contraseña.</p>
      {status?.error&&<Info kind="error">{status.error}</Info>}
    </section>}
    {configured&&<div className="bk-toolbar">
      <div className="bk-actions">
        <button className="bk-button bk-main" disabled={!!active||busy} onClick={()=>prepare('backup')}>
          <Archive size={16}/> Crear respaldo</button>
        <button className="bk-button bk-outline" disabled={!!active||busy} onClick={()=>prepare('verify')}>
          <ShieldCheck size={16}/> Verificar integridad</button>
      </div>
      <span><ShieldCheck size={16}/> Sin restauración automática sobre datos de producción</span>
    </div>}
    <div className="bk-two-col">
      <section className="bk-card">
        <header className="bk-section-head"><div><h3><Database size={18}/> Recursos protegidos</h3>
          <p>Solo los recursos configurados explícitamente en Fedora entran en el respaldo.</p></div>
          <Pill type={sources.length?'good':'warning'}>{sources.length} recursos</Pill>
        </header>
        {sources.length?<div className="bk-resources">
          {sources.map((s,i)=><div className="bk-resource" key={s.type+s.name+i}>
            <div className="bk-resource-icon"><ResourceIcon kind={s.type}/></div>
            <div><strong>{s.name}</strong><small>{s.type==='postgres'?'PostgreSQL · volcado lógico':
              s.type==='volume'?'Volumen Docker · archivo TAR':
              s.type==='directory'?'Directorio de usuario': 'HomeLab OS · SQLite consistente'}</small>
              {s.path&&<small className="bk-muted">{s.path}</small>}</div>
            <Pill type="good">Seleccionado</Pill>
          </div>)}
        </div>:<div className="bk-empty"><FolderLock size={26}/>
          <strong>Sin recursos configurados</strong>
          <span>Agrega los objetivos de respaldo desde el archivo privado backup.json.</span></div>}
        <div className="bk-discovery">
          <strong><Server size={16}/> Descubiertos, pero no respaldados automáticamente</strong>
          <p>{status?.inventory?.postgres?.length||0} bases PostgreSQL y
            {' '}{status?.inventory?.volumes?.length||0} volúmenes Docker detectados.</p>
          {!!status?.inventory?.error&&<small>{status.inventory.error}</small>}
        </div>
        {configured&&<div className="bk-retention">
          <div><span>Conservar copias diarias</span><strong>{status.retention.daily}</strong></div>
          <div><span>Semanales</span><strong>{status.retention.weekly}</strong></div>
          <div><span>Mensuales</span><strong>{status.retention.monthly}</strong></div>
        </div>}
      </section>
      <section className="bk-card">
        <header className="bk-section-head"><div><h3><Clock3 size={18}/> Programación y recuperación</h3>
          <p>Backups recurrentes mediante systemd --user; la activación es voluntaria.</p></div></header>
        <div className="bk-schedule">
          <Pill type={status?.scheduled?'good':'warning'}>{status?.scheduled?'Timer activo':'Timer no activado'}</Pill>
          <p>Para programar una copia diaria a las 03:00 (hora local):</p>
          <pre>python3 scripts/backup_schedule.py --enable 03:00</pre>
          <p>Desactivar sin borrar snapshots:</p>
          <pre>python3 scripts/backup_schedule.py --disable</pre>
        </div>
        <div className="bk-steps">
          <strong><RotateCcw size={17}/> Protocolo seguro de recuperación</strong>
          <ol><li>Selecciona un snapshot cifrado conocido.</li>
            <li>Confirma por escrito para restaurar en un directorio privado de preparación.</li>
            <li>El sistema verifica el archivo SQLite y la estructura de los archivos TAR.</li>
            <li>Revisa la copia y realiza el cambio de producción manualmente, deteniendo los servicios correspondientes.</li>
          </ol>
        </div>
        {mostRecent?.state==='failed'&&<Info kind="error">La última tarea falló: {mostRecent.error||'Revisa el historial.'}</Info>}
      </section>
    </div>
    <section className="bk-card">
      <header className="bk-section-head">
        <div><h3><FileClock size={18}/> Historial de snapshots y operaciones</h3>
          <p>El cifrado y la retención son responsabilidad del repositorio restic configurado.</p></div>
        <div className="bk-tabs">
          <button className={tab==='snapshots'?'active':''} onClick={()=>setTab('snapshots')}>Snapshots</button>
          <button className={tab==='jobs'?'active':''} onClick={()=>setTab('jobs')}>Trabajos</button>
        </div>
      </header>
      {tab==='snapshots'&&<div className="bk-list">{sorted.length?sorted.map(s=>
        <div className="bk-row" key={s.id}>
          <div className="bk-icon"><Archive size={19}/></div>
          <div className="bk-row-name"><strong>{s.id?.slice(0,12)}</strong>
            <span>{when(s.time)} · {s.hostname||'Host no identificado'}</span>
          </div>
          <button className="bk-button bk-outline" disabled={!!active||!configured}
            onClick={()=>prepare('restore',s.id)}><Download size={15}/> Preparar recuperación</button>
        </div>):<div className="bk-empty"><Archive size={25}/>
          <strong>Sin snapshots</strong><span>Los respaldos completos aparecerán aquí después de ejecutarlos.</span>
        </div>}</div>}
      {tab==='jobs'&&<div className="bk-list">{jobs.length?jobs.map(j=>
        <div className="bk-row" key={j.id}>
          <div className="bk-icon"><Clock3 size={19}/></div>
          <div className="bk-row-name"><strong>{labels[j.operation]||j.operation}</strong>
            <span>{when(j.created)} · {j.snapshot?.slice(0,12)||'Repositorio HomeLab OS'}</span>
            {j.error&&<small className="bk-job-error">{j.error}</small>}
            {j.result?.destination&&<small className="bk-job-result">
              Recuperación disponible en: {j.result.destination}</small>}
            {j.result?.verified&&<small>Comprobación de repositorio completada.</small>}
          </div>
          <Pill type={j.state==='success'?'good':j.state==='failed'?'danger':'warning'}>
            {j.state==='success'?'Correcto':j.state==='failed'?'Fallido':'En proceso'}</Pill>
        </div>):<div className="bk-empty"><FileClock size={26}/>
          <strong>Sin operaciones</strong><span>Los trabajos manuales y programados se guardan en el historial local.</span>
        </div>}</div>}
    </section>
    <div className="bk-disclaimer"><AlertTriangle size={16}/>
      No se guardan contraseñas en la interfaz. Las exportaciones se preparan temporalmente en disco local antes de cifrarse:
      protege físicamente el equipo y conserva una copia independiente de la clave. Los respaldos no sustituyen
      un simulacro periódico de restauración.
    </div>
    {dialog&&<div className="bk-modal-overlay" onMouseDown={e=>e.target===e.currentTarget&&setDialog(null)}>
      <div className="bk-modal" role="dialog" aria-modal="true" aria-label="Confirmar operación de respaldo">
        <div className="bk-modal-warning"><AlertTriangle size={24}/></div>
        <h3>{labels[dialog.action]}</h3>
        <p>{dialog.action==='restore'?'Se extraerá una copia cifrada a una carpeta privada de recuperación; los datos actuales NO serán sobrescritos.':
          dialog.action==='verify'?'Se comprobarán las estructuras y referencias del repositorio restic. No modifica aplicaciones.':
          'Se exportarán todos los recursos configurados, se cifrarán en restic y se aplicará la retención de snapshots HomeLab.'}</p>
        {dialog.snapshot&&<div className="bk-snapshot-id">Snapshot: <strong>{dialog.snapshot}</strong></div>}
        <label>Para continuar, escribe exactamente <strong>{phrase}</strong>
          <input value={typed} onChange={e=>setTyped(e.target.value)}
            autoComplete="off" placeholder={phrase}/></label>
        <div className="bk-modal-buttons">
          <button className="bk-button bk-outline" onClick={()=>setDialog(null)} disabled={submitting}>Cancelar</button>
          <button className="bk-button bk-main" onClick={submit}
            disabled={submitting||typed!==phrase}>{submitting?'Iniciando…':'Confirmar'}</button>
        </div>
      </div>
    </div>}
  </div>;
}
