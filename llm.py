"""Cliente Ollama con tool-calling, trazabilidad y ejecución segura."""
import json
import logging
import requests
import config
import tools
from core.tool_manager import ToolManager
from core.intent_router import route
from core.privacy import is_local_endpoint, ollama_disclosure
from core.ollama_transport import StreamCancelled, iter_json_lines

logger = logging.getLogger(__name__)

class OperationCancelled(Exception):
    pass


def _call_ollama(messages, model=None, base_url=None, tool_schemas=None):
    url = (base_url or config.OLLAMA_URL).rstrip("/")
    payload = {"model": model or config.MODEL, "messages": messages, "tools": tools.TOOL_SCHEMAS if tool_schemas is None else tool_schemas, "stream": False, "options": {"temperature": float(getattr(config, "TEMPERATURE", 0.2))}}
    try:
        r = requests.post(f"{url}/api/chat", json=payload, timeout=config.OLLAMA_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"No pude contactar con Ollama: {exc}") from exc


def _call_ollama_stream(messages, model=None, base_url=None, tool_schemas=None, cancel_event=None):
    url = (base_url or config.OLLAMA_URL).rstrip("/")
    payload = {"model": model or config.MODEL, "messages": messages, "tools": tools.TOOL_SCHEMAS if tool_schemas is None else tool_schemas, "stream": True, "options": {"temperature": float(getattr(config, "TEMPERATURE", 0.2))}}
    try:
        yield from iter_json_lines(
            f"{url}/api/chat",
            payload,
            config.OLLAMA_TIMEOUT,
            cancel_event,
        )
    except StreamCancelled as exc:
        raise OperationCancelled from exc
    except requests.RequestException as exc:
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelled from exc
        raise RuntimeError(f"No pude contactar con Ollama: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama devolvió JSON inválido durante el streaming: {exc}") from exc


def _normalise_args(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _reset_run(manager):
    manager.last_run = {"tool_calls": [], "tool_results": [], "tool_call_count": 0}


def _approve_ollama_request(manager, messages, model, base_url):
    url = (base_url or config.OLLAMA_URL).rstrip("/")
    if is_local_endpoint(url):
        return True
    details = ollama_disclosure(url, model or config.MODEL, messages, manager.schemas)
    return manager.approve_external("ollama", url, details)


def _cancelled_response(manager):
    message = "Operación cancelada. La herramienta que ya estaba ejecutándose pudo terminar antes de detenerse."
    manager.last_run["cancelled"] = True
    manager.last_run["final_response"] = message
    return message


def _execute_tool_calls(messages, tool_calls, manager):
    """Ejecuta únicamente llamadas que Ollama haya emitido realmente."""
    for call in tool_calls or []:
        fn = call.get("function", {}) or {}
        call_id = call.get("id") or call.get("call_id") or ""
        name = fn.get("name", "")
        args = _normalise_args(fn.get("arguments", {}))
        if args is None:
            result = {"success": False, "tool": name, "error": "Argumentos JSON inválidos."}
        else:
            result_obj = manager.execute(name, args)
            result = result_obj.to_dict()

        record = {
            "call_id": call_id,
            "tool": name,
            "arguments": args,
            "result": result,
        }
        manager.last_run["tool_calls"].append({"call_id": call_id, "tool": name, "arguments": args})
        manager.last_run["tool_results"].append(record)
        manager.last_run["tool_call_count"] += 1

        # Ollama trabaja con mensajes role=tool; no añadimos campos OpenAI que
        # Algunos servidores Ollama no necesitan campos adicionales de OpenAI.
        messages.append({
            "role": "tool",
            "content": json.dumps(result, ensure_ascii=False, default=str),
        })


def _looks_like_fake_tool_output(text: str) -> bool:
    t=(text or '').lower()
    markers=('"name": "buscar_en_web"', '"name": "obtener_proceso"', '```output', 'ejecutando la búsqueda', 'ejecutando el comando', 'se ha realizado una captura', '/path/to/screenshot', 'resultado de la herramienta', 'he ejecutado el comando', 'he abierto', 'he escrito', 'he creado', 'he cerrado')
    return any(m in t for m in markers)

def chat(messages, tool_manager=None, model=None, base_url=None):
    manager = tool_manager or ToolManager()
    _reset_run(manager)
    routed = route(messages[-1].get("content", "") if messages else "", manager)
    if routed is not None:
        manager.last_run["final_response"] = routed
        return routed
    try:
        for _ in range(config.MAX_TOOL_ITERATIONS):
            if not _approve_ollama_request(manager, messages, model, base_url):
                return "Envío a Ollama cancelado: no se autorizó el envío de la conversación."
            data = _call_ollama(messages, model, base_url, manager.schemas)
            message = data.get("message", {}) or {}
            tool_calls = message.get("tool_calls") or []
            messages.append(message)
            if not tool_calls:
                final = message.get("content", "").strip()
                if _looks_like_fake_tool_output(final):
                    final = "No puedo confirmar esa acción porque no se ejecutó ninguna herramienta real."
                manager.last_run["final_response"] = final
                return final
            _execute_tool_calls(messages, tool_calls, manager)
        return "He alcanzado el límite de pasos de esta tarea sin poder completarla de forma segura."
    except RuntimeError as exc:
        logger.exception("Conversación con Ollama falló")
        manager.last_run["error"] = str(exc)
        return str(exc)


def chat_stream(messages, tool_manager=None, model=None, base_url=None, cancel_event=None):
    """Streaming seguro: no publica contenido de un turno hasta saber si era un tool_call."""
    manager = tool_manager or ToolManager()
    _reset_run(manager)
    manager.cancel_event = cancel_event
    if cancel_event is not None and cancel_event.is_set():
        yield _cancelled_response(manager)
        return
    routed = route(messages[-1].get("content", "") if messages else "", manager)
    if routed is not None:
        manager.last_run["final_response"] = routed
        if cancel_event is not None and cancel_event.is_set():
            yield _cancelled_response(manager)
            return
        yield routed
        return
    try:
        for _ in range(config.MAX_TOOL_ITERATIONS):
            if cancel_event is not None and cancel_event.is_set():
                yield _cancelled_response(manager)
                return
            if not _approve_ollama_request(manager, messages, model, base_url):
                message = "Envío a Ollama cancelado: no se autorizó el envío de la conversación."
                manager.last_run["final_response"] = message
                yield message
                return
            content = ""
            tool_calls = None
            final_message = None

            stream = _call_ollama_stream(messages, model, base_url, manager.schemas, cancel_event)
            try:
                for chunk in stream:
                    if cancel_event is not None and cancel_event.is_set():
                        yield _cancelled_response(manager)
                        return
                    msg = chunk.get("message", {}) or {}
                    if msg.get("tool_calls"):
                        tool_calls = msg["tool_calls"]
                        # Si el modelo produjo texto antes del tool_call, se descarta:
                        # no debe llegar al usuario como si fuera una acción ya realizada.
                        final_message = {"role": "assistant", "content": "", "tool_calls": tool_calls}
                        break
                    part = msg.get("content", "")
                    if part:
                        content += part
                    if chunk.get("done"):
                        final_message = {"role": "assistant", "content": content}
            finally:
                stream.close()

            if cancel_event is not None and cancel_event.is_set():
                yield _cancelled_response(manager)
                return
            if final_message is None:
                final_message = {"role": "assistant", "content": content}

            messages.append(final_message)
            if not tool_calls:
                final = content.strip()
                if _looks_like_fake_tool_output(final):
                    final = "No puedo confirmar esa acción porque no se ejecutó ninguna herramienta real."
                manager.last_run["final_response"] = final
                if final:
                    yield final
                return

            _execute_tool_calls(messages, tool_calls, manager)
            if cancel_event is not None and cancel_event.is_set():
                yield _cancelled_response(manager)
                return

        limit_message = "He alcanzado el límite de pasos de esta tarea sin poder completarla de forma segura."
        manager.last_run["final_response"] = limit_message
        yield limit_message

    except OperationCancelled:
        yield _cancelled_response(manager)
    except RuntimeError as exc:
        logger.exception("Streaming de Ollama falló")
        manager.last_run["error"] = str(exc)
        yield str(exc)
