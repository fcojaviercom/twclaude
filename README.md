# Servidor MCP de Teamwork — Despliegue en Render.com

Esta guía te lleva desde cero a tener el servidor funcionando en
Render.com con HTTPS automático, SSE bien configurado, y todo gratis.

---

## ARCHIVOS DEL PROYECTO

- `server.py` — el servidor MCP (no editar)
- `requirements.txt` — dependencias Python (no editar)
- `render.yaml` — configuración del despliegue (no editar)

---

## OPCIÓN A — Tienes cuenta de GitHub (recomendado)

### Paso 1 — Subir los archivos a GitHub

1. Ve a https://github.com/new y crea un repositorio nuevo:
   - **Repository name:** `teamwork-mcp`
   - **Privacy:** **Private** (importante, contendrá tu código)
   - Marca "Add a README file"
   - Crea el repo.

2. En el repositorio recién creado, pulsa **"Add file" → "Upload files"**.

3. Arrastra los 3 archivos: `server.py`, `requirements.txt`, `render.yaml`.

4. Pulsa **"Commit changes"**.

### Paso 2 — Crear cuenta en Render

1. Ve a https://render.com
2. **Sign up** → **Sign up with GitHub** (lo más rápido).
3. Autoriza el acceso a tus repos.

### Paso 3 — Crear el Web Service

1. En el dashboard de Render, pulsa **"+ New"** → **"Web Service"**.
2. Selecciona el repo `teamwork-mcp` que acabas de crear.
3. Render detectará el `render.yaml` automáticamente.
4. Antes de desplegar, configura las variables de entorno:

| Key | Value |
|---|---|
| `TEAMWORK_SITE` | tu site (ej: `wecomm.eu`) |
| `TEAMWORK_TOKEN` | tu token nuevo de Teamwork |
| `MCP_PATH` | `/mcp-` + 64 caracteres aleatorios |

5. Pulsa **"Create Web Service"**.

### Paso 4 — Esperar el primer despliegue

Render tardará 2-3 minutos en:
- Clonar el repo
- Instalar las dependencias Python
- Arrancar el servidor

Verás los logs en tiempo real. Cuando veas:

```
==> Servidor MCP escuchando en /mcp-...
INFO: Uvicorn running on http://0.0.0.0:10000
==> Your service is live 🎉
```

¡Está listo!

### Paso 5 — Tu URL

Render te ha asignado un dominio como:
```
https://teamwork-mcp-xxxx.onrender.com
```

Lo verás en la parte superior del dashboard del servicio.

Tu URL completa para Claude será:
```
https://teamwork-mcp-xxxx.onrender.com/mcp-tu_path_secreto
```

---

## OPCIÓN B — No tienes GitHub o prefieres no usarlo

Render tiene una opción "Public Git repository" donde puedes pegar la URL
de cualquier repo público. Pero requiere tener el código en un repo, así
que la opción más práctica si no quieres GitHub es **crear cuenta gratis**
solo para esto.

Otra alternativa: **Railway.app**, que permite "drag & drop" de archivos.
Si prefieres Railway, dímelo y te genero la guía adaptada.

---

## PROBAR QUE FUNCIONA

### Prueba 1 — La URL responde

Abre en el navegador tu URL completa:
```
https://teamwork-mcp-xxxx.onrender.com/mcp-tu_path_secreto
```

Debe devolver:
```json
{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Not Acceptable: Client must accept text/event-stream"}}
```

Si te devuelve eso, el servidor está vivo.

Si te devuelve **404**: tu MCP_PATH no está bien configurado.
Si te devuelve **502/503**: el servicio no arrancó. Mira los logs en Render.

### Prueba 2 — Conectar a Claude

1. Ve a Claude.ai → **Settings → Connectors**.
2. Si "Teamwork" sigue de antes, **bórralo**.
3. **Add custom connector**.
4. **Name:** Teamwork
5. **Remote MCP server URL:** la URL completa con tu path secreto.
6. **Add**.

Si todo va bien, NO te pedirá Bearer token (porque la auth la hace
implícita el path secreto). Verás "Connected" en verde y la lista de
herramientas.

### Prueba 3 — Usar el conector

1. Abre un **chat NUEVO**.
2. Activa el conector "Teamwork" (botón "+").
3. Pide: "Lista mis proyectos activos de Teamwork".

---

## NOTAS DEL PLAN GRATIS DE RENDER

- **El servicio "duerme" tras 15 min sin uso.** La primera petición
  después tarda ~30 segundos en despertar el servicio. Tras eso va rápido.

- **Si quieres mantenerlo despierto**, hay un truco gratuito: usar un
  servicio como cron-job.org para hacer ping a tu URL cada 14 minutos.
  Si quieres configurarlo, dímelo.

- **750 horas/mes gratis** — más que suficiente para uso personal.

---

## ACTUALIZAR EL CÓDIGO MÁS ADELANTE

Si algún día modificas `server.py`:

1. **Por GitHub:** sube el archivo modificado al repo. Render redespliega automáticamente.
2. **Sin GitHub:** edita el archivo en el editor web de Render (si está disponible).

---

## SEGURIDAD

- Tu `MCP_PATH` es lo único que protege el acceso. **No lo compartas**.
- Si lo expones por accidente, regenéralo (cambia la env var en Render
  y reinicia el servicio).
- El repo de GitHub debe ser **privado** porque incluye tu código,
  aunque las credenciales sensibles van en variables de entorno (NUNCA
  en `server.py`).
