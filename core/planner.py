"""Planificador operativo corto.

Genera solo un resumen de pasos accionables. No expone razonamiento interno.
Si falla, el agente continúa directamente con el LLM principal.
"""
from __future__ import annotations
import json
import requests
import config

SYSTEM = (
    "Eres el planificador de Jarvis. Devuelve JSON válido con una lista 'steps' "
    "de 1 a 5 pasos operativos, breves y verificables. No incluyas razonamiento "
    "interno, explicaciones ni texto fuera del JSON. Si la tarea es simple, usa 1 paso."
)


def make_plan(goal: str, model=None, base_url=None) -> list[str]:
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
    r = requests.post(f"{url}/api/chat", json=payload, timeout=min(config.OLLAMA_TIMEOUT, 30))
    r.raise_for_status()
    content = r.json().get("message", {}).get("content", "{}")
    data = json.loads(content)
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [str(x).strip() for x in steps[:5] if str(x).strip()]
