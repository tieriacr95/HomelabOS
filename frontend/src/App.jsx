import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowUpFromLine, Bell, Box, Check,
  CheckCircle2, ChevronRight, CircleHelp, Clock3, Container, Cpu, Database,
  ExternalLink, Gauge, HardDrive, HeartPulse, LayoutDashboard, LockKeyhole,
  LogOut, Menu, Monitor, Network, RefreshCw, RotateCw, Server, Settings2,
  Shield, ShieldCheck, Terminal, Thermometer, Wifi, WifiOff, X, Zap
} from 'lucide-react';

const tabs = [
  { id: 'overview', name: 'Resumen', icon: LayoutDashboard },
  { id: 'fedora', name: 'Sistema Fedora', icon: Monitor },
  { id: 'docker', name: 'Docker', icon: Container },
  { id: 'network', name: 'Red y servicios', icon: Network },
  { id: 'security', name: 'Seguridad', icon: ShieldCheck },
  { id: 'audit', name: 'Actividad', icon: Clock3 },
  { id: 'settings', name: 'Configuración', icon: Settings2 }
];

async function api(path, opts = {}, csrf = null) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (csrf) headers['X-CSRF-Token'] = csrf;
  const response = await fetch(path, { credentials: 'same-origin', ...opts, headers });
  let json = {};
  try { json = await response.json(); } catch (_) { /* invalid response */ }
  if (!response.ok) {
    const err = new Error(typeof json.detail === 'string' ? json.detail : 'Error de comunicación');
    err.status = response.status;
    throw err;
  }
  return json;
}

const fmt = new Intl.NumberFormat('es-CR', { maximumFractionDigits: 1 });
const size = (bytes) => {
  if (bytes == null) return '—';
  if (bytes < 1024) return fmt.format(bytes) + ' B';
  const unit = ['KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)) - 1, 3);
  return fmt.format(bytes / Math.pow(1024, i + 1)) + ' ' + unit[i];
};
const pct = (n) => (n == null ? '—' : fmt.format(n) + '%');
const time = (unix) => unix ? new Date(unix * 1000).toLocaleString('es-CR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
const yes = (s) => s === 'running' || s === 'active' || s === 'enforcing';

function Pill({ positive, children }) {
  return <span className={'pill ' + (positive ? 'positive' : 'negative')}>
    <span className="pill-dot" />{children}
  </span>;
}
function Title({ eyebrow, title, sub, aside }) {
  return <div className="section-heading"><div><div className="eyebrow">{eyebrow}</div>
    <h2>{title}</h2>{sub && <p>{sub}</p>}</div>{aside}</div>;
}
function Panel({ title, icon: Icon, children, action, className = '' }) {
  return <section className={'panel ' + className}>
    {title && <header className="panel-head"><span className="panel-title">{Icon && <Icon size={17} />} {title}</span>{action}</header>}
    {children}
  </section>;
}
function Metric({ icon: Icon, label, value, help, percentage, color = 'mint' }) {
  return <div className="metric-card">
    <div className="metric-top"><div className={'metric-icon ' + color}><Icon size={18}/></div><span className="metric-label">{label}</span></div>
    <div className="metric-value">{value}</div>
    <div className="metric-bottom"><span>{help}</span>{percentage != null && <span>{pct(percentage)}</span>}</div>
    {percentage != null && <div className="progress-track"><div className={'progress-fill ' + (percentage >= 90 ? 'danger' : '')} style={{ width: Math.min(100, percentage) + '%' }}/></div>}
  </div>;
}
function Empty({ icon: Icon = CircleHelp, title, detail }) {
  return <div className="empty"><Icon size={25}/><strong>{title}</strong><p>{detail}</p></div>;
}
function Trend({ history = [], field = 'cpu', color = '#62e2c7' }) {
  const values = history.slice(-90);
  const path = values.map((v, i) => {
    const x = values.length === 1 ? 0 : (i / (values.length - 1)) * 640;
    const y = 130 - Math.min(100, Math.max(0, Number(v[field]) || 0)) * 1.2;
    return (i ? 'L' : 'M') + x.toFixed(1) + ',' + y.toFixed(1);
  }).join(' ');
  return <div className="chart-box">
    {values.length < 2 ? <div className="chart-placeholder">El historial aparecerá después de recibir al menos dos muestras (1 minuto entre muestras).</div> :
      <svg viewBox="0 0 640 140" preserveAspectRatio="none" role="img" aria-label={'Evolución de ' + field}>
        {[10, 70, 130].map(y => <line key={y} x1="0" y1={y} x2="640" y2={y} stroke="#242e3b" strokeDasharray="4 6"/>)}
        <path d={path} fill="none" stroke={color} strokeWidth="2.8" strokeLinejoin="round" strokeLinecap="round"/>
      </svg>}
  </div>;
}

function AuthPage({ configured, onAuth }) {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(e) {
    e.preventDefault(); setError(''); setBusy(true);
    try {
      const result = await api(configured ? '/api/auth/login' : '/api/auth/setup', {
        method: 'POST',
        body: JSON.stringify(configured ? { username, password } : { username, password, setup_token: token })
      });
      onAuth({ configured: true, authenticated: true, ...result });
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <div className="auth-root">
    <div className="auth-glow"/>
    <div className="auth-card">
      <div className="brand auth-brand"><div className="brand-mark"><Box size={24}/></div><span>HomeLab <b>OS</b></span></div>
      <div className="auth-icon"><LockKeyhole size={26}/></div>
      <div className="eyebrow">FEDORA + HOMELAB</div>
      <h1>{configured ? 'Bienvenido de nuevo' : 'Configura tu HomeLab'}</h1>
      <p>{configured ? 'Inicia sesión para administrar tu infraestructura.' : 'Crea la primera cuenta administrativa utilizando el token de instalación.'}</p>
      <form onSubmit={submit}>
        <label>Usuario<input autoComplete="username" required minLength={3} value={username} onChange={e => setUsername(e.target.value)} placeholder="admin"/></label>
        <label>Contraseña<input type="password" autoComplete={configured ? 'current-password' : 'new-password'} minLength={configured ? undefined : 12} required value={password} onChange={e => setPassword(e.target.value)} placeholder="Tu contraseña segura"/></label>
        {!configured && <label>Token de instalación<input type="password" required value={token} onChange={e => setToken(e.target.value)} placeholder="HOMELAB_SETUP_TOKEN"/></label>}
        {error && <div className="form-error"><AlertTriangle size={16}/>{error}</div>}
        <button className="btn primary full" disabled={busy}>{busy ? 'Validando…' : configured ? 'Ingresar al dashboard' : 'Crear administrador'}<ChevronRight size={17}/></button>
      </form>
      <div className="auth-foot"><Shield size={15}/> Acceso local con sesiones seguras y controles CSRF</div>
    </div>
    <div className="auth-caption">HomeLab OS · Tu infraestructura, en un solo lugar</div>
  </div>;
}

function ContainerRows({ items, onRestart, compact = false }) {
  return <div className="item-list">{items.map(c => <div className="item-row" key={c.name}>
    <div className={'item-icon ' + (c.state === 'running' ? 'good' : 'muted')}><Container size={18}/></div>
    <div className="item-text"><strong>{c.name}</strong><span>{c.image || 'Imagen desconocida'}{!compact && c.ports ? ' · ' + c.ports : ''}</span></div>
    <span className={'state-text ' + (c.state === 'running' ? 'green' : 'red')}>{c.state === 'running' ? 'Activo' : c.state}</span>
    {!compact && <button className="btn ghost small" title={c.restart_allowed ? 'Reiniciar contenedor' : 'No está en la lista permitida'} disabled={!c.restart_allowed} onClick={() => onRestart(c.name)}><RotateCw size={14}/> Reiniciar</button>}
  </div>)}</div>;
}

function App() {
  const [auth, setAuth] = useState(null);
  const [tab, setTab] = useState('overview');
  const [data, setData] = useState(null);
  const [history, setHistory] = useState([]);
  const [audit, setAudit] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [restart, setRestart] = useState(null);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [hours, setHours] = useState(24);

  useEffect(() => { api('/api/auth/status').then(setAuth).catch(() => setAuth({ configured: true, authenticated: false })); }, []);
  const refresh = useCallback(async (showSpinner = false) => {
    if (showSpinner) setBusy(true);
    try {
      const [d, h] = await Promise.all([api('/api/dashboard'), api('/api/history?hours=' + hours)]);
      setData(d); setHistory(h.items || []); setError('');
    } catch (err) {
      setError(err.message);
      if (err.status === 401) setAuth({ configured: true, authenticated: false });
    } finally { setBusy(false); }
  }, [hours]);
  useEffect(() => {
    if (!auth?.authenticated) return;
    refresh(true);
    const t = setInterval(() => refresh(false), 20000);
    return () => clearInterval(t);
  }, [auth?.authenticated, refresh]);
  useEffect(() => {
    if (tab !== 'audit' || !auth?.authenticated) return;
    api('/api/audit').then(r => setAudit(r.items || [])).catch(e => setError(e.message));
  }, [tab, auth?.authenticated]);
  const host = data?.host;
  const containers = host?.containers || [];
  const running = containers.filter(c => c.state === 'running').length;
  const rootDisk = host?.disks?.find(d => d.mount === '/') || host?.disks?.[0];
  const onlineServices = (data?.services || []).filter(s => s.online).length;
  const agentOnline = !!data?.agent_online;
  const activePage = tabs.find(t => t.id === tab) || tabs[0];

  async function doRestart() {
    if (!restart) return;
    setBusy(true);
    try {
      await api('/api/containers/' + encodeURIComponent(restart) + '/restart', {
        method: 'POST', body: JSON.stringify({ confirm: true })
      }, auth.csrf);
      setToast('Se solicitó reiniciar ' + restart);
      setRestart(null);
      await refresh();
    } catch (e) { setToast(e.message); setRestart(null); } finally { setBusy(false); }
  }
  async function logout() {
    try { await api('/api/auth/logout', { method: 'POST' }, auth.csrf); } catch (_) { /* clear local state */ }
    setAuth({ configured: true, authenticated: false });
    setData(null);
  }
  if (!auth) return <div className="app-loading"><Box size={35}/> Cargando HomeLab OS…</div>;
  if (!auth.authenticated) return <AuthPage configured={auth.configured} onAuth={setAuth}/>;

  return <div className="shell">
    <aside className={'sidebar ' + (mobileMenu ? 'sidebar-open' : '')}>
      <div className="brand"><div className="brand-mark"><Box size={23}/></div><span>HomeLab <b>OS</b></span></div>
      <div className="sidebar-caption">WORKSPACE</div>
      <nav className="nav-list">{tabs.map(t => <button key={t.id} className={'nav-item ' + (tab === t.id ? 'selected' : '')} onClick={() => { setTab(t.id); setMobileMenu(false); }}><t.icon size={19}/>{t.name}{tab === t.id && <ChevronRight className="nav-arrow" size={16}/>}</button>)}</nav>
      <div className="sidebar-bottom">
        <div className="host-card"><div className="host-card-top"><Server size={19}/><Pill positive={agentOnline}>{agentOnline ? 'Conectado' : 'Sin agente'}</Pill></div><strong>{host?.hostname || 'Fedora Workstation'}</strong><span>Agente local · 127.0.0.1</span></div>
        <button className="user-item" onClick={logout}><div className="avatar">{auth.username?.slice(0,1).toUpperCase()}</div><span><strong>{auth.username}</strong><small>Administrador</small></span><LogOut size={17}/></button>
      </div>
    </aside>
    {mobileMenu && <div className="mobile-overlay" onClick={() => setMobileMenu(false)}/>}
    <main className="main">
      <div className="topbar"><div className="topbar-title">
        <button className="mobile-menu-btn" onClick={() => setMobileMenu(true)} aria-label="Abrir menú"><Menu size={22}/></button>
        <span className="breadcrumb">HomeLab OS</span><ChevronRight size={14}/><span>{activePage.name}</span>
      </div><div className="topbar-actions"><div className="live-tag"><span className={agentOnline ? 'live-dot' : 'live-dot off'}/>{agentOnline ? 'Monitor activo' : 'Agente desconectado'}</div><button className="icon-button" title="Actualizar ahora" onClick={() => refresh(true)} disabled={busy}><RefreshCw size={17} className={busy ? 'spin' : ''}/></button></div></div>
      <div className="content">
        {error && <div className="notice danger"><AlertTriangle size={17}/>{error}<button onClick={() => setError('')}><X size={15}/></button></div>}
        {toast && <div className="notice info"><Check size={17}/>{toast}<button onClick={() => setToast('')}><X size={15}/></button></div>}
        {tab === 'overview' && <>
          <div className="hero"><div className="hero-content"><div className="eyebrow">CENTRO DE OPERACIONES · FEDORA</div><h1>Tu HomeLab,<br/><em>bajo control.</em></h1><p>Estado de tu sistema y tus servicios, en tiempo real y desde un solo lugar.</p><div className="hero-footer"><Pill positive={agentOnline}>{agentOnline ? 'Host disponible' : 'Host sin conexión'}</Pill><span>Última lectura: {time(data?.timestamp)}</span></div></div><div className="hero-art"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><Server size={88} strokeWidth={1.05}/></div></div>
          <div className="metrics">
            <Metric icon={Cpu} label="Procesador" value={pct(host?.cpu?.percent)} help={host ? host.cpu.cores + ' hilos lógicos' : 'Agente no conectado'} percentage={host?.cpu?.percent}/>
            <Metric icon={Gauge} label="Memoria RAM" value={pct(host?.memory?.percent)} help={host ? size(host.memory.used) + ' utilizados' : 'Sin datos'} percentage={host?.memory?.percent} color="blue"/>
            <Metric icon={HardDrive} label="Disco principal" value={pct(rootDisk?.percent)} help={rootDisk ? size(rootDisk.free) + ' disponibles' : 'Sin datos'} percentage={rootDisk?.percent} color="purple"/>
            <Metric icon={Container} label="Contenedores" value={agentOnline ? String(running) : '—'} help={host?.docker_error ? 'Docker no disponible' : containers.length + ' en total'} color="amber"/>
          </div>
          <div className="split two-thirds"><Panel title="Rendimiento del sistema" icon={Activity} action={<select value={hours} onChange={e => setHours(Number(e.target.value))} aria-label="Rango de historial"><option value="1">1 hora</option><option value="6">6 horas</option><option value="24">24 horas</option><option value="168">7 días</option></select>}>
            <div className="chart-label"><span className="color-dot"/><strong>CPU</strong><span className="chart-current">{pct(host?.cpu?.percent)}</span></div><Trend history={history} field="cpu"/>
            <div className="chart-label"><span className="color-dot violet"/><strong>RAM</strong><span className="chart-current">{pct(host?.memory?.percent)}</span></div><Trend history={history} field="memory" color="#a591ff"/>
          </Panel><Panel title="Estado y alertas" icon={Bell} action={<span className="count-tag">{data?.alerts?.length || 0}</span>}>
            {(data?.alerts || []).length === 0 ? <Empty icon={CheckCircle2} title="Sin alertas" detail="No se detectan umbrales excedidos ni servicios caídos."/> : <div className="alerts">{data.alerts.map((a,i) => <div className="alert-row" key={i}><AlertTriangle size={16}/><span>{a.message}</span></div>)}</div>}
          </Panel></div>
          <div className="split equal"><Panel title="Contenedores Docker" icon={Container} action={<button className="text-button" onClick={() => setTab('docker')}>Ver todos <ChevronRight size={15}/></button>}>
            {containers.length ? <ContainerRows compact items={containers.slice(0,5)}/> : <Empty icon={Container} title="No hay contenedores visibles" detail={host?.docker_error || 'Conecta el agente para descubrir Docker.'}/>}
          </Panel><Panel title="Servicios monitoreados" icon={HeartPulse} action={<button className="text-button" onClick={() => setTab('network')}>Explorar <ChevronRight size={15}/></button>}>
            {(data?.services || []).length ? <div className="item-list">{data.services.slice(0,5).map(s => <div className="item-row" key={s.name}><div className={'item-icon ' + (s.online ? 'good' : 'muted')}><Server size={18}/></div><div className="item-text"><strong>{s.name}</strong><span>{s.latency_ms != null ? s.latency_ms + ' ms' : s.error || s.url}</span></div><Pill positive={s.online}>{s.online ? 'Online' : 'Offline'}</Pill></div>)}</div> : <Empty icon={HeartPulse} title="Sin monitores configurados" detail="Habilita tus servicios desde config/services.json."/>}
          </Panel></div>
        </>}
        {tab === 'fedora' && <>
          <Title eyebrow="HARDWARE Y SISTEMA" title="Sistema Fedora" sub="Recursos y procesos reales, consultados desde el agente nativo." aside={<Pill positive={agentOnline}>{agentOnline ? host.hostname : 'Sin conexión'}</Pill>}/>
          <div className="metrics three"><Metric icon={Cpu} label="CPU" value={pct(host?.cpu?.percent)} help={host ? host.cpu.cores + ' hilos' : 'No disponible'} percentage={host?.cpu?.percent}/><Metric icon={Gauge} label="RAM" value={pct(host?.memory?.percent)} help={size(host?.memory?.used) + ' / ' + size(host?.memory?.total)} percentage={host?.memory?.percent} color="blue"/><Metric icon={Clock3} label="Tiempo encendido" value={host ? Math.floor(host.uptime_seconds/86400) + ' días' : '—'} help={host ? Math.floor((host.uptime_seconds%86400)/3600) + ' horas adicionales' : 'Sin conexión'} color="purple"/></div>
          <div className="split equal"><Panel title="Particiones y almacenamiento" icon={HardDrive}>{host?.disks?.length ? host.disks.map(d => <div className="disk-item" key={d.mount}><div className="disk-line"><strong>{d.mount}</strong><span>{size(d.used)} / {size(d.total)}</span></div><div className="progress-track"><div className={'progress-fill ' + (d.percent >= 85 ? 'danger' : '')} style={{width: d.percent + '%'}}/></div><small>{d.device} · {d.fstype} · {pct(d.percent)}</small></div>) : <Empty title="Sin datos de disco" detail="Inicia el agente Fedora."/>}</Panel>
          <Panel title="Servicios systemd" icon={Settings2}>{host?.services ? Object.entries(host.services).map(([name,state]) => <div className="service-row" key={name}><div className="service-name"><Server size={16}/>{name}</div><Pill positive={yes(state)}>{state}</Pill></div>) : <Empty title="Sin datos de servicios" detail="Inicia el agente Fedora."/>}</Panel></div>
          <div className="split equal"><Panel title="Procesos por consumo de RAM" icon={Activity}>{host?.processes?.length ? <div className="item-list">{host.processes.map(p => <div className="item-row" key={p.pid}><div className="item-icon muted"><Terminal size={17}/></div><div className="item-text"><strong>{p.name || 'Proceso'}</strong><span>PID {p.pid} · {p.user}</span></div><span className="mono">{size(p.rss)}</span></div>)}</div> : <Empty title="Sin datos de procesos" detail="El agente recopila los principales procesos."/>}</Panel>
          <Panel title="Detalles del equipo" icon={Thermometer}><div className="kv"><span>Hostname</span><strong>{host?.hostname || '—'}</strong></div><div className="kv"><span>Carga (1, 5, 15 min)</span><strong>{host?.cpu?.load?.map(n => fmt.format(n)).join(' · ') || '—'}</strong></div><div className="kv"><span>SELinux</span><strong>{host?.selinux || '—'}</strong></div><div className="kv"><span>Tráfico recibido</span><strong>{size(host?.network?.bytes_recv)}</strong></div>{host?.temperatures?.length ? host.temperatures.map((t,i) => <div className="kv" key={i}><span>{t.label}</span><strong>{t.celsius}°C</strong></div>) : <div className="small-note">Sensores de temperatura no disponibles en este equipo.</div>}</Panel></div>
        </>}
        {tab === 'docker' && <>
          <Title eyebrow="INFRAESTRUCTURA" title="Docker y contenedores" sub="Inspecciona imágenes, estado y disponibilidad. Los reinicios requieren autorización previa." aside={<Pill positive={!host?.docker_error && agentOnline}>{host?.docker_error || (running + ' activos')}</Pill>}/>
          <div className="metrics three"><Metric icon={Container} label="Total" value={agentOnline && !host?.docker_error ? containers.length : '—'} help="Contenedores detectados"/><Metric icon={CheckCircle2} label="En ejecución" value={agentOnline && !host?.docker_error ? running : '—'} help="Estado running" color="blue"/><Metric icon={AlertTriangle} label="Detenidos" value={agentOnline && !host?.docker_error ? containers.length-running : '—'} help="Revisar servicios inactivos" color="amber"/></div>
          <Panel title="Inventario de contenedores" icon={Container}>{containers.length ? <ContainerRows items={containers} onRestart={setRestart}/> : <Empty icon={Container} title="Docker no disponible o sin contenedores" detail={host?.docker_error || 'El agente detectará los contenedores cuando Docker esté accesible.'}/>}</Panel>
          <div className="hint"><Shield size={17}/> Solo puedes reiniciar contenedores cuyos nombres estén en HOMELAB_ALLOWED_CONTAINERS. El panel no recibe acceso al socket de Docker.</div>
        </>}
        {tab === 'network' && <>
          <Title eyebrow="CONECTIVIDAD" title="Red y servicios" sub="Comprobaciones HTTP y estado de la conectividad del host."/>
          <div className="metrics three"><Metric icon={ArrowDownToLine} label="Datos recibidos" value={size(host?.network?.bytes_recv)} help="Acumulado desde arranque"/><Metric icon={ArrowUpFromLine} label="Datos enviados" value={size(host?.network?.bytes_sent)} help="Acumulado desde arranque" color="blue"/><Metric icon={Wifi} label="Servicios online" value={(data?.services || []).length ? onlineServices + '/' + data.services.length : '0'} help="Monitores habilitados" color="purple"/></div>
          <Panel title="Endpoints monitoreados" icon={HeartPulse}>{(data?.services || []).length ? data.services.map(s => <div className="service-row" key={s.name}><div className="service-detail"><strong>{s.name}</strong><small>{s.url}</small></div><div className="service-actions"><span>{s.latency_ms == null ? '—' : s.latency_ms + ' ms'}</span><Pill positive={s.online}>{s.online ? 'Disponible' : 'Sin respuesta'}</Pill></div></div>) : <Empty icon={WifiOff} title="Todavía no hay verificaciones activas" detail="Edita config/services.json y establece enabled: true para los servicios que tengas desplegados."/>}</Panel>
          <div className="hint"><Network size={17}/> Las verificaciones se ejecutan localmente. Activa únicamente URLs que tú controles.</div>
        </>}
        {tab === 'security' && <>
          <Title eyebrow="PROTECCIÓN" title="Seguridad del host" sub="Indicadores básicos de endurecimiento. No sustituyen una auditoría de vulnerabilidades."/>
          <div className="metrics three"><Metric icon={ShieldCheck} label="SELinux" value={host?.selinux || '—'} help="Modo de seguridad del sistema"/><Metric icon={Shield} label="firewalld" value={host?.services?.firewalld || '—'} help="Estado del firewall" color="blue"/><Metric icon={LockKeyhole} label="SSHD" value={host?.services?.sshd || '—'} help="Servicio de acceso remoto" color="purple"/></div>
          <Panel title="Controles de HomeLab OS" icon={ShieldCheck}><div className="security-list">
            <div><CheckCircle2 size={18}/><span><strong>Acceso web limitado a localhost</strong><small>El servidor escucha 127.0.0.1:8090 usando la red del host.</small></span></div>
            <div><CheckCircle2 size={18}/><span><strong>Sesiones HTTP-only y protección CSRF</strong><small>Las operaciones de cambio requieren sesión y token CSRF.</small></span></div>
            <div><CheckCircle2 size={18}/><span><strong>Agente no privilegiado</strong><small>Sin shell remoto ni permisos root predeterminados.</small></span></div>
            <div><CheckCircle2 size={18}/><span><strong>Acciones Docker con lista permitida</strong><small>Los reinicios son opt-in y quedan registrados en la auditoría.</small></span></div>
          </div></Panel>
          <div className="hint"><AlertTriangle size={17}/> Para publicar la aplicación fuera de casa, usa Cloudflare Access y HTTPS. Configura HOMELAB_COOKIE_SECURE=true en el servidor web.</div>
        </>}
        {tab === 'audit' && <>
          <Title eyebrow="AUDITORÍA" title="Registro de actividad" sub="Acciones de acceso y administración realizadas desde HomeLab OS." aside={<button className="btn secondary" onClick={() => api('/api/audit').then(r=>setAudit(r.items||[]))}><RefreshCw size={16}/> Actualizar</button>}/>
          <Panel title="Eventos recientes" icon={Clock3}>{audit.length ? <div className="item-list">{audit.map(a => <div className="item-row" key={a.id}><div className="item-icon good"><Activity size={17}/></div><div className="item-text"><strong>{a.action} · {a.target}</strong><span>{a.actor} · {time(a.timestamp)}</span></div><Pill positive={a.result === 'ok'}>{a.result}</Pill></div>)}</div> : <Empty icon={Clock3} title="Sin eventos" detail="Los inicios de sesión y reinicios de contenedores se registran aquí."/>}</Panel>
        </>}
        {tab === 'settings' && <>
          <Title eyebrow="PREFERENCIAS" title="Configuración" sub="Información del despliegue y conexiones del HomeLab."/>
          <Panel title="Conexiones" icon={Settings2}><div className="kv"><span>Interfaz web</span><strong>127.0.0.1:8090</strong></div><div className="kv"><span>Agente host</span><Pill positive={agentOnline}>{agentOnline ? 'Conectado' : 'Desconectado'}</Pill></div><div className="kv"><span>Monitores activos</span><strong>{data?.services?.length || 0}</strong></div><div className="kv"><span>Cuenta</span><strong>{auth.username}</strong></div></Panel>
          <Panel title="Próximos pasos" icon={Zap}><div className="settings-steps"><div><span>01</span><p><strong>Conecta el agente:</strong> ejecuta bash scripts/install.sh desde Fedora.</p></div><div><span>02</span><p><strong>Servicios:</strong> edita config/services.json para activar las verificaciones de Plex y tus aplicaciones.</p></div><div><span>03</span><p><strong>Reinicios:</strong> agrega nombres a HOMELAB_ALLOWED_CONTAINERS en .env y reinstala el agente.</p></div><div><span>04</span><p><strong>Acceso externo:</strong> configura Cloudflare Tunnel + Access antes de habilitar acceso desde Internet.</p></div></div></Panel>
        </>}
        <footer className="footer"><span>HomeLab OS v0.1.0</span><span>Diseñado para Fedora Linux · Actualización automática cada 20 s</span></footer>
      </div>
    </main>
    {restart && <div className="modal-overlay" role="presentation" onClick={() => setRestart(null)}><div className="modal" role="dialog" aria-modal="true" aria-label="Confirmar reinicio" onClick={e => e.stopPropagation()}><div className="modal-icon"><RotateCw size={24}/></div><h3>¿Reiniciar contenedor?</h3><p>Se reiniciará <strong>{restart}</strong>. Esto puede interrumpir temporalmente el servicio.</p><div className="modal-buttons"><button className="btn secondary" onClick={() => setRestart(null)}>Cancelar</button><button className="btn primary" disabled={busy} onClick={doRestart}>Sí, reiniciar</button></div></div></div>}
  </div>;
}
export default App;
