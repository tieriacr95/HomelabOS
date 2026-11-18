# Recuperar datos de HomeLab OS y aplicaciones Docker

La fase D restaura copias **solo a staging**, no a producción. Este documento describe cómo practicar recuperación y aplicar un cambio controlado después de verificar una copia.

## 1. Preparar una restauración

En http://localhost:8091 abre Respaldos → Snapshots, selecciona una copia y pulsa Preparar recuperación. Escribe la frase exacta RESTAURAR seguida por el ID mostrado.

En Trabajos consulta la ruta destino bajo:

~~~text
~/.local/state/homelabos/backup/restores/
~~~

En cada carpeta hay un manifest.json con archivos que se guardaron durante el backup. El manifiesto permite distinguir dumps PostgreSQL, backups de SQLite, archivos TAR de volúmenes y archivos de directorios.

Asegura que tu usuario Fedora conserva el acceso; la carpeta es privada y contiene datos descifrados. No compartas los dumps ni los archivos de datos.

## 2. Probar SQLite de HomeLab OS

El propio proceso de recuperación realiza PRAGMA integrity_check y fallará si el resultado no es ok.

Para una verificación manual:

~~~bash
python3 - /RUTA/RESTAURADA/homelabos/homelabos.db <<'PY'
import sqlite3, sys
with sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True) as db:
    print(db.execute('PRAGMA integrity_check').fetchone()[0])
PY
~~~

Para reemplazar la base usada por HomeLab OS, crea una copia adicional del estado actual, detén el contenedor homelabos, sustituye data/homelabos.db desde un archivo verificado con el usuario correcto y vuelve a arrancar el servicio. Jamás reemplaces el fichero SQLite mientras la aplicación esté activa: puede tener archivos WAL/SHM pendientes.

## 3. Probar un dump PostgreSQL

Los dumps son archivos de texto PostgreSQL creados con pg_dumpall. Para probar uno, utiliza una instancia PostgreSQL de pruebas separada y **no** una base existente con información de producción.

Ejemplo orientativo, con un contenedor de pruebas aislado y con la versión de PostgreSQL adecuada:

~~~bash
# Prepara primero una instancia PostgreSQL temporal sin publicar puertos.
# Confirma que es una instancia desechable, no un servicio real.
docker ps -a
# Después importa allí el dump, usando psql y las credenciales del entorno de pruebas.
~~~

Los dumps pg_dumpall pueden incluir CREATE ROLE, CREATE DATABASE y otra información sensible, y pueden sobrescribir objetos si los importas en un servidor real. Revisa siempre el contenido y prueba primero en un contenedor desechable.

Para producción, el procedimiento seguro es acordar mantenimiento, comprobar backups recientes, detener las aplicaciones que escriben, provisionar una base nueva o vacía, restaurar con las herramientas nativas de PostgreSQL y realizar verificaciones antes de volver a abrir tráfico. No importes directamente en las bases de Finance OS, Personal Planner o Cloud Engineer Lab sin comprobar la compatibilidad del esquema y la versión PostgreSQL.

## 4. Recuperar un volumen Docker

Los archivos TAR se capturaron de un volumen con acceso de solo lectura. Para practicar una recuperación, **crea primero un volumen nuevo** y restaura allí los archivos, sin tocar el volumen original.

~~~bash
docker volume create homelabos-restore-test
docker volume ls
~~~

No asumas que un volumen que figura como disponible está libre de usuarios: comprueba docker ps --filter volume=NOMBRE y docker inspect antes de reemplazar uno existente. La aplicación de HomeLab OS no monta volúmenes recuperados sobre una ruta de producción ni cambia Docker Compose automáticamente.

La extracción de TAR a un volumen de prueba puede requerir la imagen local busybox:1.36. Comprueba previamente la estructura y no extraigas archivos suministrados por terceros a un destino sensible.

## 5. Recuperar directorios

Los recursos directory se restauran bajo la misma carpeta de staging, no dentro del proyecto original. Compara permisos, propietario, estructura y diferencias antes de copiarlos. Mantén una copia de la versión actual y detén las aplicaciones que escriban archivos.

## 6. Resultado del simulacro

Registra como mínimo:

- Fecha, ID del snapshot, aplicaciones y recursos cubiertos.
- Tiempo para obtener una copia descifrada y verificar integridad.
- Resultado de la importación de PostgreSQL a una base temporal.
- Resultado de iniciar un servicio temporal usando el volumen o directorio recuperado.
- Problemas con versiones de Docker/PostgreSQL, SELinux o permisos.
- Ubicación de una copia externa del repositorio restic y de la clave.

**Una copia no está verificada para recuperación hasta que puedas restaurar y arrancar las aplicaciones necesarias.** Los datos guardados en el mismo disco requieren réplica fuera del equipo para soportar pérdida del host.

## 7. Limpiar datos descifrados

Después de las pruebas elimina únicamente la carpeta de restauración específica que tú mismo has comprobado. No uses patrones globales ni elimines el repositorio cifrado. Ten presente que borrar archivos en SSD o sistemas CoW no garantiza borrado criptográfico de bloques; utiliza cifrado de disco completo si el host necesita esa garantía.
