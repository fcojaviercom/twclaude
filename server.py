"""
Servidor MCP HTTP para Teamwork.com — Versión para Render.com
Sin autenticación a nivel de protocolo MCP — la protección viene de
que el path del endpoint contiene un componente secreto largo y aleatorio
(MCP_PATH), que actúa como token implícito.

La URL completa solo la conoce el dueño del servidor, lo que en la
práctica funciona como un token Bearer transmitido por la propia ruta.
"""

import os
import base64
from typing import Any
import httpx
from fastmcp import FastMCP


# ============================================================
# CONFIGURACIÓN (vienen como env vars en Render)
# ============================================================
TEAMWORK_SITE = os.getenv("TEAMWORK_SITE", "")
TEAMWORK_TOKEN = os.getenv("TEAMWORK_TOKEN", "")
MCP_PATH = os.getenv("MCP_PATH", "")

if not TEAMWORK_SITE or not TEAMWORK_TOKEN:
    raise RuntimeError("Faltan TEAMWORK_SITE o TEAMWORK_TOKEN.")
if not MCP_PATH or len(MCP_PATH) < 32:
    raise RuntimeError("MCP_PATH ausente o demasiado corto (mínimo 32 caracteres).")

# Asegurar que el path empiece con "/"
if not MCP_PATH.startswith("/"):
    MCP_PATH = "/" + MCP_PATH

# Construir BASE_URL.
# Soporta tres formatos para TEAMWORK_SITE:
#   - "miempresa"             -> https://miempresa.teamwork.com
#   - "miempresa.eu"          -> https://miempresa.eu.teamwork.com
#   - "projects.miempresa.es" -> https://projects.miempresa.es  (dominio propio)
#   - "https://projects.miempresa.es" -> se respeta tal cual
if TEAMWORK_SITE.startswith("http://") or TEAMWORK_SITE.startswith("https://"):
    BASE_URL = TEAMWORK_SITE.rstrip("/")
elif "." in TEAMWORK_SITE and not TEAMWORK_SITE.endswith(".eu"):
    # Tiene puntos y no termina en ".eu" -> es un dominio propio completo
    BASE_URL = f"https://{TEAMWORK_SITE.rstrip('/')}"
else:
    # Es un site name de Teamwork (con o sin .eu)
    BASE_URL = f"https://{TEAMWORK_SITE}.teamwork.com"

print(f"==> Conectando a Teamwork en: {BASE_URL}")
auth_str = f"{TEAMWORK_TOKEN}:X"
auth_b64 = base64.b64encode(auth_str.encode()).decode()
TEAMWORK_HEADERS = {
    "Authorization": f"Basic {auth_b64}",
    "Content-Type": "application/json",
}
client = httpx.AsyncClient(headers=TEAMWORK_HEADERS, timeout=30.0)


# ============================================================
# INICIALIZAR FASTMCP
# ============================================================
mcp = FastMCP(
    name="teamwork",
    instructions="MCP de Teamwork.com — gestiona proyectos, tareas, empleados y tiempo.",
)


# ============================================================
# Helpers HTTP a Teamwork
# ============================================================
async def api_get(path: str, params: dict | None = None) -> dict[str, Any]:
    r = await client.get(f"{BASE_URL}{path}", params=params or {})
    r.raise_for_status()
    return r.json()


async def api_post(path: str, payload: dict) -> dict[str, Any]:
    r = await client.post(f"{BASE_URL}{path}", json=payload)
    r.raise_for_status()
    return r.json()


async def api_patch(path: str, payload: dict) -> dict[str, Any]:
    r = await client.patch(f"{BASE_URL}{path}", json=payload)
    r.raise_for_status()
    return r.json()


async def api_put(path: str, payload: dict) -> dict[str, Any]:
    r = await client.put(f"{BASE_URL}{path}", json=payload)
    r.raise_for_status()
    return r.json()


def _extract_project_from_task(task: dict, included: dict) -> tuple[int | None, str]:
    """Extrae (project_id, project_name) de una tarea + sideloads.

    En la API v3 de Teamwork la jerarquía es Proyecto -> Tasklist -> Tarea.
    La tarea solo conoce su tasklist (campo 'tasklistId').
    Para llegar al proyecto hay que:
      tasklist_id -> included.tasklists[tasklist_id].projectId -> included.projects[project_id]

    Si los sideloads no incluyen tasklists pero solo hay UN proyecto en included.projects,
    asumimos que ese es el proyecto (caso de get_task con un único include).
    """
    if not included:
        return None, "(proyecto desconocido)"

    projects = included.get("projects", {}) or {}
    tasklists = included.get("tasklists", {}) or {}

    tasklist_id = task.get("tasklistId")

    # Camino 1: ideal - tasklist -> projectId -> proyecto
    if tasklist_id and tasklists:
        tl = tasklists.get(str(tasklist_id))
        if tl:
            project_id = tl.get("projectId") or tl.get("project", {}).get("id")
            if project_id and str(project_id) in projects:
                return project_id, projects[str(project_id)].get("name", "(sin nombre)")

    # Camino 2: fallback - solo hay un proyecto en included, asumimos que es ese
    if len(projects) == 1:
        project_id_str = next(iter(projects))
        return int(project_id_str), projects[project_id_str].get("name", "(sin nombre)")

    # Camino 3: no podemos resolver
    return None, "(proyecto desconocido)"


# ============================================================
# PROYECTOS
# ============================================================
@mcp.tool
async def list_projects(status: str = "active", page_size: int = 250) -> str:
    """Lista proyectos.

    Args:
        status: "active", "archived" o "all".
        page_size: cuántos proyectos devolver máximo (1-500). Por defecto 250.
    """
    params = {
        "status": status,
        "pageSize": min(max(page_size, 1), 500),
    }
    data = await api_get("/projects/api/v3/projects.json", params)
    projects = data.get("projects", [])
    if not projects:
        return "No hay proyectos."
    lines = [f"Proyectos ({len(projects)}):"]
    for p in projects:
        lines.append(f"- [{p['id']}] {p.get('name')} (estado: {p.get('status', 'N/A')})")
    return "\n".join(lines)


@mcp.tool
async def get_project(project_id: int) -> str:
    """Detalles de un proyecto."""
    data = await api_get(f"/projects/api/v3/projects/{project_id}.json")
    p = data.get("project", {})
    return (
        f"Proyecto: {p.get('name')}\nID: {p.get('id')}\n"
        f"Descripción: {p.get('description', 'sin descripción')}\n"
        f"Estado: {p.get('status')}\n"
        f"Inicio: {p.get('startDate', 'N/A')}\nFin: {p.get('endDate', 'N/A')}"
    )


# ============================================================
# TAREAS
# ============================================================
@mcp.tool
async def list_tasks(
    project_id: int | None = None,
    assigned_to_user_id: int | None = None,
    completed: bool = False,
    page_size: int = 200,
) -> str:
    """Lista tareas. Filtros opcionales: proyecto, asignado, completadas.

    Args:
        project_id: filtrar por proyecto.
        assigned_to_user_id: filtrar por usuario asignado (ID numérico).
        completed: si True, incluye también las completadas.
        page_size: cuántas tareas devolver máximo (1-500). Por defecto 200.
    """
    params: dict[str, Any] = {
        "includeCompletedTasks": str(completed).lower(),
        "pageSize": min(max(page_size, 1), 500),
        "include": "projects,tasklists",
    }
    # Pasamos los IDs como string CSV (formato exigido por la API v3)
    if assigned_to_user_id is not None:
        params["assignedToUserIds"] = str(assigned_to_user_id)
    if project_id is not None:
        params["projectIds"] = str(project_id)

    data = await api_get("/projects/api/v3/tasks.json", params)
    tasks = data.get("tasks", [])
    included = data.get("included", {})
    if not tasks:
        return "No hay tareas que coincidan con los filtros."
    lines = [f"Tareas ({len(tasks)}):"]
    for t in tasks:
        assignees = t.get("assigneeUserIds", []) or []
        due = t.get("dueAt") or "sin fecha"
        proj_id, proj_name = _extract_project_from_task(t, included)
        lines.append(
            f"- [{t['id']}] {t.get('name')} | proyecto: {proj_name} [{proj_id}] "
            f"| vence: {due} | asignados: {assignees}"
        )
    return "\n".join(lines)


import json


@mcp.tool
async def debug_get_task_raw(task_id: int) -> str:
    """[DEBUG] Devuelve el JSON crudo de la API para una tarea.
    Sirve para ver qué nombres de campos usa Teamwork (projectId, project.id, etc.)
    y dónde aparece el proyecto. Borrar esta herramienta cuando termine la depuración.
    """
    data = await api_get(
        f"/projects/api/v3/tasks/{task_id}.json",
        {"include": "projects,tasklists"},
    )
    # Devolver formateado y truncado para no saturar
    pretty = json.dumps(data, indent=2, ensure_ascii=False)
    if len(pretty) > 8000:
        pretty = pretty[:8000] + "\n... (respuesta truncada)"
    return f"Respuesta cruda de Teamwork:\n{pretty}"


@mcp.tool
async def debug_try_complete(task_id: int, payload_variant: str = "status") -> str:
    """[DEBUG] Intenta completar una tarea con distintos payloads para ver cuál acepta Teamwork.

    Args:
        task_id: ID de la tarea
        payload_variant: cuál probar:
            - "status": {"task": {"status": "completed"}}
            - "completed_bool": {"task": {"completed": true}}
            - "progress": {"task": {"progress": 100}}
            - "completed_and_progress": {"task": {"completed": true, "progress": 100}}
            - "v1_endpoint": PUT /tasks/{id}/complete.json (ruta v1)
    """
    if payload_variant == "v1_endpoint":
        url = f"{BASE_URL}/tasks/{task_id}/complete.json"
        try:
            r = await client.put(url, json={})
            return f"v1_endpoint: status={r.status_code}, body={r.text[:500]}"
        except Exception as e:
            return f"v1_endpoint: EXCEPTION {type(e).__name__}: {e}"

    payloads = {
        "status": {"task": {"status": "completed"}},
        "completed_bool": {"task": {"completed": True}},
        "progress": {"task": {"progress": 100}},
        "completed_and_progress": {"task": {"completed": True, "progress": 100}},
    }
    if payload_variant not in payloads:
        return f"variant inválida. Opciones: {list(payloads.keys())} + v1_endpoint"

    payload = payloads[payload_variant]
    url = f"{BASE_URL}/projects/api/v3/tasks/{task_id}.json"
    try:
        r = await client.patch(url, json=payload)
        return (
            f"Variant '{payload_variant}'\n"
            f"Payload enviado: {json.dumps(payload)}\n"
            f"HTTP status: {r.status_code}\n"
            f"Respuesta cruda: {r.text[:1500]}"
        )
    except Exception as e:
        return f"EXCEPTION {type(e).__name__}: {e}"


@mcp.tool
async def get_task(task_id: int) -> str:
    """Detalles completos de una tarea, incluyendo el proyecto al que pertenece."""
    data = await api_get(
        f"/projects/api/v3/tasks/{task_id}.json",
        {"include": "projects,tasklists"},
    )
    t = data.get("task", {})
    included = data.get("included", {})
    project_id, project_name = _extract_project_from_task(t, included)

    return (
        f"Tarea: {t.get('name')}\n"
        f"ID: {t.get('id')}\n"
        f"Proyecto: {project_name} [{project_id}]\n"
        f"Descripción: {t.get('description', 'sin descripción')}\n"
        f"Estado: {'completada' if t.get('completed') else 'pendiente'}\n"
        f"Prioridad: {t.get('priority', 'normal')}\n"
        f"Inicio: {t.get('startAt', 'N/A')}\n"
        f"Vencimiento: {t.get('dueAt', 'N/A')}\n"
        f"Asignados: {t.get('assigneeUserIds', [])}\n"
        f"Progreso: {t.get('progress', 0)}%"
    )


@mcp.tool
async def create_task(
    name: str,
    tasklist_id: int | None = None,
    parent_task_id: int | None = None,
    description: str = "",
    assignee_user_ids: list[int] | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    priority: str = "normal",
) -> str:
    """Crea una tarea nueva o una subtarea bajo una tarea padre.

    Modos de uso:
    - Tarea normal: pasar tasklist_id (NO parent_task_id).
    - Subtarea:     pasar parent_task_id (NO tasklist_id, hereda el del padre).

    Args:
        name: Nombre de la tarea (obligatorio).
        tasklist_id: ID de la lista donde crear la tarea. Obligatorio si es tarea normal.
        parent_task_id: Si se indica, se creará como SUBTAREA bajo esa tarea padre.
        description: Descripción opcional.
        assignee_user_ids: Lista de IDs de empleados asignados.
        start_date: Fecha inicio YYYY-MM-DD.
        due_date: Fecha vencimiento YYYY-MM-DD.
        priority: "low", "normal" o "high".
    """
    # Validación de modos: uno y solo uno de los dos campos.
    if parent_task_id is None and tasklist_id is None:
        return "Error: debes indicar tasklist_id (tarea normal) o parent_task_id (subtarea)."
    if parent_task_id is not None and tasklist_id is not None:
        return (
            "Error: pasa solo UNO de los dos: tasklist_id (para tarea normal) "
            "o parent_task_id (para subtarea). No los dos a la vez."
        )

    # Construir el payload común
    task_data: dict[str, Any] = {
        "name": name,
        "priority": priority,
    }
    if tasklist_id is not None:
        task_data["tasklistId"] = tasklist_id
    if description:
        task_data["description"] = description
    if assignee_user_ids:
        task_data["assignees"] = {"userIds": assignee_user_ids}
    if start_date:
        task_data["startAt"] = start_date
    if due_date:
        task_data["dueAt"] = due_date

    # Elegir endpoint según el modo
    if parent_task_id is not None:
        endpoint = f"/projects/api/v3/tasks/{parent_task_id}/subtasks.json"
    else:
        endpoint = f"/projects/api/v3/tasklists/{tasklist_id}/tasks.json"

    data = await api_post(endpoint, {"task": task_data})
    t = data.get("task", {})
    kind = "Subtarea" if parent_task_id is not None else "Tarea"
    return f"{kind} creada: [{t.get('id')}] {t.get('name')}"


@mcp.tool
async def update_task(
    task_id: int,
    name: str | None = None,
    description: str | None = None,
    assignee_user_ids: list[int] | None = None,
    due_date: str | None = None,
    priority: str | None = None,
) -> str:
    """Actualiza una tarea (solo los campos pasados)."""
    update: dict[str, Any] = {}
    if name is not None:
        update["name"] = name
    if description is not None:
        update["description"] = description
    if assignee_user_ids is not None:
        update["assignees"] = {"userIds": assignee_user_ids}
    if due_date is not None:
        update["dueAt"] = due_date
    if priority is not None:
        update["priority"] = priority

    if not update:
        return "No hay cambios que aplicar."
    await api_patch(f"/projects/api/v3/tasks/{task_id}.json", {"task": update})
    return f"Tarea {task_id} actualizada correctamente."


@mcp.tool
async def complete_task(task_id: int) -> str:
    """Marca una tarea como completada (cierra la tarea)."""
    # Teamwork v3 exige AMBOS campos: completed=True + progress=100.
    # Solo uno de los dos no completa de verdad (responde 200 pero no cambia status).
    payload = {"task": {"completed": True, "progress": 100}}
    await api_patch(f"/projects/api/v3/tasks/{task_id}.json", payload)
    return f"Tarea {task_id} marcada como completada."


@mcp.tool
async def reopen_task(task_id: int) -> str:
    """Reabre una tarea previamente completada (vuelve a 'new')."""
    # Simétrico a complete_task: ambos campos a la vez.
    payload = {"task": {"completed": False, "progress": 0}}
    await api_patch(f"/projects/api/v3/tasks/{task_id}.json", payload)
    return f"Tarea {task_id} reabierta."


@mcp.tool
async def delete_task(task_id: int, confirm: bool = False) -> str:
    """Borra DEFINITIVAMENTE una tarea de Teamwork. Operación irreversible.

    PROTOCOLO DE SEGURIDAD OBLIGATORIO:
    Antes de llamar a esta herramienta con confirm=True, el asistente DEBE:
    1. Llamar a get_task(task_id) para obtener los detalles de la tarea.
    2. Mostrar al usuario el nombre, asignados, descripción y fecha.
    3. Pedir confirmación EXPLÍCITA al usuario en el chat.
    4. SOLO SI el usuario confirma claramente (ej: "sí, bórrala"),
       llamar de nuevo a delete_task con confirm=True.

    Args:
        task_id: ID de la tarea a borrar.
        confirm: Debe ser True para ejecutar el borrado. Si es False,
                 la herramienta solo devolverá una advertencia sin borrar nada.

    NUNCA usar confirm=True en una primera llamada. NUNCA borrar varias
    tareas en bucle sin confirmación una a una. La operación es IRREVERSIBLE
    y la API de Teamwork no ofrece deshacer.
    """
    if not confirm:
        return (
            f"⚠️ BORRADO NO EJECUTADO. Para borrar la tarea {task_id} debes:\n"
            f"1. Mostrar al usuario los detalles de la tarea (usa get_task).\n"
            f"2. Pedir confirmación explícita en el chat.\n"
            f"3. Solo entonces, llamar a delete_task con confirm=True.\n"
            f"Esta operación es irreversible."
        )

    # Ejecutar borrado real
    url = f"{BASE_URL}/projects/api/v3/tasks/{task_id}.json"
    response = await client.delete(url)
    response.raise_for_status()
    return f"✓ Tarea {task_id} BORRADA definitivamente. Esta acción no se puede deshacer."


# ============================================================
# LISTAS DE TAREAS
# ============================================================
@mcp.tool
async def list_tasklists(project_id: int) -> str:
    """Lista las tasklists de un proyecto. Necesario para crear tareas."""
    data = await api_get(f"/projects/api/v3/projects/{project_id}/tasklists.json")
    tasklists = data.get("tasklists", [])
    if not tasklists:
        return "No hay listas de tareas en este proyecto."
    lines = [f"Listas de tareas ({len(tasklists)}):"]
    for tl in tasklists:
        lines.append(f"- [{tl['id']}] {tl.get('name')}")
    return "\n".join(lines)


# ============================================================
# USUARIOS
# ============================================================
@mcp.tool
async def list_users() -> str:
    """Lista los empleados del workspace."""
    data = await api_get("/projects/api/v3/people.json")
    people = data.get("people", [])
    if not people:
        return "No hay usuarios."
    lines = [f"Usuarios ({len(people)}):"]
    for u in people:
        full_name = f"{u.get('firstName', '')} {u.get('lastName', '')}".strip()
        lines.append(
            f"- [{u['id']}] {full_name} | {u.get('email', 'sin email')} | rol: {u.get('title', 'N/A')}"
        )
    return "\n".join(lines)


@mcp.tool
async def get_user_workload(
    user_id: int,
    completed: bool = False,
    page_size: int = 200,
) -> str:
    """Tareas pendientes de un empleado concreto.

    Args:
        user_id: ID numérico del empleado.
        completed: si True, incluye también las completadas.
        page_size: cuántas tareas devolver máximo (1-500). Por defecto 200.
    """
    params: dict[str, Any] = {
        # CSV string explícito - formato exigido por la API v3
        "assignedToUserIds": str(user_id),
        "includeCompletedTasks": str(completed).lower(),
        "pageSize": min(max(page_size, 1), 500),
        "include": "projects,tasklists",
    }
    data = await api_get("/projects/api/v3/tasks.json", params)
    tasks = data.get("tasks", [])
    included = data.get("included", {})
    if not tasks:
        return f"El usuario {user_id} no tiene tareas pendientes."

    # Verificación: filtrar localmente por si la API devolviera tareas
    # que no contienen este user en sus assignees (defensa frente a bugs)
    filtered = []
    for t in tasks:
        assignees = t.get("assigneeUserIds", []) or []
        if user_id in assignees:
            filtered.append(t)

    if not filtered:
        return (
            f"El usuario {user_id} no tiene tareas asignadas directamente. "
            f"(La API devolvió {len(tasks)} tareas pero ninguna está asignada a este usuario)."
        )

    lines = [f"Carga de trabajo del usuario {user_id} ({len(filtered)} tareas):"]
    for t in filtered:
        due = t.get("dueAt") or "sin fecha"
        priority = t.get("priority", "normal")
        proj_id, proj_name = _extract_project_from_task(t, included)
        lines.append(
            f"- [{t['id']}] {t.get('name')} | proyecto: {proj_name} [{proj_id}] "
            f"| vence: {due} | prioridad: {priority}"
        )
    return "\n".join(lines)


# ============================================================
# COMENTARIOS Y ACTIVIDAD
# ============================================================
@mcp.tool
async def get_task_comments(
    task_id: int,
    page_size: int = 50,
    order: str = "desc",
) -> str:
    """Devuelve los comentarios de una tarea con autor y fecha.

    Args:
        task_id: ID de la tarea.
        page_size: Cuántos comentarios traer (1-100). Por defecto 50.
        order: "desc" (más recientes primero) o "asc" (más antiguos primero).
    """
    params: dict[str, Any] = {
        "include": "users",
        "pageSize": min(max(page_size, 1), 100),
        "orderBy": "date",
        "orderMode": order if order in ("asc", "desc") else "desc",
    }
    data = await api_get(f"/projects/api/v3/tasks/{task_id}/comments.json", params)
    comments = data.get("comments", [])
    included = data.get("included", {})
    users = included.get("users", {}) or {}

    if not comments:
        return f"La tarea {task_id} no tiene comentarios."

    lines = [f"Comentarios de la tarea {task_id} ({len(comments)}):"]
    for c in comments:
        # Autor
        author_id = c.get("postedBy") or c.get("authorId") or c.get("userId")
        author_name = "(desconocido)"
        if author_id and str(author_id) in users:
            u = users[str(author_id)]
            author_name = f"{u.get('firstName', '')} {u.get('lastName', '')}".strip() or "(sin nombre)"

        # Fecha
        when = c.get("postedAt") or c.get("dateCreated") or c.get("createdAt") or "fecha desconocida"

        # Cuerpo (recortar si es muy largo)
        body = (c.get("body") or "").strip()
        if len(body) > 400:
            body = body[:400] + "…"

        lines.append(
            f"\n[{c.get('id')}] {author_name} ({when}):\n{body}"
        )
    return "\n".join(lines)


@mcp.tool
async def get_project_activity(
    project_id: int,
    days_back: int = 7,
    page_size: int = 100,
) -> str:
    """Actividad reciente de un proyecto: comentarios, cambios de estado,
    tareas creadas/completadas, etc.

    Args:
        project_id: ID del proyecto.
        days_back: Cuántos días hacia atrás mirar. Por defecto 7.
        page_size: Máximo de eventos a devolver (1-200). Por defecto 100.
    """
    from datetime import datetime, timedelta, timezone
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params: dict[str, Any] = {
        "startDate": start_date,
        "pageSize": min(max(page_size, 1), 200),
    }
    data = await api_get(
        f"/projects/api/v3/projects/{project_id}/latestactivity.json",
        params,
    )
    activities = data.get("activities", [])
    if not activities:
        return f"No hay actividad en el proyecto {project_id} en los últimos {days_back} días."

    lines = [f"Actividad del proyecto {project_id} ({len(activities)} eventos en {days_back} días):"]
    for a in activities:
        when = a.get("dateTime", "fecha desconocida")
        action_type = a.get("activityType", "?")
        description = a.get("description") or a.get("extraDescription") or ""
        # Usuario que hizo la acción
        for_user = a.get("forUser") or {}
        user_id = for_user.get("id") if isinstance(for_user, dict) else None
        user_str = f"user:{user_id}" if user_id else "?"
        lines.append(f"- {when} | {action_type} | {user_str} | {description[:200]}")
    return "\n".join(lines)


@mcp.tool
async def get_user_activity(
    user_id: int,
    days_back: int = 1,
    page_size: int = 100,
) -> str:
    """Actividad reciente de un usuario en todos los proyectos.
    Permite saber qué tocó cada persona hoy o en los últimos N días.

    Args:
        user_id: ID del usuario.
        days_back: Cuántos días hacia atrás. Por defecto 1 (hoy).
        page_size: Máximo de eventos (1-200). Por defecto 100.
    """
    from datetime import datetime, timedelta, timezone
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params: dict[str, Any] = {
        "startDate": start_date,
        "userIds": str(user_id),
        "pageSize": min(max(page_size, 1), 200),
    }
    data = await api_get("/projects/api/v3/latestactivity.json", params)
    activities = data.get("activities", [])
    if not activities:
        return f"El usuario {user_id} no tiene actividad en los últimos {days_back} días."

    lines = [f"Actividad del usuario {user_id} ({len(activities)} eventos en {days_back} días):"]
    for a in activities:
        when = a.get("dateTime", "?")
        action_type = a.get("activityType", "?")
        description = a.get("description") or a.get("extraDescription") or ""
        company = a.get("company") or {}
        project = a.get("project") or {}
        proj_id = project.get("id") if isinstance(project, dict) else None
        proj_str = f"proj:{proj_id}" if proj_id else ""
        lines.append(f"- {when} | {action_type} | {proj_str} | {description[:200]}")
    return "\n".join(lines)


@mcp.tool
async def get_user_logged_time(
    user_id: int,
    days_back: int = 7,
    page_size: int = 200,
) -> str:
    """Tiempo registrado por un usuario en los últimos N días.

    Args:
        user_id: ID del usuario.
        days_back: Cuántos días hacia atrás. Por defecto 7.
        page_size: Máximo de entradas (1-500). Por defecto 200.
    """
    from datetime import datetime, timedelta, timezone
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params: dict[str, Any] = {
        "userIds": str(user_id),
        "startDate": start_date,
        "pageSize": min(max(page_size, 1), 500),
        "include": "projects,tasks",
    }
    data = await api_get("/projects/api/v3/time.json", params)
    entries = data.get("timelogs", []) or data.get("time", [])
    included = data.get("included", {}) or {}
    projects = included.get("projects", {}) or {}
    tasks = included.get("tasks", {}) or {}

    if not entries:
        return f"El usuario {user_id} no tiene tiempo registrado en los últimos {days_back} días."

    total_minutes = 0
    lines = [f"Tiempo registrado por usuario {user_id} (últimos {days_back} días):"]
    for e in entries:
        hours = e.get("hours", 0) or 0
        minutes = e.get("minutes", 0) or 0
        total_minutes += hours * 60 + minutes
        date = e.get("date", "?")
        billable = "💰" if e.get("isBillable") else "  "
        # Resolver proyecto y tarea
        proj_id = e.get("projectId")
        task_id = e.get("taskId")
        proj_name = projects.get(str(proj_id), {}).get("name", "?") if proj_id else "?"
        task_name = tasks.get(str(task_id), {}).get("name", "—") if task_id else "—"
        descr = (e.get("description") or "").strip()[:100]
        lines.append(
            f"- {date} | {hours}h {minutes}m {billable} | {proj_name} | {task_name} | {descr}"
        )

    total_h = total_minutes // 60
    total_m = total_minutes % 60
    lines.append(f"\nTotal: {total_h}h {total_m}m ({len(entries)} entradas)")
    return "\n".join(lines)


# ============================================================
# REGISTRO DE TIEMPO
# ============================================================
@mcp.tool
async def log_time(
    task_id: int,
    user_id: int,
    hours: int,
    minutes: int,
    date: str,
    description: str = "",
    billable: bool = False,
) -> str:
    """Registra tiempo trabajado. date: YYYY-MM-DD."""
    payload = {
        "timelog": {
            "userId": user_id,
            "hours": hours,
            "minutes": minutes,
            "date": date,
            "description": description,
            "isBillable": billable,
        }
    }
    await api_post(f"/projects/api/v3/tasks/{task_id}/time.json", payload)
    return f"Tiempo registrado: {hours}h {minutes}m en la tarea {task_id}."


# ============================================================
# ARRANQUE — Render usa la variable PORT
# ============================================================
if __name__ == "__main__":
    # Render asigna el puerto vía la env var PORT
    port = int(os.getenv("PORT", "8000"))
    print(f"==> Servidor MCP escuchando en {MCP_PATH} (puerto {port})")
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port,
        path=MCP_PATH,
    )
