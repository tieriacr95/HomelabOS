# HomeLab OS v0.5 — Backup & Recovery

## Alcance

Los backups son cifrados con restic. La fase D incluye inventario de recursos, PostgreSQL (pg_dumpall lógico), SQLite consistente, exportación de volúmenes Docker seleccionados, directorios de usuario, programación opcional con timer systemd, retención, verificación y recuperación aislada.

**Al actualizar HomeLab OS no se ejecuta ni programa ningún backup automáticamente.** Debes configurar el repositorio y seleccionar las fuentes localmente, y después completar un trabajo. No se hacen backups previos a las actualizaciones DNF.

## Instalar

~~~bash
cd ~/Documents/Proyectos/HomelabOS
git pull --ff-only
bash scripts/install.sh
sudo dnf install restic
python3 scripts/setup_backups.py --include-discovered-postgres
~~~

El repositorio local por defecto estará en ~/Backups/HomeLabOS. Es útil ante errores humanos, pero si el disco falla perderías tanto el origen como esa copia: almacena otra copia cifrada fuera del host. La contraseña se guarda exclusivamente en ~/.config/homelabos/restic-password (0600); resguárdala también fuera del equipo, pues sin ella no podrás recuperar los datos.

Tras crear el repositorio, actualiza el sandbox de systemd para que permita escribir en el repositorio local y en su staging:

~~~bash
python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user restart homelabos-agent
~~~

Abre http://localhost:8091 → Respaldos. El usuario de HomeLab OS ve el estado y la lista de recursos, pero nunca la contraseña.

## Elegir fuentes de respaldo

Edita ~/.config/homelabos/backup.json, archivo privado 0600. Por ejemplo, adapta los nombres a los que tengas realmente en docker ps -a y docker volume ls:

~~~json
{
  "sources": [
    {"type": "homelab", "name": "homelab"},
    {"type": "postgres", "name": "finance-os-db-1"},
    {"type": "postgres", "name": "personal-planner-planner-db-1"},
    {"type": "postgres", "name": "cloud-engineer-lab-db-1"},
    {"type": "volume", "name": "VOLUMEN_A_ELEGIR"},
    {"type": "directory", "name": "planner-files", "path": "/home/tieria/Documents/Proyectos/personal-planner-ai"}
  ],
  "retention": {"daily": 7, "weekly": 4, "monthly": 6}
}
~~~

Quita las fuentes de ejemplo que no existan. Nunca se agregan volúmenes automáticamente. Si deseas añadirlos durante la creación inicial, usa --include-volume NOMBRE (repetible) y descarga antes docker pull busybox:1.36. La herramienta requiere una imagen BusyBox local para exportar un volumen con montaje de solo lectura y sin red. Deja el volumen PostgreSQL fuera de ese listado: usa exclusivamente dumps lógicos de bases activas.

El tipo homelab copia data/homelabos.db con SQLite Backup API y los archivos no secretos services.json y tls_endpoints.json, sin copiar .env ni tokens. El tipo postgres ejecuta pg_dumpall -U postgres --no-role-passwords desde el contenedor, sin recuperar credenciales ni contraseñas. El tipo directory copia un directorio que está bajo el home de Fedora: útil para bind mounts de las aplicaciones. No garantiza una transacción atómica entre varias apps y directorios.

## Backup y verificación

Desde Respaldos pulsa Crear respaldo, escribe EJECUTAR RESPALDO y confirma. Tras un backup exitoso se aplica una retención por etiqueta homelabos de 7 diarios, 4 semanales y 6 mensuales, editable en backup.json. Si una fuente falla no se declara el backup exitoso. Los trabajos se guardan en disco y el panel informa los fallos.

Para verificar ejecuta Verificar integridad y escribe VERIFICAR RESPALDOS. Se llama restic check --read-data, que lee y verifica los bloques del repositorio (puede tardar). Adicionalmente realiza simulacros de restauración con regularidad: restic check por sí solo no asegura que tus apps puedan arrancar.

**Privacidad:** los dumps PostgreSQL y TAR existen temporalmente sin cifrar en un staging privado 0700 antes de subir al repositorio cifrado. Se eliminan al acabar; son datos sensibles si otros procesos no confiables tienen acceso a tu sesión Fedora.

## Programación automática opcional

~~~bash
python3 scripts/backup_schedule.py --enable 03:00
systemctl --user list-timers homelabos-backup.timer
~~~

Puedes elegir otra hora local en formato HH:MM, con un retraso aleatorio de hasta 10 minutos. Persistent=false evita ejecutar copias atrasadas de manera inesperada al activar. Si necesitas ejecutarlo sin sesión abierta, configura el servicio de usuario con linger según tu política local.

~~~bash
python3 scripts/backup_schedule.py --disable
~~~

Desactivarlo no borra el repositorio. Los trabajos del navegador y el timer comparten un bloqueo de archivos para evitar concurrencia de operaciones.

## Recuperación segura

Desde la pestaña Snapshots elige una copia, pulsa Preparar recuperación y escribe RESTAURAR seguido por su ID exacto. Restic desencripta los archivos a una carpeta privada nueva bajo ~/.local/state/homelabos/backup/restores/. No se sobrescribe jamás la instancia de producción; la ruta final aparece en el historial de trabajos. El programa verifica la base SQLite con PRAGMA integrity_check y comprueba estructura y rutas seguras de TAR.

Para recuperar una aplicación real, detén primero los servicios afectados y sigue [Guía de recuperación](RECOVERY.md). La reimportación a PostgreSQL o reemplazo de un volumen permanece como cambio manual expresamente deliberado; no existe un botón que sobrescriba producción.

## Límites y seguridad

- Repositorio local en el mismo disco: insuficiente para recuperación de desastre. Mantén una réplica cifrada fuera del host y copia segura de la contraseña.
- La exportación pg_dumpall requiere PostgreSQL accesible mediante socket local y el usuario postgres. No almacena ni lee contraseñas de apps.
- El staging temporal no está cifrado en disco; utiliza tu dispositivo de confianza, con permisos privados y suficiente espacio.
- Los backups de volumen son consistentes a nivel de archivos solo si la aplicación detiene escrituras o tiene su propio mecanismo de snapshot. No utilices un TAR crudo de PGDATA con PostgreSQL en ejecución.
- El listado de trabajos muestra fallos; también puedes consultar journalctl --user -u homelabos-backup.service.
- La verificación profunda no equivale a una prueba de importación de datos. Realiza pruebas de recuperación en ambientes aislados.
- No se conceden operaciones root, borrado de volúmenes ni ejecución de comandos arbitrarios desde el navegador.
