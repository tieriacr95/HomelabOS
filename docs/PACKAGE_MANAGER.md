# Fedora Package Manager — HomeLab OS v0.3

Este módulo consulta las actualizaciones de **DNF5/DNF** y **Flatpak (usuario/sistema)** desde el agente Fedora, y permite actualizarlas de manera explícita y auditada.

## Funcionalidades

- Paquetes RPM instalados y actualizables (hasta 3 000 instalados y 1 000 pendientes por lectura).
- Historial DNF de las últimas transacciones que devuelve el CLI.
- Paquetes Flatpak instalados y pendientes en las instalaciones de usuario y sistema.
- Actualización manual: botón, ventana de advertencia y **frase de confirmación obligatoria**.
- Ejecución como trabajo supervisado por el agente, con estado, resultado y salida reciente.
- Registro de solicitudes de actualización en la auditoría de HomeLab OS.
- Caché de inventario de 5 minutos, con botón de consulta manual.

El historial de trabajos es volátil: desaparece si se reinicia el agente. DNF y Flatpak mantienen sus propios historiales en el sistema operativo. Las operaciones pueden requerir reiniciar aplicaciones o Fedora; HomeLab OS no reinicia el equipo.

## 1. Instalar versión 0.3

~~~bash
cd ~/Documents/Proyectos/HomelabOS
git pull --ff-only
bash scripts/install.sh
~~~

Abre **http://localhost:8091 → Actualizaciones**. Sin instalar privilegios adicionales puedes consultar las actualizaciones y ejecutar Flatpak de usuario (cuando el servicio systemd pueda escribir en la instalación del usuario).

## 2. Autorizar DNF y Flatpak del sistema (opcional)

El agente **no funciona como root**. Para actualizar el sistema operativo, HomeLab OS usa un pequeño ejecutable instalado como propiedad de root y una regla sudoers que autoriza **solo dos subcomandos exactos**:

- /usr/local/libexec/homelabos/package-helper dnf-upgrade
- /usr/local/libexec/homelabos/package-helper flatpak-system-upgrade

Revisa el código de **helpers/package-helper** y **scripts/install_package_helper.sh** antes de instalarlo. Requiere acceso sudo interactivo de tu cuenta durante la configuración inicial:

~~~bash
bash scripts/install_package_helper.sh
~~~

El instalador solicita tu contraseña sudo en la terminal. Copia el helper a una ruta propiedad de root y escribe /etc/sudoers.d/homelabos-packages. A continuación vuelve a generar y reiniciar el servicio systemd de usuario.

**Consideración de seguridad:** para permitir las actualizaciones privilegiadas, la unidad del agente ya no puede usar NoNewPrivileges ni un sistema de archivos enteramente de solo lectura. La delegación sigue restringida a los dos comandos anteriores, pero el aislamiento de systemd es menor que en modo solo lectura. Configura HomeLab OS exclusivamente en localhost, y usa HTTPS + Cloudflare Access si habilitas acceso externo.

En el panel no se permiten nombres de paquetes ni comandos arbitrarios. La actualización DNF ejecuta todas las actualizaciones disponibles de repositorios configurados; revisa previamente la lista.

## 3. Proteger las aplicaciones y los datos

Antes de grandes actualizaciones de Fedora:
1. Verifica que los respaldos de los proyectos Docker y PostgreSQL están al día.
2. Revisa la lista de paquetes pendientes y el historial.
3. Ejecuta la actualización de DNF o Flatpak que corresponda.
4. Comprueba el resultado desde **Trabajos de actualización**, y el estado de los servicios Docker.
5. Reinicia Fedora desde el sistema operativo solo si es necesario.

Las actualizaciones no poseen mecanismo automático de rollback.

## 4. Volver al modo solo lectura

~~~bash
sudo rm /etc/sudoers.d/homelabos-packages
sudo rm /usr/local/libexec/homelabos/package-helper
python3 scripts/install_agent.py
systemctl --user daemon-reload
systemctl --user restart homelabos-agent
~~~

Esto no desinstala DNF, Flatpak ni revierte actualizaciones previas. El agente recuperará las restricciones de systemd configuradas para el modo sin helper.

## 5. Diagnósticos

~~~bash
systemctl --user status homelabos-agent --no-pager
journalctl --user -u homelabos-agent -n 100 --no-pager
docker compose logs --tail=100 homelabos
sudo visudo -c
curl -fsS http://localhost:8091/api/health
~~~

Si la consulta DNF falla, verifica manualmente con:

~~~bash
dnf5 repoquery --upgrades
flatpak list
flatpak remote-ls --updates
~~~

Las consultas pueden tardar mientras Fedora actualiza metadatos. Los errores se muestran en el panel; no se inventan resultados. Todas las operaciones requieren que el agente local esté disponible.
