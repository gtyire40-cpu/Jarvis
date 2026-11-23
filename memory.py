"""
Memoria persistente de Jarvis: histórico de conversación y agenda,
guardados en un archivo SQLite local.
"""

import sqlite3
from contextlib import contextmanager

import config


@contextmanager
def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_tool_execution_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ejecuciones_herramientas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id TEXT DEFAULT '',
            herramienta TEXT NOT NULL,
            argumentos TEXT NOT NULL DEFAULT '{}',
            resultado TEXT NOT NULL DEFAULT '{}',
            exito INTEGER NOT NULL DEFAULT 0,
            verificado INTEGER NOT NULL DEFAULT 0,
            creado DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ejecuciones_herramienta ON ejecuciones_herramientas(herramienta)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ejecuciones_creado ON ejecuciones_herramientas(creado)")


def init_db() -> None:
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mensajes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT,
                descripcion TEXT,
                creado DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        _ensure_tool_execution_schema(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS jarvis_meta (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
        row = conn.execute("SELECT valor FROM jarvis_meta WHERE clave='history_version'").fetchone()
        if not row or row[0] != '360':
            # La 3.4.0 puede contener respuestas simuladas de herramientas.
            # Se limpia solo el historial conversacional; recuerdos persistentes se conservan.
            conn.execute("DELETE FROM mensajes")
            conn.execute("INSERT OR REPLACE INTO jarvis_meta (clave, valor) VALUES ('history_version','360')")


# ---------------------------------------------------------------------------
# Historial de conversación
# ---------------------------------------------------------------------------

def guardar_mensaje(role: str, content: str) -> None:
    if role not in ("user", "assistant"):
        return  # no persistimos mensajes de sistema/herramientas, solo la conversación real
    with _conn() as conn:
        conn.execute(
            "INSERT INTO mensajes (role, content) VALUES (?, ?)", (role, content)
        )


def cargar_historial(limite: int = None) -> list:
    limite = limite or config.HISTORIAL_MENSAJES_MAX
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM mensajes ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
    rows.reverse()
    return [{"role": r, "content": c} for r, c in rows]


def borrar_historial() -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM mensajes")


def guardar_ejecucion_herramienta(record: dict) -> None:
    """Persiste evidencia de una llamada real emitida por Ollama y ejecutada por ToolManager."""
    import json
    result = record.get("result") or {}
    verification = ((result.get("data") or {}).get("verification") or {}) if isinstance(result, dict) else {}
    with _conn() as conn:
        _ensure_tool_execution_schema(conn)
        conn.execute(
            """INSERT INTO ejecuciones_herramientas
               (call_id, herramienta, argumentos, resultado, exito, verificado)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(record.get("call_id") or ""),
                str(record.get("tool") or ""),
                json.dumps(record.get("arguments") or {}, ensure_ascii=False, default=str),
                json.dumps(result, ensure_ascii=False, default=str),
                int(bool(result.get("success"))),
                int(bool(verification.get("verified"))),
            ),
        )


def cargar_ejecuciones_herramientas(limite: int = 50) -> list:
    import json
    with _conn() as conn:
        _ensure_tool_execution_schema(conn)
        rows = conn.execute(
            "SELECT call_id, herramienta, argumentos, resultado, exito, verificado, creado "
            "FROM ejecuciones_herramientas ORDER BY id DESC LIMIT ?", (int(limite),)
        ).fetchall()
    rows.reverse()
    out = []
    for call_id, tool, args, result, success, verified, created in rows:
        try: args = json.loads(args)
        except Exception: pass
        try: result = json.loads(result)
        except Exception: pass
        out.append({"call_id": call_id, "tool": tool, "arguments": args, "result": result,
                    "success": bool(success), "verified": bool(verified), "created": created})
    return out


# ---------------------------------------------------------------------------
# Agenda
# ---------------------------------------------------------------------------

def agendar_evento(titulo: str, fecha: str, hora: str = "", descripcion: str = "") -> str:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO eventos (titulo, fecha, hora, descripcion) VALUES (?, ?, ?, ?)",
            (titulo, fecha, hora, descripcion),
        )
    return f"Evento agendado: '{titulo}' el {fecha}" + (f" a las {hora}" if hora else "")


def listar_eventos(fecha: str = None) -> str:
    with _conn() as conn:
        if fecha:
            rows = conn.execute(
                "SELECT titulo, fecha, hora, descripcion FROM eventos WHERE fecha = ? ORDER BY hora",
                (fecha,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT titulo, fecha, hora, descripcion FROM eventos ORDER BY fecha, hora"
            ).fetchall()

    if not rows:
        return "No hay eventos" + (f" para el {fecha}." if fecha else " en la agenda.")

    lineas = []
    for titulo, f, hora, desc in rows:
        linea = f"- {f}" + (f" {hora}" if hora else "") + f": {titulo}"
        if desc:
            linea += f" ({desc})"
        lineas.append(linea)
    return "\n".join(lineas)

# ---------------------------------------------------------------------------
# Memoria semántica local y recordatorios
# ---------------------------------------------------------------------------

def _ensure_extended_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recuerdos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clave TEXT NOT NULL,
            valor TEXT NOT NULL,
            categoria TEXT DEFAULT 'general',
            creado DATETIME DEFAULT CURRENT_TIMESTAMP,
            actualizado DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recuerdos_clave ON recuerdos(clave)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recuerdos_categoria ON recuerdos(categoria)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recordatorios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            texto TEXT NOT NULL,
            cuando TEXT NOT NULL,
            completado INTEGER DEFAULT 0,
            creado DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)


def guardar_recuerdo(clave: str, valor: str, categoria: str = "general") -> str:
    clave = (clave or "").strip()
    valor = (valor or "").strip()
    categoria = (categoria or "general").strip() or "general"
    if not clave or not valor:
        raise ValueError("El recuerdo necesita una clave y un valor.")
    with _conn() as conn:
        _ensure_extended_schema(conn)
        row = conn.execute("SELECT id FROM recuerdos WHERE clave = ?", (clave,)).fetchone()
        if row:
            conn.execute(
                "UPDATE recuerdos SET valor=?, categoria=?, actualizado=CURRENT_TIMESTAMP WHERE id=?",
                (valor, categoria, row[0]),
            )
        else:
            conn.execute(
                "INSERT INTO recuerdos (clave, valor, categoria) VALUES (?, ?, ?)",
                (clave, valor, categoria),
            )
    return f"Recuerdo guardado: {clave}."


def buscar_recuerdos(consulta: str = "", categoria: str = "") -> str:
    consulta = (consulta or "").strip()
    categoria = (categoria or "").strip()
    with _conn() as conn:
        _ensure_extended_schema(conn)
        if consulta and categoria:
            rows = conn.execute(
                "SELECT clave, valor, categoria FROM recuerdos WHERE (clave LIKE ? OR valor LIKE ?) AND categoria = ? ORDER BY actualizado DESC LIMIT 20",
                (f"%{consulta}%", f"%{consulta}%", categoria),
            ).fetchall()
        elif consulta:
            rows = conn.execute(
                "SELECT clave, valor, categoria FROM recuerdos WHERE clave LIKE ? OR valor LIKE ? ORDER BY actualizado DESC LIMIT 20",
                (f"%{consulta}%", f"%{consulta}%"),
            ).fetchall()
        elif categoria:
            rows = conn.execute(
                "SELECT clave, valor, categoria FROM recuerdos WHERE categoria = ? ORDER BY actualizado DESC LIMIT 20",
                (categoria,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT clave, valor, categoria FROM recuerdos ORDER BY actualizado DESC LIMIT 20"
            ).fetchall()
    if not rows:
        return "No encontré recuerdos que coincidan."
    return "Recuerdos:\n" + "\n".join(f"- {k}: {v} [{c}]" for k, v, c in rows)


def borrar_recuerdo(clave: str) -> str:
    clave = (clave or "").strip()
    if not clave:
        raise ValueError("Debes indicar la clave del recuerdo.")
    with _conn() as conn:
        _ensure_extended_schema(conn)
        cur = conn.execute("DELETE FROM recuerdos WHERE clave = ?", (clave,))
    return f"Recuerdo '{clave}' eliminado." if cur.rowcount else f"No encontré el recuerdo '{clave}'."


def crear_recordatorio(texto: str, cuando: str) -> str:
    texto = (texto or "").strip()
    cuando = (cuando or "").strip()
    if not texto or not cuando:
        raise ValueError("El recordatorio necesita texto y fecha/hora.")
    with _conn() as conn:
        _ensure_extended_schema(conn)
        conn.execute("INSERT INTO recordatorios (texto, cuando) VALUES (?, ?)", (texto, cuando))
    return f"Recordatorio creado para {cuando}: {texto}"


def listar_recordatorios(incluir_completados: bool = False) -> str:
    with _conn() as conn:
        _ensure_extended_schema(conn)
        if incluir_completados:
            rows = conn.execute("SELECT id, texto, cuando, completado FROM recordatorios ORDER BY cuando, id").fetchall()
        else:
            rows = conn.execute("SELECT id, texto, cuando, completado FROM recordatorios WHERE completado=0 ORDER BY cuando, id").fetchall()
    if not rows:
        return "No hay recordatorios pendientes."
    return "Recordatorios:\n" + "\n".join(
        f"- #{i} {cuando}: {texto}" + (" [completado]" if done else "")
        for i, texto, cuando, done in rows
    )


def completar_recordatorio(recordatorio_id: int) -> str:
    with _conn() as conn:
        _ensure_extended_schema(conn)
        cur = conn.execute("UPDATE recordatorios SET completado=1 WHERE id=?", (int(recordatorio_id),))
    if not cur.rowcount:
        raise ValueError(f"No existe el recordatorio #{recordatorio_id}.")
    return f"Recordatorio #{recordatorio_id} marcado como completado."


# Asegura que las tablas nuevas existan también para instalaciones ya existentes.
with _conn() as _startup_conn:
    _ensure_extended_schema(_startup_conn)
    _ensure_tool_execution_schema(_startup_conn)

# ---------------------------------------------------------------------------
# Tareas persistentes V3.1
# ---------------------------------------------------------------------------

def _ensure_tasks_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tareas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descripcion TEXT DEFAULT '',
            prioridad INTEGER DEFAULT 2,
            estado TEXT DEFAULT 'pendiente',
            vence TEXT DEFAULT '',
            creado DATETIME DEFAULT CURRENT_TIMESTAMP,
            actualizado DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tareas_estado ON tareas(estado)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tareas_vence ON tareas(vence)")


def crear_tarea(titulo: str, descripcion: str = "", prioridad: int = 2, vence: str = "") -> str:
    titulo = (titulo or "").strip()
    descripcion = (descripcion or "").strip()
    vence = (vence or "").strip()
    prioridad = max(1, min(3, int(prioridad)))
    if not titulo:
        raise ValueError("La tarea necesita un título.")
    with _conn() as conn:
        _ensure_tasks_schema(conn)
        cur = conn.execute(
            "INSERT INTO tareas (titulo, descripcion, prioridad, vence) VALUES (?, ?, ?, ?)",
            (titulo, descripcion, prioridad, vence),
        )
        rid = cur.lastrowid
    return f"Tarea #{rid} creada: {titulo}."


def listar_tareas(estado: str = "pendiente") -> str:
    estado = (estado or "pendiente").strip().lower()
    if estado not in ("pendiente", "en_progreso", "completada", "cancelada", "todas"):
        raise ValueError("Estado no válido. Usa pendiente, en_progreso, completada, cancelada o todas.")
    with _conn() as conn:
        _ensure_tasks_schema(conn)
        if estado == "todas":
            rows = conn.execute(
                "SELECT id, titulo, descripcion, prioridad, estado, vence FROM tareas ORDER BY CASE WHEN vence='' THEN 1 ELSE 0 END, vence, prioridad DESC, id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, titulo, descripcion, prioridad, estado, vence FROM tareas WHERE estado=? ORDER BY CASE WHEN vence='' THEN 1 ELSE 0 END, vence, prioridad DESC, id",
                (estado,),
            ).fetchall()
    if not rows:
        return f"No hay tareas en estado '{estado}'."
    prioridad = {1: "baja", 2: "media", 3: "alta"}
    lines = []
    for rid, titulo, desc, prio, state, vence in rows:
        line = f"- #{rid} [{state}] [{prioridad.get(prio, 'media')}] {titulo}"
        if vence:
            line += f" | vence: {vence}"
        if desc:
            line += f" | {desc}"
        lines.append(line)
    return "Tareas:\n" + "\n".join(lines)


def actualizar_tarea(tarea_id: int, estado: str = "", prioridad: int = 0, titulo: str = "", descripcion: str = "", vence: str = "") -> str:
    tarea_id = int(tarea_id)
    estado = (estado or "").strip().lower()
    titulo = (titulo or "").strip()
    descripcion = (descripcion or "").strip()
    vence = (vence or "").strip()
    if estado and estado not in ("pendiente", "en_progreso", "completada", "cancelada"):
        raise ValueError("Estado no válido.")
    if prioridad:
        prioridad = max(1, min(3, int(prioridad)))
    with _conn() as conn:
        _ensure_tasks_schema(conn)
        row = conn.execute("SELECT titulo, descripcion, prioridad, estado, vence FROM tareas WHERE id=?", (tarea_id,)).fetchone()
        if not row:
            raise ValueError(f"No existe la tarea #{tarea_id}.")
        ntitulo = titulo or row[0]
        ndesc = descripcion if descripcion else row[1]
        nprio = prioridad or row[2]
        nestado = estado or row[3]
        nvence = vence if vence else row[4]
        conn.execute(
            "UPDATE tareas SET titulo=?, descripcion=?, prioridad=?, estado=?, vence=?, actualizado=CURRENT_TIMESTAMP WHERE id=?",
            (ntitulo, ndesc, nprio, nestado, nvence, tarea_id),
        )
    return f"Tarea #{tarea_id} actualizada."


def completar_tarea(tarea_id: int) -> str:
    actualizar_tarea(tarea_id, estado="completada")
    return f"Tarea #{int(tarea_id)} marcada como completada."


def cancelar_tarea(tarea_id: int) -> str:
    actualizar_tarea(tarea_id, estado="cancelada")
    return f"Tarea #{int(tarea_id)} cancelada."


def contexto_relevante(consulta: str, max_recuerdos: int = 8, max_tareas: int = 8, max_mensajes: int = 4) -> dict:
    """Devuelve contexto persistente relevante sin modificar memoria."""
    consulta = (consulta or "").strip().lower()
    palabras = [p for p in consulta.replace("¿", " ").replace("?", " ").replace(",", " ").split() if len(p) >= 3]
    with _conn() as conn:
        _ensure_extended_schema(conn)
        _ensure_tasks_schema(conn)
        recuerdos = []
        rows = conn.execute(
            "SELECT clave, valor, categoria FROM recuerdos ORDER BY actualizado DESC LIMIT 50"
        ).fetchall()
        for clave, valor, categoria in rows:
            hay = (clave + " " + valor + " " + categoria).lower()
            score = sum(1 for p in palabras if p in hay)
            if score or not palabras:
                recuerdos.append({"clave": clave, "valor": valor, "categoria": categoria, "score": score})
        recuerdos.sort(key=lambda x: (x["score"], x["categoria"] != "general"), reverse=True)
        recuerdos = recuerdos[:max_recuerdos]

        tareas = conn.execute(
            "SELECT id, titulo, descripcion, prioridad, estado, vence FROM tareas WHERE estado IN ('pendiente','en_progreso') ORDER BY prioridad DESC, CASE WHEN vence='' THEN 1 ELSE 0 END, vence, id LIMIT ?",
            (max_tareas,),
        ).fetchall()
        tareas_out = [
            {"id": i, "titulo": t, "descripcion": d, "prioridad": p, "estado": s, "vence": v}
            for i, t, d, p, s, v in tareas
        ]

        mensajes = conn.execute(
            "SELECT role, content, timestamp FROM mensajes ORDER BY id DESC LIMIT ?", (max_mensajes,)
        ).fetchall()
    mensajes.reverse()
    return {
        "recuerdos": recuerdos,
        "tareas_pendientes": tareas_out,
        "mensajes_recientes": [{"role": r, "content": c, "timestamp": ts} for r, c, ts in mensajes],
    }


with _conn() as _startup_conn:
    _ensure_tasks_schema(_startup_conn)
