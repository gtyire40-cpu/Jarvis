"""Servicio ligero de recordatorios locales.

No ejecuta comandos arbitrarios: únicamente muestra una notificación cuando
llega la hora de un recordatorio persistido en SQLite.
"""
import logging
import shutil
import subprocess
import threading
import time
from datetime import datetime

import config
import memory

logger = logging.getLogger(__name__)

_running = False
_thread = None


def _parse_when(value: str):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _notify(texto):
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", "Jarvis", texto], check=False, timeout=3)
            return
        except Exception:
            logger.exception("No pude mostrar la notificación")
    print(f"\nRecordatorio JARVIS — Recordatorio: {texto}\n")


def _loop():
    global _running
    while _running:
        try:
            now = datetime.now()
            with memory._conn() as conn:
                memory._ensure_extended_schema(conn)
                rows = conn.execute(
                    "SELECT id, texto, cuando FROM recordatorios WHERE completado=0 ORDER BY id"
                ).fetchall()
                for rid, texto, cuando in rows:
                    due = _parse_when(cuando)
                    if due and due <= now:
                        _notify(texto)
                        conn.execute("UPDATE recordatorios SET completado=1 WHERE id=?", (rid,))
        except Exception:
            logger.exception("Error en el servicio de recordatorios")
        time.sleep(max(2.0, config.REMINDER_POLL_SECONDS))


def start():
    global _running, _thread
    if _running:
        return
    memory.init_db()
    _running = True
    _thread = threading.Thread(target=_loop, name="jarvis-reminders", daemon=True)
    _thread.start()
    logger.info("Servicio de recordatorios iniciado")


def stop():
    global _running
    _running = False
