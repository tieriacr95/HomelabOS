# Instalación de HomeLab OS en Fedora

HomeLab OS corre en **http://localhost:8090**. Tiene dos componentes:

- **Web + API**: Docker Compose, red del host, FastAPI + React. Solo escucha 127.0.0.1:8090.
- **Agente nativo**: servicio systemd de usuario, escucha 127.0.0.1:18765. No requiere root.

El agente consulta datos reales de Fedora con psutil, systemctl y la CLI de Docker. La API no monta el socket de Docker ni ejecuta comandos arbitrarios.

## Requisitos

Fedora Workstation, Python 3 con venv, Docker Engine accesible a tu usuario, Docker Compose v2 y systemd --user. El Dockerfile requiere Internet para descargar dependencias durante la compilación.

### Primer despliegue

~~~bash
git clone https://github.com/tieriacr95/HomelabOS.git
cd HomelabOS
bash scripts/install.sh
~~~

Si el repositorio es privado, autentícate con GitHub antes de clonar. No ejecutes el script con sudo.

El instalador:
1. Crea .env con tokens aleatorios (permisos 600) si no existe.
2. Prepara data/ (permisos 700).
3. Instala psutil en un entorno virtual local.
4. Registra y arranca homelabos-agent como servicio de usuario.
5. Construye y arranca la aplicación mediante Docker Compose.

Abre **http://localhost:8090**. Para crear la primera cuenta introduce usuario, contraseña de 12 caracteres como mínimo y el token:

~~~bash
grep '^HOMELAB_SETUP_TOKEN=' .env
~~~

Para comprobar el servicio:

~~~bash
docker compose ps
docker compose logs -f homelabos
systemctl --user status homelabos-agent
journalctl --user -u homelabos-agent -n 80 --no-pager
curl -fsS http://127.0.0.1:8090/api/health
~~~

Si quieres que el agente se ejecute cuando cierres sesión de Fedora, activa el lingering de systemd para tu usuario mediante loginctl con privilegios administrativos; hazlo solo si lo necesitas.

## Habilitar monitores

Edita config/services.json:

~~~json
[
  {"name": "Plex", "url": "http://127.0.0.1:32400/identity", "enabled": true},
  {"name": "Mi servicio", "url": "http://127.0.0.1:3000/health", "enabled": true}
]
~~~

No des por supuesto que los puertos del ejemplo coinciden con los de tus aplicaciones. Los cambios en config/services.json se cargan en cada lectura del dashboard y no requieren reconstruir contenedores.

## Reinicios de contenedores

Predeterminado: **ningún contenedor puede reiniciarse desde el panel**. Para habilitar algunos, edita .env:

~~~dotenv
HOMELAB_ALLOWED_CONTAINERS=plex,homepage
~~~

Y sincroniza el agente con esta configuración:

~~~bash
python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user restart homelabos-agent
~~~

El usuario Fedora que ejecuta el agente debe tener acceso normal a la CLI de Docker. No uses chmod 666 sobre /var/run/docker.sock; pertenecer al grupo docker implica permisos muy amplios sobre el host, por lo que debes proteger la sesión y las credenciales.

## Actualizar

~~~bash
git pull --ff-only
bash scripts/install.sh
~~~

El instalador no sustituye .env ni borra la base de datos.

## Acceso remoto

El despliegue está diseñado para **localhost** por defecto. No publiques directamente el puerto sin autenticación adicional. Si usas Cloudflare Tunnel, protege la ruta con Cloudflare Access y HTTPS.

**Importante:** como la web escucha 127.0.0.1, un contenedor cloudflared en modo bridge no puede alcanzar esa dirección del host. Para el túnel usa un cloudflared nativo en el host o una configuración segura equivalente (p. ej. host networking). No conviertas el enlace web en 0.0.0.0 solo para facilitar el túnel.

Con acceso por HTTPS establece HOMELAB_COOKIE_SECURE=true en .env y reinicia la web. Las sesiones creadas previamente desde HTTP ya no servirán desde localhost mientras Secure esté habilitado; úsalo para el hostname HTTPS.

## Backups cifrados

HomeLab OS proporciona scripts/backup.sh basado en restic. Requiere instalar restic y establecer HOMELAB_RESTIC_REPOSITORY y HOMELAB_RESTIC_PASSWORD_FILE (la contraseña se almacena fuera del repositorio).

~~~bash
restic -r /ruta/a/backup-repo --password-file /ruta/segura/restic-password init
export HOMELAB_RESTIC_REPOSITORY=/ruta/a/backup-repo
export HOMELAB_RESTIC_PASSWORD_FILE=/ruta/segura/restic-password
bash scripts/backup.sh
~~~

El script realiza una copia coherente de SQLite antes de enviarla cifrada a restic. Prueba una restauración sobre un entorno aislado antes de confiar en los respaldos.

## Resolución de problemas

- **Agente desconectado**: comprueba systemctl --user y que HOMELAB_AGENT_TOKEN coincida entre .env y ~/.config/homelabos/agent.env.
- **Docker no disponible**: prueba docker ps con el mismo usuario que ejecuta el agente.
- **Puerto ocupado**: revisa ss -ltnp | grep :8090; detén el proceso que ocupa ese puerto antes de iniciar HomeLab OS.
- **Problemas con SELinux**: conserva las opciones :Z en compose.yaml, comprueba permisos del directorio data y revisa audit.log antes de cambiar políticas. No desactives SELinux para solucionar problemas de montaje.
- **La interfaz muestra datos vacíos**: no se simulan métricas; el agente debe estar activo y correctamente autenticado.

## Alcance de esta versión

Implementado: autenticación inicial y login, panel responsive, métricas Fedora, temperaturas disponibles, disco, procesos, servicios systemd, listado Docker, reinicios opt-in, comprobaciones HTTP, alertas por umbral, historial SQLite y auditoría básica, backup cifrado manual y pruebas CI.

Pendiente para futuras versiones: actualizaciones DNF/Flatpak con autorización, tareas automáticas, análisis avanzado de seguridad, restauración asistida, asistente IA y administración multi-host.
