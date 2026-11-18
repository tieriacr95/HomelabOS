# HomeLab OS v0.6 — Alertas y automatizaciones (Fase E)

## Qué incorpora

Monitoreo periódico del host Fedora y tus servicios Docker mediante un timer systemd de usuario: CPU, RAM, disco, sensores de temperatura, contenedores esperados, PostgreSQL (pg_isready), endpoints HTTP configurados, caducidad y confianza de certificados TLS y estado/frescura de backups.

La evaluación consolida incidentes en una base SQLite privada, confirma fallos consecutivos, registra recuperaciones automáticas, limita avisos repetidos y permite reconocer, silenciar o reactivar incidencias. Telegram utiliza credenciales privadas en Fedora: nunca las recibe el navegador, nunca aparecen en el historial y no se guardan en el repositorio GitHub.

## Seguridad y activación

**La fase E no se activa automáticamente al instalar HomeLab OS.** Para enviar notificaciones necesitas tres pasos independientes:

1. Configurar el bot y chat de Telegram en tu Fedora.
2. Habilitar el programador systemd.
3. Habilitar el motor de monitoreo y las notificaciones desde las Reglas de la interfaz.

En ningún momento se reinician contenedores, ejecutan scripts arbitrarios, cambian paquetes o modifican servicios por una alerta. Las acciones destructivas y privilegiadas de las fases anteriores siguen requiriendo autorización individual.

### Instala la versión

~~~bash
cd ~/Documents/Proyectos/HomelabOS
git pull --ff-only
bash scripts/install.sh
~~~

La pantalla está en http://localhost:8091 → **Alertas**.

### Configurar Telegram

Crea un bot con BotFather en Telegram, inicia una conversación con él y obtén el ID del chat donde quieras recibir avisos.

~~~bash
python3 scripts/alerts_setup.py --telegram
~~~

El script solicita el token con getpass (sin eco) y el chat ID. Guarda un JSON privado 0600 en ~/.config/homelabos/telegram.json, con permisos 0700 para el directorio. **No publiques el token en el chat, terminal compartida o GitHub.** Usa la pestaña Telegram y agenda → **Enviar mensaje de prueba** para comprobar el destino. Para reemplazar las credenciales ejecuta el mismo script con --telegram --replace.

### Habilitar el timer

~~~bash
python3 scripts/alerts_setup.py --enable
systemctl --user list-timers homelabos-alerts.timer
~~~

El timer evalúa aproximadamente cada dos minutos (hasta quince segundos aleatorios adicionales). Si Fedora tiene la sesión de usuario cerrada, el timer de usuario puede dejar de ejecutarse; puedes habilitar linger si tu política local lo permite.

A continuación entra a Alertas → Reglas, activa Motor de monitoreo y opcionalmente Notificaciones Telegram, luego pulsa Guardar cambios. El estado inicial es **desactivado** para evitar avisos no solicitados.

Para detener las evaluaciones sin borrar incidentes:

~~~bash
python3 scripts/alerts_setup.py --disable
~~~

También puedes desactivar el motor desde Reglas. Desactivar Telegram no elimina el historial local.

## Reglas disponibles

| Fuente | Comportamiento | Valor por defecto |
|---|---|---|
| CPU | Porcentaje sobre umbral | 90% |
| RAM | Porcentaje usado | 90% |
| Disco | Ocupación de / | 85% |
| Temperatura | Máxima temperatura reconocida | 85 °C |
| Contenedores | Contenedores seleccionados que no figuran como running | Selección vacía |
| PostgreSQL | Contenedores de base que no aceptan conexiones | pg_isready |
| HTTP | Endpoints de config/services.json sin respuesta o con HTTP 5xx | Cada endpoint habilitado |
| TLS | Certificado vencido, próximo a vencer o no confiable | 15 días |
| Backups | Error nuevo o copia más antigua que el umbral | 36 horas; solo si restic está configurado |

La configuración de reglas queda en ~/.config/homelabos/alerts.json con permisos 0600. Solo se admiten nombres de contenedores, tipos y rangos numéricos validados: la API no acepta URLs arbitrarias, comandos, scripts ni nombres de unidades systemd para ejecución automática.

Los contenedores Docker se monitorizan únicamente cuando los agregas explícitamente al campo Contenedores esperados. Este diseño evita alarmas por contenedores que normalmente permanecen detenidos. **Si Docker está inaccesible, el resultado es desconocido y no se interpreta como una caída masiva de contenedores.**

## Ciclo de vida y mensajes

- El monitor necesita dos comprobaciones fallidas consecutivas para abrir un incidente, por defecto.
- Una fuente que vuelve a estar saludable cierra el incidente.
- Los estados desconocidos no abren ni cierran incidentes.
- Telegram envía un mensaje inicial y, si sigue abierto y no está reconocido, un recordatorio tras el tiempo de enfriamiento (60 minutos por defecto).
- Recuperaciones informan mediante un único mensaje si el incidente había sido notificado.
- Puedes reconocer un incidente para detener recordatorios, silenciarlo por 15 min, 1 hora, 4 o 24 horas, o activar el silencio global temporal.
- El historial de eventos y evaluaciones se conserva aproximadamente 90 días; las mediciones de salud recientes, 30 días.

Un aviso silenciado temporalmente conserva el estado del incidente. Las reglas no tienen un botón de reparación automática.

## Alertas sobre backups

Se usa el historial local de operaciones de la fase D. Si los backups no están configurados, esta comprobación no genera incidentes. Si están configurados y nunca terminaste una copia, se genera un incidente tras los fallos consecutivos indicados. La frescura de la última copia correcta y los errores posteriores se supervisan por separado.

Estas alarmas detectan fallos operativos y antigüedad; **no sustituyen la validación de recuperación**. Continúa haciendo simulacros de restauración y guardando una réplica cifrada fuera del equipo.

## Mantenimiento semanal autorizado (opt-in)

Además del sondeo de alertas, puedes configurar una **verificación semanal de integridad restic** sin ejecutar cambios sobre contenedores ni bases de producción. La configuración requiere que el repositorio cifrado de la Fase D ya exista.

~~~bash
python3 scripts/maintenance_schedule.py --enable
systemctl --user list-timers homelabos-maintenance.timer
~~~

El timer verifica el repositorio cada domingo a las 04:00 (hora local), con un retraso aleatorio de hasta 15 minutos. Internamente registra el mismo trabajo de verificación profunda que ofrece el panel Respaldos. Si falla, HomeLab OS registra el resultado y la regla de respaldos genera una incidencia después de las comprobaciones consecutivas configuradas.

~~~bash
python3 scripts/maintenance_schedule.py --disable
~~~

Esta programación está desactivada por defecto y **no** actualiza DNF, elimina snapshots, reinicia contenedores ni modifica archivos de producción. Desactivar el timer preserva el historial.

## Diagnósticos y limitaciones

~~~bash
systemctl --user status homelabos-alerts.timer
systemctl --user list-timers homelabos-alerts.timer
journalctl --user -u homelabos-alerts.service -n 80 --no-pager
systemctl --user status homelabos-agent
curl -fsS http://localhost:8091/api/health
~~~

Los registros del monitor y SQLite permanecen bajo ~/.local/state/homelabos/alerts. Los mensajes de Telegram tienen límite de longitud y no contienen contraseñas ni tokens.

No es un sistema de métricas industriales ni un SIEM. El check HTTP utiliza la lista explícita de servicios del host y puede encontrar endpoints que respondan 4xx, considerados servicio operativo para este monitor. Para certificar disponibilidad desde Internet necesitas observadores externos: el agente prueba desde tu Fedora.

Las notificaciones por Telegram requieren conectividad de salida a api.telegram.org. Los errores de entrega se registran sin mostrar detalles de URL que pudieran contener el token.

**Fase E no incorpora backups previos a actualizaciones DNF ni remediación automática.**
