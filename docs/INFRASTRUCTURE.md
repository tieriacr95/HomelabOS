# Infraestructura v0.4.2 — Mejoras previas a Backup & Recovery

## 1. Diagnóstico SSH con privilegios restringidos (opcional)

El agente sigue operando como usuario Fedora sin ser root. Si sshd -T falla por claves privadas o configuración protegida, instala manualmente el helper de lectura SSH:

~~~bash
cd ~/Documents/Proyectos/HomelabOS
bash scripts/install_ssh_audit.sh
~~~

Esto instala un ejecutable propiedad de root y la regla sudoers **sin argumentos permitidos**. Solo ejecuta sshd -T para una conexión de prueba y filtra su salida a un conjunto fijo de parámetros, sin mostrar claves o archivos secretos.

**Revísalo antes de instalar:** helpers/ssh-audit-helper y scripts/install_ssh_audit.sh. Al habilitar sudo desde un servicio systemd se desactiva NoNewPrivileges, pero se conserva ProtectSystem=strict y ProtectHome=read-only cuando no se ha instalado el helper de actualizaciones DNF.

Para deshabilitarlo:

~~~bash
sudo rm /etc/sudoers.d/homelabos-ssh-audit /usr/local/libexec/homelabos/ssh-audit-helper
python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user restart homelabos-agent
~~~

## 2. Estado PostgreSQL

**Infraestructura → PostgreSQL** descubre contenedores con imágenes PostgreSQL, PostGIS y TimescaleDB. Ejecuta exclusivamente:

~~~bash
docker exec NOMBRE pg_isready -h 127.0.0.1 -p 5432 -q
~~~

No lee credenciales, entorno de contenedores, contenido SQL ni datos. Los contenedores detenidos se muestran como tales. La disponibilidad TCP no demuestra integridad de datos ni funcionamiento completo de la aplicación. Los servicios con imágenes personalizadas no identificadas se deben revisar manualmente.

## 3. Métricas históricas

**Infraestructura → Métricas históricas** muestra CPU y RAM por contenedor. La API consulta Docker stats sin transmisión y conserva muestras SQLite cada 60 segundos hasta 30 días. Retiene 1 000 muestras máximo por consulta. La colección funciona aunque no haya navegadores abiertos, pero requiere que el contenedor HomeLab OS y el agente estén activos.

## 4. Gestión systemd restringida

**Infraestructura → Servicios systemd** lista unidades systemd de usuario y del sistema. Los servicios del sistema son **siempre de solo lectura**. Solo los servicios de usuario explícitamente listados en .env pueden administrarse.

~~~dotenv
HOMELAB_ALLOWED_SYSTEMD_UNITS=mi-servicio.service,otro-servicio.service
~~~

Aplica cambios:

~~~bash
python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user restart homelabos-agent
~~~

Para cada inicio, parada o reinicio exige confirmación escrita y registra auditoría. No permite crear, habilitar, enmascarar ni eliminar unidades y no ejecuta comandos de shell.

No incluyas homelabos-agent.service salvo que quieras poder desconectar voluntariamente el panel.

## 5. Certificados TLS

**Infraestructura → Certificados TLS** consulta automáticamente los servicios con URLs HTTPS en config/services.json. Para añadir dominios administrados fuera del mismo host, edita config/tls_endpoints.json:

~~~json
[
  {"name": "Planner público", "host": "planner.example.com", "port": 443},
  {"name": "Finance público", "host": "finance.example.com", "port": 443}
]
~~~

Comprueba expiración, emisor y confianza de la cadena. Marca certificados que vencen en 30 días y críticos en 7 días. No almacena certificados, claves privadas ni permite modificar DNS o renovar TLS. El monitoreo requiere que el contenedor HomeLab OS pueda realizar conexiones salientes al destino. Usa dominios administrados por ti.

## Seguridad

- No se habilitan acciones de systemd automáticamente.
- No se instala ningún helper root sin ejecutar manualmente el instalador.
- El acceso Docker otorga amplios privilegios al usuario que lo posee; evita exponer el agente o la aplicación sin Cloudflare Access.
- Los cambios systemd quedan auditados y requieren confirmación escrita.
- La capa de certificados solo consulta sitios configurados en archivos de administrador, no URLs enviadas por el navegador.
