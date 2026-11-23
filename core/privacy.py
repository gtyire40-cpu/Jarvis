"""Disclosure helpers for data that leaves the local machine."""
from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlparse


def is_local_endpoint(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def ollama_disclosure(url: str, model: str, messages: list[dict], tool_schemas=None) -> str:
    payload = {
        "endpoint": url,
        "model": model,
        "messages": messages,
    }
    if tool_schemas is not None:
        payload["tools"] = tool_schemas
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def tool_disclosure(name: str, args: dict) -> tuple[str, str] | None:
    if name == "analizar_pantalla" and args.get("incluir_vision", True):
        import config

        if not is_local_endpoint(config.OLLAMA_URL):
            model = getattr(config, "VISION_MODEL", "") or config.MODEL
            return config.OLLAMA_URL, (
                "Se enviará una captura PNG de toda la pantalla al modelo visual "
                f"{model}. Instrucción adicional: {args.get('prompt', '') or '(ninguna)'}"
            )
    if name == "buscar_en_web":
        return "DuckDuckGo (html.duckduckgo.com)", f"Consulta de búsqueda: {args.get('consulta', '')}"
    if name == "leer_pagina_web":
        return str(args.get("url", "")), f"Se solicitará esta URL: {args.get('url', '')}"
    if name == "abrir_url":
        return str(args.get("url", "")), f"Se abrirá esta dirección en el navegador: {args.get('url', '')}"
    if name == "navegador_abrir":
        return str(args.get("url", "")), f"Se navegará a: {args.get('url', '')}"
    if name == "navegador_atras":
        return "Sitio abierto en el navegador", "Se solicitará cargar la página anterior."
    if name in {"navegador_click_texto", "navegador_click_role"}:
        action = args.get("texto") or f"rol {args.get('rol', '')}, nombre {args.get('nombre', '')}"
        return "Sitio abierto en el navegador", f"Se enviará una interacción de click: {action}"
    if name == "navegador_escribir":
        return "Sitio abierto en el navegador", (
            f"Campo: {args.get('campo', '')}\nContenido que se escribirá: {args.get('texto', '')}"
        )
    if name == "navegador_tecla":
        return "Sitio abierto en el navegador", (
            f"Se enviará la tecla {args.get('tecla', '')}; puede enviar un formulario."
        )
    if name == "enviar_correo":
        from config import EMAIL_ADDRESS, SMTP_PORT, SMTP_SERVER

        return str(args.get("destinatario", "")), (
            f"Servidor SMTP: {SMTP_SERVER}:{SMTP_PORT}\n"
            f"Cuenta autenticada: {EMAIL_ADDRESS} (se usarán sus credenciales)\n"
            f"Destinatario: {args.get('destinatario', '')}\n"
            f"Asunto: {args.get('asunto', '')}\n"
            f"Cuerpo:\n{args.get('cuerpo', '')}"
        )
    if name == "leer_correos":
        from config import EMAIL_ADDRESS, IMAP_PORT, IMAP_SERVER

        return f"{IMAP_SERVER}:{IMAP_PORT}", (
            f"Cuenta autenticada: {EMAIL_ADDRESS} (se usarán sus credenciales). "
            "Se consultarán los metadatos de mensajes no leídos."
        )
    return None
