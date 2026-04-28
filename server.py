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


# ============================================================
# PROYECTOS
# ============================================================
@mcp.tool
async def list_projects(status: str = "active") -> str:
    """Lista proyectos. status: active | archived | all."""
    data = await api_get("/projects/api/v3/projects.json", {"status": status})
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
) -> str:
    """Lista tareas. Filtros opcionales: proyecto, asignado, completadas."""
    params: dict[str, Any] = {"includeCompletedTasks": str(completed).lower()}
    if assigned_to_user_id:
        params["assignedToUserIds"] = assigned_to_user_id
    if project_id:
        params["projectIds"] = project_id

    data = await api_get("/projects/api/v3/tasks.json", params)
    tasks = data.get("tasks", [])
    if not tasks:
        return "No hay tareas que coincidan con los filtros."
    lines = [f"Tareas ({len(tasks)}):"]
    for t in tasks:
        assignees = t.get("assigneeUserIds", []) or []
        due = t.get("dueAt") or "sin fecha"
        lines.append(f"- [{t['id']}] {t.get('name')} | vence: {due} | asignados: {assignees}")
    return "\n".join(lines)


@mcp.tool
async def get_task(task_id: int) -> str:
    """Detalles completos de una tarea."""
    data = await api_get(f"/projects/api/v3/tasks/{task_id}.json")
    t = data.get("task", {})
    return (
        f"Tarea: {t.get('name')}\nID: {t.get('id')}\n"
        f"Descripción: {t.get('description', 'sin descripción')}\n"
        f"Estado: {'completada' if t.get('completed') else 'pendiente'}\n"
        f"Prioridad: {t.get('priority', 'normal')}\n"
        f"Inicio: {t.get('startAt', 'N/A')}\nVencimiento: {t.get('dueAt', 'N/A')}\n"
        f"Asignados: {t.get('assigneeUserIds', [])}\nProgreso: {t.get('progress', 0)}%"
    )


@mcp.tool
async def create_task(
    tasklist_id: int,
    name: str,
    description: str = "",
    assignee_user_ids: list[int] | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    priority: str = "normal",
) -> str:
    """Crea una tarea nueva. priority: low | normal | high. Fechas YYYY-MM-DD."""
    task_data: dict[str, Any] = {
        "tasklistId": tasklist_id,
        "name": name,
        "priority": priority,
    }
    if description:
        task_data["description"] = description
    if assignee_user_ids:
        task_data["assignees"] = {"userIds": assignee_user_ids}
    if start_date:
        task_data["startAt"] = start_date
    if due_date:
        task_data["dueAt"] = due_date

    data = await api_post(
        f"/projects/api/v3/tasklists/{tasklist_id}/tasks.json",
        {"task": task_data},
    )
    t = data.get("task", {})
    return f"Tarea creada: [{t.get('id')}] {t.get('name')}"


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
    """Marca una tarea como completada."""
    await api_put(f"/projects/api/v3/tasks/{task_id}/complete.json", {})
    return f"Tarea {task_id} marcada como completada."


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
async def get_user_workload(user_id: int, completed: bool = False) -> str:
    """Tareas pendientes de un empleado concreto."""
    params = {
        "assignedToUserIds": user_id,
        "includeCompletedTasks": str(completed).lower(),
    }
    data = await api_get("/projects/api/v3/tasks.json", params)
    tasks = data.get("tasks", [])
    if not tasks:
        return f"El usuario {user_id} no tiene tareas pendientes."
    lines = [f"Carga de trabajo del usuario {user_id} ({len(tasks)} tareas):"]
    for t in tasks:
        due = t.get("dueAt") or "sin fecha"
        priority = t.get("priority", "normal")
        lines.append(f"- [{t['id']}] {t.get('name')} | vence: {due} | prioridad: {priority}")
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
