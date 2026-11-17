# HomeLab OS

**Centro local de administración Fedora + Docker + servicios HomeLab.**

Aplicación web oscura y responsive, accesible en **http://localhost:8090**. Tu computadora Fedora aporta métricas reales mediante un agente systemd de usuario. El contenedor web no necesita root ni acceso directo al socket Docker.

## Funciones incluidas

- **Vista general**: CPU, RAM, disco, contenedores, alertas e historial de uso.
- **Fedora**: procesos por RAM, sensores disponibles, uptime, tráfico de red, particiones y estado de servicios systemd.
- **Docker**: inventario de contenedores e imágenes, estados y reinicio por lista blanca con confirmación.
- **Servicios**: comprobaciones HTTP de endpoints que tú configures y alertas de disponibilidad.
- **Seguridad**: indicadores de SELinux, firewalld y SSH; sesiones HttpOnly, CSRF, cabeceras de seguridad y auditoría.
- **Histórico**: SQLite persistente, muestras de rendimiento y registro de acciones.
- **Respaldo**: script de copia consistente de SQLite con cifrado restic opcional.

## Instalación en Fedora

~~~bash
git clone https://github.com/tieriacr95/HomelabOS.git
cd HomelabOS
bash scripts/install.sh
~~~

Abre **http://localhost:8090** y crea tu cuenta. El instalador genera un token aleatorio:

~~~bash
grep '^HOMELAB_SETUP_TOKEN=' .env
~~~

**Requisitos:** Fedora Linux, Python 3 + venv, Docker Engine, Docker Compose v2, systemd --user y acceso de tu usuario a Docker. El instalador se ejecuta **sin sudo** y no sobrescribe los tokens existentes.

Consulta **[Guía completa de instalación](docs/INSTALL.md)**, que incluye monitoreo de Plex, Personal Planner, Cloudflare Tunnel, restauración y solución de problemas.

## Arquitectura

~~~text
Navegador (http://localhost:8090)
               |
       API FastAPI + React
       Contenedor Docker sin root
         |             |
    SQLite local    127.0.0.1:18765
                         |
                  Agente Fedora
                  systemd --user
                         |
              psutil / systemctl / docker CLI
~~~

Por defecto solo escucha en loopback. No expongas el puerto directamente a Internet. Para acceso externo utiliza túnel HTTPS y Cloudflare Access.

## Desarrollo y pruebas

~~~bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt -r agent/requirements.txt pytest
PYTHONPATH=backend:. pytest -q
cd frontend
npm install
npm run build
~~~

CI en GitHub Actions: pruebas del backend/agente, compilación frontend y build Docker.

## Roadmap

- [x] Base segura, interfaz responsive y puerto 8090
- [x] Monitor Fedora, Docker, red, servicios y alertas
- [x] Reinicios restringidos de contenedores
- [x] Historial SQLite, auditoría y respaldo cifrado manual
- [ ] Administración de actualizaciones DNF/Flatpak
- [ ] Automatizaciones y notificaciones programadas
- [ ] Restauración guiada y auditoría de seguridad avanzada
- [ ] Diagnóstico asistido por IA
- [ ] Administración de múltiples hosts Linux

**Licencia:** uso personal; añade una licencia antes de redistribuirlo.
