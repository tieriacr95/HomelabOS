# HomeLab OS

**Centro local de administración Fedora + Docker + servicios HomeLab.**

Aplicación web oscura y responsive, accesible en **http://localhost:8091**. Tu computadora Fedora aporta métricas reales mediante un agente systemd de usuario. El contenedor web no necesita root ni acceso directo al socket Docker.

## Funciones incluidas

- **Vista general**: CPU, RAM, disco, contenedores, alertas e historial de uso.
- **Fedora**: procesos por RAM, sensores disponibles, uptime, tráfico de red, particiones y estado de servicios systemd.
- **Docker Manager 2.1**: inventario, métricas, logs y acciones por contenedor o por proyecto Compose; confirmación escrita para proyectos y servicios críticos.
- **Fedora Package Manager**: consulta DNF/RPM y Flatpak (usuario/sistema), historial y actualización manual mediante helper privilegiado opcional y confirmación escrita.
- **Infraestructura**: salud PostgreSQL mediante pg_isready, historial CPU/RAM por contenedor, servicios systemd y caducidad de certificados TLS.
- **Servicios**: comprobaciones HTTP de endpoints que tú configures y alertas de disponibilidad.
- **Security Center v0.4**: SELinux, firewalld, configuración efectiva SSH, sockets TCP/UDP, eventos de autenticación agregados, parámetros del kernel, hallazgos e historial; sin cambios automáticos. Sesiones HttpOnly, CSRF y auditoría.
- **Histórico**: SQLite persistente, muestras de rendimiento y registro de acciones.
- **Alertas y automatizaciones v0.6**: incidentes persistentes, reglas y umbrales, supervisión de Fedora/Docker/PostgreSQL/HTTP/TLS/restic, Telegram opt-in, silenciamiento, recuperación y timer systemd cada dos minutos.
- **Backup & Recovery v0.5**: SQLite consistente, dumps de PostgreSQL, volúmenes y directorios Docker seleccionados, restic cifrado, programación diaria, retención, verificación profunda y restauración en staging seguro. Sin backups automáticos antes de DNF.

## Instalación en Fedora

~~~bash
git clone https://github.com/tieriacr95/HomelabOS.git
cd HomelabOS
bash scripts/install.sh
~~~

Abre **http://localhost:8091** y crea tu cuenta. El instalador genera un token aleatorio:

~~~bash
grep '^HOMELAB_SETUP_TOKEN=' .env
~~~

**Requisitos:** Fedora Linux, Python 3 + venv, Docker Engine, Docker Compose v2, systemd --user y acceso de tu usuario a Docker. El instalador se ejecuta **sin sudo** y no sobrescribe los tokens existentes.

Consulta **[Guía completa de instalación](docs/INSTALL.md)**, **[Docker Manager](docs/DOCKER_MANAGER.md)** y **[Package Manager](docs/PACKAGE_MANAGER.md)** y **[Security Center](docs/SECURITY_CENTER.md)** y **[Infraestructura](docs/INFRASTRUCTURE.md)** y **[Backup & Recovery](docs/BACKUP_RECOVERY.md)** para permisos y operación segura.

## Activar respaldos (opcional)

~~~bash
sudo dnf install restic
python3 scripts/setup_backups.py --include-discovered-postgres
python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user restart homelabos-agent
# Después de configurar los recursos, habilita el timer cuando lo desees:
python3 scripts/backup_schedule.py --enable 03:00
~~~

El repositorio restic inicial es local y **debes conservar una copia cifrada externa y la contraseña fuera de Fedora**. No se activan backups al instalar. Consulta [Backup & Recovery](docs/BACKUP_RECOVERY.md) y la [guía de recuperación](docs/RECOVERY.md).

## Activar alertas (opcional)

~~~bash
python3 scripts/alerts_setup.py --telegram
python3 scripts/alerts_setup.py --enable
~~~

Luego en **Alertas → Reglas** habilita el motor y las notificaciones, y guarda los cambios. Consulta [Alertas y automatizaciones](docs/ALERTS_AUTOMATIONS.md). Las acciones administrativas **no se ejecutan automáticamente**.

## Arquitectura

~~~text
Navegador (http://localhost:8091)
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

- [x] Base segura, interfaz responsive y puerto 8091
- [x] Monitor Fedora, Docker, red, servicios y alertas
- [x] **Fase A — Docker Manager 2.1**: contenedores, Compose, imágenes, volúmenes, redes, métricas, logs y acciones seguras; control por proyecto y protección de servicios críticos
- [x] Historial SQLite, auditoría y respaldo cifrado manual
- [x] **Fase B — Fedora Package Manager**: DNF, Flatpak, paquetes instalados, pendientes, historial y ejecución bajo aprobación
- [x] **Fase C — Security Center**: auditoría de solo lectura, recomendaciones, cobertura e historial
- [x] **Extras 0.4.2**: SSH privilegiado mínimo opt-in, Postgres readiness, systemd, métricas históricas y TLS
- [x] **Fase E — Alertas y automatizaciones v0.6**: reglas, Telegram, incidentes, deduplicación, silenciamiento y monitoreo programado
- [x] **Fase D — Backup & Recovery v0.5**: respaldos cifrados, inventario explícito, retención, programación, comprobación de integridad y restauración guiada sin sobrescritura de producción
- [ ] Auditoría de seguridad avanzada
- [ ] Diagnóstico asistido por IA
- [ ] Administración de múltiples hosts Linux

**Licencia:** uso personal; añade una licencia antes de redistribuirlo.
