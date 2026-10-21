# interfaz-backup

Interfaz web en Python (Flask) para monitorear servidores de copias de seguridad.

## Qué controla
- **Conexión**: ping al servidor, puerto del servicio (22 SSH / 445 carpeta compartida) y acceso a la carpeta de copias.
- **Almacenamiento**: total, usado, libre y % del disco donde están las copias.
- **Copias**: busca el archivo más reciente. Si pasó más de `intervalo_minutos` + `tolerancia_minutos` (por defecto 30 + 5) marca **ALERTA: no se hizo la copia**.
- **Estados**: OK · Copia atrasada · Sin acceso (usuario/contraseña) · Sin conexión (el servidor no responde).

## Funciones de la interfaz

**Vista Estado** (`/`)
- Filtros por estado con contador (Todas, Con problemas, OK, Copia atrasada, Sin acceso, Sin conexión).
- Ordenar por problemas, nombre, copia más vieja o disco más lleno.
- Vista en tarjetas o en tabla.
- Botón **Chequear** por carpeta y **Chequear todo**.
- **Silenciar** las alertas de una carpeta por 30 min, 1 h, 4 h o 24 h (por ejemplo, durante un mantenimiento).
- Historial de eventos con filtro por carpeta y tipo, y botón para limpiarlo. Se guarda en `data/monitor.json`.

**Vista Archivos** (`/archivos`)
- Últimos archivos modificados de cada carpeta.
- Buscador por nombre, filtro por fecha (última hora, hoy, 7 días, 30 días) y cantidad (20/50/100).
- Ordenar haciendo clic en las columnas.
- Exportar a Excel (CSV).

**Avisos**
- En pantalla: botón 🔔 para activar sonido y notificación del navegador cuando una carpeta pasa a alerta.
  Las notificaciones del navegador solo funcionan entrando por `localhost` o HTTPS; el sonido funciona siempre.
- Por mail y/o Telegram: se configuran en la sección `avisos` de `config.json`. Se envía un aviso cada vez que una carpeta cambia de estado (no si está silenciada).
  Para probarlos: `POST /api/avisos/probar`.

Las preferencias (filtros, orden, vista) se recuerdan en el navegador.

## Configuración
Los archivos con contraseñas **no se suben al repositorio**. Hay que crearlos a partir de los ejemplos:

| Archivo | Se crea desde | Para qué |
|---|---|---|
| `config.json` | `config.example.json` | Ejecutar en Windows sin Docker |
| `docker/config.json` | `docker/config.example.json` | Ejecutar con Docker |
| `.env` | `.env.example` | Servidores y credenciales de las carpetas compartidas (Docker) |

Cada carpeta en `servidores` puede ser:
- `"modo": "ssh"` → servidor Linux. Usa `usuario` + `password` o `clave_privada`, y `ruta_backups` (ej. `/backups`).
- `"modo": "ruta"` → carpeta local, unidad de red o ruta compartida (ej. `\\\\servidor\\backups`). En Windows, si tiene `usuario`/`password`, se conecta sola con `net use`.

Otros campos: `intervalo_minutos` (30), `tolerancia_minutos` (5), `alerta_disco_porcentaje` (90), `chequeo_cada_segundos` (60), `archivos_por_carpeta` (100), `eventos_a_guardar` (500).

### Avisos por mail / Telegram
```json
"avisos": {
  "email":    { "activo": true, "servidor": "smtp.gmail.com", "puerto": 587,
                "usuario": "cuenta@gmail.com", "password": "contraseña de aplicación",
                "remitente": "", "destinatarios": ["sistemas@empresa.com"] },
  "telegram": { "activo": true, "token": "TOKEN_DEL_BOT", "chat_id": "ID_DEL_CHAT" }
}
```

## Ejecutar sin Docker (Windows)
```
pip install -r requirements.txt
copy config.example.json config.json   (y completar los datos)
python app.py
```
Abrir http://localhost:5050

## Ejecutar con Docker
```
copy .env.example .env                              (y completar)
copy docker\config.example.json docker\config.json  (y completar)
docker compose up -d --build     # crear / actualizar y arrancar
docker compose logs -f           # ver el log
docker compose down              # detener
```
Dentro del contenedor las carpetas compartidas se leen en `/datos/...` (las monta `docker-compose.yml`).
Si se cambia una contraseña en `.env`, hay que recrear los volúmenes:
```
docker compose down -v && docker compose up -d
```
El contenedor arranca solo con Docker (`restart: unless-stopped`).
