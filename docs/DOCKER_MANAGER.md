# Docker Manager 2.1 — HomeLab OS v0.3

La fase A incorpora un inventario de Docker y acciones supervisadas desde la interfaz web.

## Capacidades

- **Contenedores**: lista de todos los contenedores (activos o detenidos), imagen, estado, puertos, proyecto y servicio Compose.
- **Métricas**: CPU, RAM, porcentaje de memoria, tráfico de red, E/S de bloque y número de procesos desde docker stats (las métricas solo corresponden a contenedores que Docker puede medir).
- **Logs**: visor con 50–500 líneas, periodos de 5 min, 30 min, 1 h, 24 h o todo el historial; recarga cada 5 segundos mientras está abierto, con opción de pausa. Lectura bajo demanda; no se almacenan los logs en la base de datos.
- **Imágenes**: repositorio, etiqueta, ID, tamaño y antigüedad.
- **Redes**: nombres, drivers, ámbito e IDs.
- **Volúmenes**: nombres y drivers, sin exponer directorios del host.
- **Compose**: detección de proyectos a partir de etiquetas com.docker.compose.project y com.docker.compose.service, agrupados por proyecto.
- **Operaciones**: iniciar, detener o reiniciar **solo** contenedores explícitamente autorizados en el agente. Todas las acciones requieren sesión, token CSRF, confirmación visual y quedan auditadas.

No se ha implementado eliminación de contenedores, imágenes o volúmenes, Docker prune, Docker Compose down ni comandos arbitrarios. El agente no opera como root por defecto y el contenedor web nunca monta el socket Docker.

## Actualizar desde v0.1

En Fedora, desde el repositorio:

~~~bash
cd ~/Documents/Proyectos/HomelabOS
git pull --ff-only
bash scripts/install.sh
~~~

El instalador mantiene el archivo .env y los datos existentes. **Es necesario reiniciar el agente systemd** para que cargue los nuevos endpoints. El instalador realiza esa operación automáticamente.

Si solo actualizas el contenedor con Docker Compose, la pestaña Docker Manager no podrá acceder a los endpoints nuevos hasta que reinicies el agente:

~~~bash
systemctl --user restart homelabos-agent
~~~

## Activar operaciones por contenedor

Por defecto, **todos los contenedores son de solo lectura**.

En tu archivo local .env, configura los nombres concretos separados por comas, por ejemplo:

~~~dotenv
HOMELAB_ALLOWED_CONTAINERS=plex,homepage
~~~

**No se activa ningún contenedor automáticamente**, especialmente bases de datos y componentes críticos de Finance OS, Personal Planner o Cloud Engineer Lab.

Para aplicar la lista al agente:

~~~bash
python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user restart homelabos-agent
~~~

La API web usa un token compartido de alta entropía para comunicarse con el agente en 127.0.0.1:18765. El servidor web está limitado a 127.0.0.1:8091.

## Verificación

~~~bash
docker compose ps
systemctl --user status homelabos-agent --no-pager
curl -fsS http://localhost:8091/api/health
docker ps -a
~~~

Abre http://localhost:8091 → Docker. Deberías ver tus contenedores reales, sin datos de demostración. El inventario se actualiza aproximadamente cada 30 segundos y las estadísticas cada 20 segundos mientras la pestaña está abierta.

## Consideraciones

- **Permisos Docker**: el agente debe poder ejecutar docker ps como tu usuario Fedora. El acceso al socket Docker representa privilegios elevados del host; no agregues usuarios desconocidos al grupo docker.
- **Privacidad**: los logs de contenedores pueden contener tokens o datos sensibles. Accede al panel solo desde una sesión confiable, idealmente con Cloudflare Access si expones la interfaz.
- **Proyectos Compose**: el agrupamiento solo aparecerá si los contenedores tienen las etiquetas de Compose estándar. Los contenedores que creaste manualmente aparecen como independientes.
- **Gestión limitada**: las operaciones afectan contenedores individuales. No intentan sustituir las reglas de dependencia de Compose ni administran todos los servicios de un stack a la vez.
- **Política de reinicio**: si detienes un contenedor con una política de reinicio, Docker puede volver a iniciarlo según esa política. Revisa antes de usar la función.
- **Logs y métricas**: el agente limita tiempos de ejecución, número de líneas y tamaño de las respuestas; no ofrece una terminal ni ejecución interactiva.

## Controles por proyecto y protección crítica

La sección **Proyectos Compose** incorpora acciones para iniciar, detener o reiniciar todos los contenedores existentes de un proyecto, si todos están autorizados individualmente en HOMELAB_ALLOWED_CONTAINERS. Se consulta un plan nuevo antes de cada operación. Los proyectos siempre requieren escribir una confirmación exacta.

Los contenedores con nombres o imágenes que indican base de datos, túnel, proxy o panel de administración (por ejemplo PostgreSQL, cloudflared y homelabos) requieren confirmación escrita también para acciones individuales. La validación se repite en el agente; la API antigua no elude estas protecciones.

La operación usa docker start/stop/restart por contenedor, con orden conservador (base de datos antes de API/web al iniciar, orden inverso al detener). **No sustituye el control de dependencias de Docker Compose** ni elimina recursos. Una operación puede completar parcialmente; revisa los resultados y logs.
