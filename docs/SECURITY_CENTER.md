# Fase C — Fedora Security Center (HomeLab OS v0.4)

**Modo lectura.** Security Center analiza información local accesible al agente Fedora: no abre puertos, no cambia políticas, no instala paquetes y no accede a claves SSH ni contraseñas.

## Qué analiza

| Control | Comprobación | Limitación |
|---|---|---|
| SELinux | Modo actual (getenforce) y modo persistente (/etc/selinux/config) | No inspecciona todas las reglas de política ni AVC sin acceso especial |
| firewalld | Estado, zonas activas, interfaces, orígenes, servicios y puertos explícitos | Las reglas nftables, de Docker y del router pueden ser distintas |
| SSH | Configuración efectiva para una conexión de muestra: PermitRootLogin, PasswordAuthentication, PubkeyAuthentication, PermitEmptyPasswords, MaxAuthTries y puerto | Match puede variar según usuario/IP y sshd -T puede fallar sin permisos |
| Puertos | Sockets TCP LISTEN y UDP bind, dirección, puerto, ámbito y proceso conocido | Estar enlazado a 0.0.0.0 no significa que Internet pueda acceder |
| Autenticación | Recuento aproximado de fallos SSH, accesos SSH aceptados y fallos sudo en últimas 24 horas | Solo registros accesibles para el usuario agente; no es un SIEM |
| Kernel | ASLR, symlink/hardlink protection, kptr_restrict, dmesg_restrict | No representa una auditoría de hardening completa |
| Helper de paquetes | Si el helper privilegiado opcional de fase B está instalado | Indicación de configuración, no verificación exhaustiva de sudoers |

## Hallazgos

El sistema genera hallazgos orientativos y ordenados por severidad: crítica, alta, media e informativa. Identifica SELinux en permisivo/deshabilitado, configuraciones SSH de riesgo, escuchas en puertos sensibles fuera de loopback, eventos de autenticación repetidos y ASLR desactivado.

**Sin falsos positivos por ausencia de acceso:** si journalctl, sshd -T o la enumeración de sockets no es accesible, la prueba figura como **no disponible**, nunca como cero incidentes. El indicador de cobertura cuenta cuántas de las cinco familias principales han podido verificarse.

## Instalación y actualización

~~~bash
cd ~/Documents/Proyectos/HomelabOS
git pull --ff-only
bash scripts/install.sh
~~~

Es necesario reiniciar homelabos-agent, pues el recolector se ejecuta nativamente en Fedora. El instalador lo hace automáticamente.

Abre http://localhost:8091 → **Seguridad**. El botón **Analizar ahora** realiza una lectura sin alterar el host.

## Historial y retención

La API almacena **solo conteos agregados y estados resumidos** en la base SQLite existente (tabla security_scans):

- Fecha y cantidad de hallazgos por severidad
- Número de sockets fuera de loopback
- Cantidad de comprobaciones accesibles
- Fallos SSH agregados, si el journal es accesible
- Estado de SELinux y firewalld

Las observaciones se guardan como máximo una vez cada 10 minutos, se retienen 30 días y **no** contienen mensajes de journal, usuarios, IPs, nombres de procesos, claves ni configuraciones SSH completas. El reporte completo se muestra en vivo y se puede copiar desde la interfaz.

El agente cachea un reporte por 120 segundos para evitar ejecutar comandos repetidamente. Un análisis manual fuerza un nuevo resultado.

## Auditoría manual y comprobaciones adicionales

En la terminal Fedora puedes comparar lecturas:

~~~bash
getenforce
sudo firewall-cmd --state
sudo firewall-cmd --get-active-zones
sudo ss -ltnup
sudo sshd -T -C user=root,host=localhost,addr=127.0.0.1
sudo journalctl -u sshd --since "-24 hours" --no-pager
~~~

Las órdenes con sudo son **solo para el usuario en su terminal**, no para el agente. Si no puedes leer el journal, Security Center mostrará que falta cobertura; no debes elevar permisos innecesariamente.

## Recomendaciones de protección

- Mantén SELinux Enforcing cuando tus servicios sean compatibles.
- Verifica que firewalld, nftables y tus reglas de red reflejan la exposición deseada.
- Usa claves SSH y evita PermitRootLogin yes; no bloquees tu único método de acceso al editar sshd.
- Para bases de datos Docker, prefiere redes internas o puertos vinculados a loopback cuando sea suficiente.
- Si utilizas Cloudflare Tunnel para HomeLab OS, exige Cloudflare Access y HTTPS; nunca expongas el agente en 18765.
- Revisa los privilegios de Fase B: instalar el helper root disminuye parte del sandbox systemd del agente.
- Realiza una copia de seguridad antes de aplicar cambios de seguridad delicados.

**No es una prueba de penetración, escáner CVE, auditoría exhaustiva de nftables, comprobación de conectividad desde Internet ni solución de detección de intrusiones.** Los hallazgos son pistas de configuración para revisión humana.

## Diagnóstico

~~~bash
systemctl --user status homelabos-agent --no-pager
journalctl --user -u homelabos-agent --no-pager -n 80
docker compose logs --tail=100 homelabos
curl -fsS http://127.0.0.1:8091/api/health
~~~

El informe está disponible solo después de iniciar sesión en HomeLab OS. Los fallos al conectar el agente se devuelven como error, nunca como un informe de seguridad simulado.
