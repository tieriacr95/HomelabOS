# HomeLab OS v0.6.1 → v0.6.5 — Consolidación y observabilidad

Esta entrega acumula las cinco mejoras solicitadas. Se mantiene Fedora como host,
FastAPI + React como interfaz y un agente systemd de usuario vinculado a loopback.
Todas las rutas nuevas están autenticadas. Las operaciones que cambian Docker
requieren CSRF, allowlist y confirmación escrita.

## v0.6.1 — Consolidación de alertas, permisos y diagnóstico Telegram

- Aclara la respuesta Telegram 403 cuando el chat ID corresponde **a otro bot**
  (telegram_target_is_bot). No comparte token, URL ni respuesta cruda del proveedor.
- El reconocimiento de un incidente deja de afectar reapariciones posteriores:
  al recuperarse y fallar otra vez, vuelve a requerir atención.
- El estado del monitor muestra diagnostics: motor/timer activos, Telegram
  configurado, edad del último sondeo, lecturas desconocidas y si el sondeo
  está atrasado. Ninguna credencial se expone en esta respuesta.
- Incluye pruebas de backups cifrados/restauración aislada, permisos,
  sesiones y CSRF.

En Telegram, «Forbidden: the bot can't send messages to the bot» significa que
se ingresó el ID de una cuenta bot, no el chat personal o de un grupo válido.

~~~bash
python3 scripts/alerts_setup.py --telegram --replace
~~~

## v0.6.2 — Salud global y topología

La sección **Salud global** consulta en paralelo Fedora (CPU/RAM/discos),
Docker, PostgreSQL (pg_isready), incidentes y estado de backups.

El estado global distingue healthy, degraded, critical y unknown. La ausencia
del agente no se muestra como éxito ficticio. Los contenedores detenidos no
son incidentes por sí mismos: podrían estar detenidos deliberadamente.

Los enlaces entre proyectos Compose y contenedores se derivan de las etiquetas
verificadas. Las dependencias entre bases de datos y API/web/worker se etiquetan
como estimaciones heurísticas: nunca se utilizan para ejecutar órdenes.

API: GET /api/observability/overview.

## v0.6.3 — Actualizaciones controladas de imágenes Docker

La sección **Imágenes Docker** ofrece inventario autorizado, vista previa de la
imagen y el ID en ejecución, confirmación escrita por nombre, descarga de la
imagen (docker pull) y comprobación del ID después de la descarga.

**Solo descarga una imagen. No reinicia, recrea, detiene ni cambia
automáticamente contenedores.** El despliegue de la imagen nueva es una
operación separada y manual mediante el archivo Compose original. Esto evita
interrupciones inesperadas de PostgreSQL, Plex, túneles y otros servicios.

El sistema exige HOMELAB_ALLOWED_CONTAINERS y verifica de nuevo el
identificador de la imagen antes de descargar. No hay ejecución de comandos
arbitrarios ni limpieza de imágenes o volúmenes.

La disponibilidad de actualizaciones no se confirma antes del pull:
el resultado changed se obtiene después de comparar IDs locales.

## v0.6.4 — Históricos de 30 días y tendencias

- Host: CPU, RAM, disco y contenedores recopilados hasta cada cinco minutos
  en segundo plano, sin que debas abrir el navegador.
- Docker: muestras cada minuto, incluso cuando no ves la pantalla Docker.
- Períodos de 1h, 6h, 24h, 7d y 30d. Agregación SQL en franjas y retención
  hasta 30 días, evitando truncar las primeras 1000 muestras de días largos.
- Proyección indicativa y lineal de 24h a partir de promedios, disponible solo
  con al menos 12 horas y 12 franjas históricas.

No es un modelo predictivo ni inicia cambios automáticos.

API: GET /api/observability/trends/host?hours=720.

## v0.6.5 — PWA para iPhone

- Manifiesto web, modo standalone e iconos PNG 192×192 y 512×512.
- Service worker activado por HTTPS o localhost.
- Caché limitada a los archivos estáticos y públicos del frontend: jamás
  HTML, respuestas API, tokens, cookies ni datos del usuario.
- Metadatos y guía de Safari para Añadir a pantalla de inicio.

Para instalar desde iPhone, abre HomeLab OS con HTTPS y acceso protegido
(Cloudflare Tunnel y Cloudflare Access, por ejemplo). En Safari pulsa
Compartir → Añadir a pantalla de inicio. Vuelve a iniciar sesión.
No expongas el puerto 8091 directamente a Internet.

No existe modo offline de operaciones administrativas ni almacenamiento
offline de credenciales, sesiones ni respuestas del servidor.

## Actualizar Fedora

~~~bash
cd ~/Documents/Proyectos/HomelabOS
git pull --ff-only
bash scripts/install.sh
systemctl --user status homelabos-agent
docker compose ps
curl -fsS http://127.0.0.1:8091/api/health
~~~

No se activan automáticamente los nuevos permisos Docker, Telegram, timers
ni acciones root. La configuración local y las bases persistentes se preservan.

### Limitaciones

- La topología inferida no reemplaza la definición de depends_on del Compose.
- La descarga Docker no cambia el contenedor activo, ni comprueba el registro
  remoto hasta ejecutar una descarga autorizada.
- Los históricos de 30 días se acumulan gradualmente, sin datos retroactivos.
- Las proyecciones lineales son aproximaciones, no garantías.
- La instalación PWA requiere acceso HTTPS seguro desde el iPhone.
