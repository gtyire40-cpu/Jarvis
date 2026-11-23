"""Planificador operativo corto.

Genera solo un resumen de pasos accionables. No expone razonamiento interno.
Si falla, el agente continúa directamente con el LLM principal.
"""
from __future__ import annotations
import json
import config
from core.privacy import is_local_endpoint, ollama_disclosure
from core.ollama_transport import StreamCancelled, iter_json_lines
import requests

SYSTEM = (
    "Eres el planificador de Jarvis. Devuelve JSON válido con una lista 'steps' "
    "de 1 a 5 pasos operativos, breves y verificables. No incluyas razonamiento "
    "interno, explicaciones ni texto fuera del JSON. Si la tarea es simple, usa 1 paso."
)


def make_plan(goal: str, model=None, base_url=None, privacy_callback=None, cancel_event=None) -> list[str]:
    url = (base_url or config.OLLAMA_URL).rstrip("/")
    payload = {
        "model": model or config.MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": goal},
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1},
    }
    if cancel_event is not None and cancel_event.is_set():
        return []
    selected_model = model or config.MODEL
    if not is_local_endpoint(url):
        disclosure = ollama_disclosure(url, selected_model, payload["messages"])
        if privacy_callback is None or not privacy_callback("ollama-planner", url, disclosure):
            return []
    if cancel_event is None:
        r = requests.post(f"{url}/api/chat", json=payload, timeout=min(config.OLLAMA_TIMEOUT, 30))
        r.raise_for_status()
        content = r.json().get("message", {}).get("content", "{}")
    else:
        payload["stream"] = True
        content = ""
        try:
            for chunk in iter_json_lines(
                f"{url}/api/chat",
                payload,
                config.OLLAMA_TIMEOUT,
                cancel_event,
            ):
                content += (chunk.get("message") or {}).get("content", "")
        except StreamCancelled:
            return []
        except requests.RequestException:
            if cancel_event.is_set():
                return []
            raise
    data = json.loads(content)
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [str(x).strip() for x in steps[:5] if str(x).strip()]
