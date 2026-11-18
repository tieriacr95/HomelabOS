import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, Copy, Flame, History,
  KeyRound, LockKeyhole, Network, Radio, RefreshCw, Search, Server,
  ShieldAlert, ShieldCheck, ShieldQuestion, Terminal, Wifi } from 'lucide-react';
import './security-center.css';

const tabs = [
  { id: 'findings', name: 'Hallazgos', icon: ShieldAlert },
  { id: 'ports', name: 'Puertos abiertos', icon: Network },
  { id: 'firewall', name: 'Firewall', icon: Flame },
  { id: 'ssh', name: 'SSH', icon: LockKeyhole },
  { id: 'events', name: 'Autenticación', icon: KeyRound },
  { id: 'kernel', name: 'Kernel e historial', icon: Terminal },
];
const levels = {
  critical: { label: 'Crítico', css: 'critical' },
  high: { label: 'Alto', css: 'high' },
  medium: { label: 'Medio', css: 'medium' },
  low: { label: 'Bajo', css: 'low' },
  info: { label: 'Informativo', css: 'info' },
};

function Tag({ status, children }) {
  return <span className={'sc-tag sc-tag-' + status}>{children}</span>;
}
function Stat({ icon: Icon, label, value, note, level }) {
  return <div className="sc-stat">
    <div className="sc-stat-label"><span>{label}</span><Icon size={17}/></div>
    <strong className={level ? 'sc-stat-'+level : ''}>{value}</strong><small>{note}</small>
  </div>;
}
function NoData({ children }) {
  return <div className="sc-empty"><ShieldQuestion size={30}/><span>{children}</span></div>;
}
function Field({ label, value, status }) {
  return <div className="sc-field"><span>{label}</span>
    <div>{status ? <Tag status={status}>{value ?? 'Sin información'}</Tag> :
      <strong>{value == null ? 'No disponible' : String(value)}</strong>}</div>
  </div>;
}
function Severity({ level }) {
  const x = levels[level] || levels.info;
  return <Tag status={x.css}>{x.label}</Tag>;
}

export default function SecurityCenter({ request }) {
  const [report, setReport] = useState(null);
  const [history, setHistory] = useState([]);
  const [tab, setTab] = useState('findings');
  const [filter, setFilter] = useState('all');
  const [portsSearch, setPortsSearch] = useState('');
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const getReport = useCallback(async (fresh=false) => {
    setBusy(true);
    try {
      const result = await request('/api/security/report'+(fresh?'?refresh=true':''));
      setReport(result); setError('');
    } catch(e) { setError(e.message || 'No se pudo completar la auditoría de seguridad'); }
    finally { setBusy(false); }
  },[request]);
  const getHistory = useCallback(async (selected=7) => {
    try { const result = await request('/api/security/history?days='+selected);
      setHistory(result.items || []);
    } catch(e) { /* show report even if history is temporarily unavailable */ }
  },[request]);

  useEffect(() => { getReport(); getHistory(days); }, [getReport, getHistory]);
  async function refresh() { await getReport(true); await getHistory(days); }

  const findings = report?.findings || [];
  const visibleFindings = useMemo(()=>findings.filter(f=>filter==='all'||f.severity===filter),[findings,filter]);
  const ports = report?.ports?.items || [];
  const visiblePorts = useMemo(()=>ports.filter(p=>
    [p.address,p.port,p.protocol,p.scope,p.process].join(' ').toLowerCase()
      .includes(portsSearch.toLowerCase().trim())),[ports,portsSearch]);

  async function copyReport() {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(report,null,2));
      setMessage('Informe copiado al portapapeles.');
    } catch (_) { setMessage('No fue posible copiar el informe desde este navegador.'); }
  }
  const summary = report?.summary;

  return <div className="sc-root">
    <div className="sc-heading">
      <div><div className="eyebrow">FEDORA · SECURITY CENTER v0.4</div>
        <h2>Seguridad del sistema</h2>
        <p>Auditoría de configuración y superficie de exposición, sin cambios automáticos.</p>
      </div>
      <div className="sc-actions">
        <button className="sc-button" onClick={copyReport} disabled={!report}><Copy size={16}/> Copiar informe</button>
        <button className="sc-button sc-primary" onClick={refresh} disabled={busy}>
          <RefreshCw size={16} className={busy?'spin':''}/> {busy?'Analizando…':'Analizar ahora'}</button>
      </div>
    </div>
    {error && <div className="sc-notice sc-error"><AlertTriangle size={17}/>{error}</div>}
    {message && <div className="sc-notice"><CheckCircle2 size={17}/>{message}</div>}
    <div className="sc-summary">
      <Stat label="Hallazgos críticos / altos" value={summary ? summary.critical+summary.high : '—'}
        note="Priorizados para revisión" icon={ShieldAlert} level={summary?.critical||summary?.high?'bad':'good'}/>
      <Stat label="Hallazgos medios" value={summary?.medium??'—'}
        note="Recomendaciones de seguridad" icon={AlertTriangle} level={summary?.medium?'warning':''}/>
      <Stat label="Sockets fuera de loopback" value={summary?.visible_ports??'—'}
        note="No implica exposición pública" icon={Radio}/>
      <Stat label="Comprobaciones evaluadas" value={summary?summary.checks_available+'/'+summary.checks_total:'—'}
        note="Las no disponibles no se consideran seguras" icon={ShieldCheck}/>
    </div>
    <div className="sc-context">
      <span><Server size={15}/>{report?.hostname || 'Equipo Fedora'}</span>
      <span><Clock3 size={15}/>{report?.timestamp?new Date(report.timestamp*1000).toLocaleString('es-CR'):'Pendiente de análisis'}</span>
      <span><ShieldCheck size={15}/> Solo lectura</span>
      {busy && <span className="sc-loading"><RefreshCw className="spin" size={13}/> Actualizando</span>}
    </div>

    <section className="sc-panel">
      <div className="sc-tabs" role="tablist" aria-label="Secciones de seguridad">
        {tabs.map(({id,name,icon:Icon})=><button key={id} role="tab"
          aria-selected={tab===id} className={tab===id?'active':''}
          onClick={()=>setTab(id)}><Icon size={15}/>{name}</button>)}
      </div>
      {!report && !error && <NoData>Consultando la configuración real del sistema…</NoData>}
      {report && tab==='findings' && <div className="sc-content">
        <div className="sc-section-title"><div><h3>Hallazgos y recomendaciones</h3>
          <p>Severidad orientativa, calculada exclusivamente con los datos que pudieron consultarse.</p></div>
          <select aria-label="Filtrar severidad" value={filter} onChange={e=>setFilter(e.target.value)}>
            <option value="all">Todos los niveles</option>
            {Object.entries(levels).map(([key,v])=><option value={key} key={key}>{v.label}</option>)}
          </select>
        </div>
        {visibleFindings.length ? <div className="sc-findings">{visibleFindings.map(item=>
          <article className={'sc-finding sc-finding-'+item.severity} key={item.id}>
            <div className="sc-finding-top"><Severity level={item.severity}/><strong>{item.title}</strong></div>
            <p>{item.detail}</p>
            <div className="sc-recommendation"><ShieldCheck size={16}/><span>{item.recommendation}</span></div>
          </article>)}</div> : <NoData>{findings.length?'No hay hallazgos para este filtro.':
            'Sin hallazgos en las comprobaciones disponibles. Esto no garantiza que el equipo sea seguro.'}</NoData>}
        {summary?.checks_available<summary?.checks_total && <div className="sc-unavailable">
          <ShieldQuestion size={18}/> Algunas comprobaciones no pudieron completarse. Revisa SSH, permisos del journal y acceso a sockets antes de interpretar el resultado.
        </div>}
      </div>}
      {report && tab==='ports' && <div className="sc-content">
        <div className="sc-section-title"><div><h3>Puertos de escucha TCP y UDP</h3>
          <p>Se muestran sockets locales; la accesibilidad desde otras redes depende de firewalld, nftables y el router.</p></div>
          <Tag status={report.ports.available?'good':'medium'}>{report.ports.available?report.ports.total+' sockets detectados':'No disponible'}</Tag>
        </div>
        {report.ports.available?<>
          <div className="sc-search"><Search size={16}/><input value={portsSearch}
            onChange={e=>setPortsSearch(e.target.value)} placeholder="Buscar puerto, protocolo o proceso…"
            aria-label="Buscar puertos"/></div>
          <div className="sc-table-scroller"><table className="sc-table">
            <thead><tr><th>Protocolo</th><th>Dirección de escucha</th><th>Puerto</th><th>Alcance de enlace</th><th>Proceso</th></tr></thead>
            <tbody>{visiblePorts.length ? visiblePorts.map((p,i)=><tr key={p.protocol+p.address+p.port+i}>
              <td>{p.protocol.toUpperCase()}</td><td className="sc-code">{p.address}</td>
              <td className="sc-code">{p.port}</td>
              <td><Tag status={p.scope==='loopback'?'good':p.scope==='unknown'?'medium':'info'}>
                {p.scope==='loopback'?'Local':p.scope==='all'?'Todas las interfaces':p.scope==='interface'?'Interfaz específica':'Indeterminado'}</Tag></td>
              <td>{p.process||'No identificado'}</td>
            </tr>):<tr><td className="sc-table-empty" colSpan="5">No hay resultados.</td></tr>}</tbody>
          </table></div>
          {report.ports.truncated&&<p className="sc-disclaimer">Inventario truncado a los primeros 200 sockets.</p>}
        </>:<NoData>{report.ports.error}</NoData>}
      </div>}
      {report && tab==='firewall' && <div className="sc-content">
        <div className="sc-section-title"><div><h3>Firewall de Fedora</h3>
          <p>Vista de firewalld. No representa reglas directas de nftables ni reglas creadas por Docker.</p></div>
          <Tag status={report.firewall.state==='running'?'good':'medium'}>
            {report.firewall.state==='running'?'Ejecutándose':report.firewall.state==='not-running'?'No activo':'Desconocido'}</Tag>
        </div>
        <div className="sc-fields">
          <Field label="Servicio systemd" value={report.firewall.service}/>
          <Field label="Estado firewalld" value={report.firewall.state}/>
          <Field label="Zonas activas" value={report.firewall.zones.length}/>
          <Field label="Herramienta disponible" value={report.firewall.available?'Sí':'No'}/>
        </div>
        {report.firewall.zones.length ? <div className="sc-zones">
          {report.firewall.zones.map(zone=><article key={zone.name} className="sc-zone">
            <header><Flame size={17}/><strong>{zone.name}</strong></header>
            <Field label="Interfaces" value={zone.interfaces.join(', ')||'Ninguna listada'}/>
            <Field label="Orígenes" value={zone.sources.join(', ')||'No especificados'}/>
            <Field label="Servicios permitidos" value={zone.services.join(', ')||'Ninguno listado'}/>
            <Field label="Puertos declarados" value={zone.ports.join(', ')||'Ninguno listado'}/>
          </article>)}</div> : <NoData>{report.firewall.error ||
            'No se detectaron zonas activas. Comprueba el estado de firewalld antes de sacar conclusiones.'}</NoData>}
      </div>}
      {report && tab==='ssh' && <div className="sc-content">
        <div className="sc-section-title"><div><h3>Configuración efectiva de OpenSSH</h3>
          <p>Consulta de sshd -T para una conexión de muestra. Las reglas Match pueden variar según origen o usuario.</p></div>
          <Tag status={report.ssh.service==='active'?'info':'medium'}>{report.ssh.service}</Tag>
        </div>
        {report.ssh.available?<div className="sc-fields">
          {[
            ['PermitRootLogin','permitrootlogin'],['PasswordAuthentication','passwordauthentication'],
            ['PubkeyAuthentication','pubkeyauthentication'],
            ['PermitEmptyPasswords','permitemptypasswords'],
            ['MaxAuthTries','maxauthtries'],['Port','port'],
            ['X11Forwarding','x11forwarding']
          ].map(([label,key])=><Field key={key} label={label}
            value={report.ssh.effective[key]||'No determinado'}/>)}
        </div>:<NoData>{report.ssh.error||'No hay configuración SSH disponible.'}</NoData>}
        <div className="sc-info"><LockKeyhole size={18}/> No cambies la autenticación SSH sin comprobar que conservas un método alternativo de acceso.</div>
      </div>}
      {report && tab==='events' && <div className="sc-content">
        <div className="sc-section-title"><div><h3>Eventos de autenticación · 24 horas</h3>
          <p>Conteos aproximados desde el journal accesible; nunca se muestran nombres de usuario, IP ni mensajes originales.</p></div>
          <Tag status={report.authentication.available?'good':'medium'}>
            {report.authentication.available?'Journal disponible':'Permisos insuficientes o no disponible'}</Tag>
        </div>
        {report.authentication.available?<div className="sc-auth-grid">
          <Stat icon={ShieldAlert} label="Fallos SSH" value={report.authentication.ssh_failed} note="Intentos fallidos detectados"/>
          <Stat icon={CheckCircle2} label="Accesos SSH aceptados" value={report.authentication.ssh_accepted} note="Entradas reconocidas"/>
          <Stat icon={LockKeyhole} label="Fallos de sudo" value={report.authentication.sudo_failures} note="Errores de autenticación reconocidos"/>
          <Stat icon={History} label="Líneas analizadas" value={report.authentication.scanned_lines} note={report.authentication.truncated?'Consulta limitada':'Últimas 24 horas'}/>
        </div>:<NoData>{report.authentication.error || 'Los eventos del sistema no están disponibles para este usuario.'}</NoData>}
        <div className="sc-info"><ShieldCheck size={17}/> No se elevan permisos para leer logs. Si el journal es inaccesible, su estado queda como no evaluado.</div>
      </div>}
      {report && tab==='kernel' && <div className="sc-content">
        <div className="sc-section-title"><div><h3>Endurecimiento del kernel</h3>
          <p>Configuraciones sysctl de solo lectura. Su valor apropiado puede variar por sistema.</p></div></div>
        <div className="sc-fields">
          {[
            ['ASLR (randomize_va_space)','aslr'],['Protección hardlinks','protected_hardlinks'],
            ['Protección symlinks','protected_symlinks'],['Restricción punteros kernel','kptr_restrict'],
            ['Restricción dmesg','dmesg_restrict']
          ].map(([label,key])=><Field key={key} label={label} value={report.kernel[key]}/>)}
          <Field label="SELinux en ejecución" value={report.selinux.mode}/>
          <Field label="SELinux persistente" value={report.selinux.configured}/>
          <Field label="Helper privilegiado de actualizaciones" value={report.privileged_package_helper?'Instalado':'No instalado'}/>
        </div>
        <div className="sc-history-head">
          <h3><History size={17}/> Historial agregado de auditorías</h3>
          <select value={days} onChange={e=>{const n=Number(e.target.value);setDays(n);getHistory(n);}}>
            <option value={7}>7 días</option><option value={30}>30 días</option>
          </select>
        </div>
        {history.length?<div className="sc-table-scroller"><table className="sc-table">
          <thead><tr><th>Fecha</th><th>Críticos</th><th>Altos</th><th>Medios</th><th>Interfaces</th><th>Controles</th></tr></thead>
          <tbody>{history.map((row,i)=><tr key={row.timestamp+'-'+i}>
            <td>{new Date(row.timestamp*1000).toLocaleString('es-CR')}</td>
            <td>{row.critical}</td><td>{row.high}</td><td>{row.medium}</td>
            <td>{row.non_loopback??'—'}</td><td>{row.checks_available}/5</td>
          </tr>)}</tbody>
        </table></div>:<NoData>El historial comenzará a llenarse después de realizar auditorías.</NoData>}
      </div>}
    </section>
    <div className="sc-footer"><ShieldCheck size={16}/>
      Este panel no realiza una prueba de penetración ni determina exposición desde Internet. No modifica SELinux, SSH, firewall ni permisos.
    </div>
  </div>;
}
