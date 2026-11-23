from core.security import SecurityManager
import json
import subprocess
import threading

import pytest

import config
import llm
import tts
import tools
from core import ollama_transport
from core.planner import make_plan
from core.privacy import is_local_endpoint, ollama_disclosure, tool_disclosure
from core.tool_manager import ToolManager


def test_dispatch_schema_and_policy_are_consistent():
    dispatch = set(tools.DISPATCH)
    schemas = {schema["function"]["name"] for schema in tools.TOOL_SCHEMAS}
    policies = set(SecurityManager().policies)

    assert dispatch == schemas
    assert dispatch == policies


def test_every_tool_belongs_to_exactly_one_group():
    grouped = [name for names in tools.TOOL_GROUPS.values() for name in names]
    assert set(grouped) == set(tools.DISPATCH)
    assert len(grouped) == len(set(grouped))
    assert set(tools.TOOL_GROUPS) == set(tools.TOOL_GROUP_LABELS)


def test_disabled_group_hides_schemas_and_blocks_execution(monkeypatch):
    manager = ToolManager(enabled_tool_groups={"email"})
    exposed = {schema["function"]["name"] for schema in manager.schemas}
    assert "enviar_correo" in exposed
    assert "leer_archivo" not in exposed

    def unexpected_call(**_kwargs):
        pytest.fail("No debe ejecutarse una herramienta de un grupo desactivado.")

    monkeypatch.setitem(tools.DISPATCH, "leer_archivo", unexpected_call)
    result = manager.execute("leer_archivo", {"ruta": "/tmp/test"})
    assert not result.success
    assert "desactivado" in result.error


def test_privacy_denial_blocks_external_tool(monkeypatch):
    prompt = {}
    manager = ToolManager(
        enabled_tool_groups={"web"},
        privacy_callback=lambda name, destination, disclosure: prompt.update(
            name=name, destination=destination, disclosure=disclosure,
        ) or False,
    )

    def unexpected_call(**_kwargs):
        pytest.fail("La herramienta externa no debe ejecutarse sin consentimiento.")

    monkeypatch.setitem(tools.DISPATCH, "buscar_en_web", unexpected_call)
    result = manager.execute("buscar_en_web", {"consulta": "consulta privada"})
    assert not result.success
    assert "no autorizado" in result.error
    assert prompt["name"] == "buscar_en_web"
    assert "consulta privada" in prompt["disclosure"]


def test_cancelled_manager_does_not_start_a_tool(monkeypatch):
    manager = ToolManager(enabled_tool_groups={"desktop"})
    manager.cancel_event = threading.Event()
    manager.cancel_event.set()

    def unexpected_call(**_kwargs):
        pytest.fail("No debe empezar una herramienta tras la cancelación.")

    monkeypatch.setitem(tools.DISPATCH, "obtener_fecha_hora", unexpected_call)
    result = manager.execute("obtener_fecha_hora")
    assert not result.success
    assert "cancelada" in result.error


def test_empty_schema_list_is_sent_as_empty(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "ok"}}

    captured = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm._call_ollama([], base_url="http://localhost:11434", tool_schemas=[])
    assert captured["json"]["tools"] == []


def test_cancelled_stream_does_not_contact_ollama(monkeypatch):
    manager = ToolManager()
    cancelled = threading.Event()
    cancelled.set()

    def unexpected_request(*_args, **_kwargs):
        pytest.fail("No debe iniciarse una petición tras la cancelación.")

    monkeypatch.setattr(llm, "_call_ollama_stream", unexpected_request)
    chunks = list(llm.chat_stream(
        [{"role": "user", "content": "hola"}],
        tool_manager=manager,
        cancel_event=cancelled,
    ))
    assert len(chunks) == 1
    assert "cancelada" in chunks[0].lower()
    assert manager.last_run["cancelled"]


def test_remote_ollama_disclosure_includes_filtered_tool_schemas():
    captured = {}
    manager = ToolManager(enabled_tool_groups={"email"})
    manager.privacy_callback = lambda name, destination, disclosure: captured.update(
        name=name, destination=destination, disclosure=disclosure,
    ) or False
    approved = llm._approve_ollama_request(
        manager,
        [{"role": "user", "content": "dato"}],
        "modelo",
        "https://ollama.example",
    )
    assert not approved
    disclosure = json.loads(captured["disclosure"])
    assert disclosure["endpoint"] == "https://ollama.example"
    assert captured["name"] == "ollama"
    assert {schema["function"]["name"] for schema in disclosure["tools"]} == {
        schema["function"]["name"] for schema in manager.schemas
    }


def test_remote_planner_requires_consent_before_request(monkeypatch):
    seen = {}

    def unexpected_request(*_args, **_kwargs):
        pytest.fail("No debe enviarse el objetivo sin consentimiento.")

    monkeypatch.setattr("core.planner.requests.post", unexpected_request)
    steps = make_plan(
        "Una tarea que requiere varios pasos",
        base_url="https://ollama.example",
        privacy_callback=lambda name, destination, disclosure: seen.update(
            name=name, destination=destination, disclosure=disclosure,
        ) or False,
    )
    assert steps == []
    assert seen["name"] == "ollama-planner"
    assert seen["destination"] == "https://ollama.example"
    assert "Una tarea que requiere varios pasos" in seen["disclosure"]


def test_non_loopback_ollama_and_remote_screen_capture_require_disclosure(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://jarvis.local:11434")
    monkeypatch.setattr(config, "VISION_MODEL", "vision-model")
    assert not is_local_endpoint(config.OLLAMA_URL)
    disclosure = tool_disclosure("analizar_pantalla", {"prompt": "Describe el panel"})
    assert disclosure is not None
    destination, details = disclosure
    assert destination == config.OLLAMA_URL
    assert "captura PNG de toda la pantalla" in details
    assert "vision-model" in details
    assert tool_disclosure("analizar_pantalla", {"incluir_vision": False}) is None


def test_stream_transport_decodes_json_and_closes_response(monkeypatch):
    class Response:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def raise_for_status(self):
            pass

        def iter_lines(self):
            yield b'{"message":{"content":"ok"}}'

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(ollama_transport.requests, "post", lambda *_args, **_kwargs: response)
    chunks = list(ollama_transport.iter_json_lines("http://localhost", {}, 5))
    assert chunks == [{"message": {"content": "ok"}}]
    assert response.closed


def test_stream_transport_closes_active_response_on_cancel(monkeypatch):
    class Response:
        def __init__(self):
            self.started = threading.Event()
            self.release = threading.Event()
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def raise_for_status(self):
            pass

        def iter_lines(self):
            self.started.set()
            self.release.wait(5)
            yield b'{"message":{"content":"late"}}'

        def close(self):
            self.closed = True
            self.release.set()

    response = Response()
    cancelled = threading.Event()
    monkeypatch.setattr(ollama_transport.requests, "post", lambda *_args, **_kwargs: response)
    canceller = threading.Thread(
        target=lambda: (response.started.wait(2), cancelled.set()),
        daemon=True,
    )
    canceller.start()
    with pytest.raises(ollama_transport.StreamCancelled):
        list(ollama_transport.iter_json_lines("http://localhost", {}, 5, cancelled))
    canceller.join(timeout=2)
    assert response.closed


def test_tts_cancellation_terminates_voice_synthesis(monkeypatch):
    cancelled = threading.Event()

    class Process:
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def communicate(self, input=None, timeout=None):
            if self.terminated:
                self.returncode = -15
                return b"", b""
            cancelled.set()
            raise subprocess.TimeoutExpired("piper", timeout)

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    process = Process()
    monkeypatch.setattr(tts, "_find_model", lambda: "model")
    monkeypatch.setattr(tts, "_find_piper", lambda: "piper")
    monkeypatch.setattr(tts.subprocess, "Popen", lambda *_args, **_kwargs: process)

    assert tts.hablar("respuesta", cancel_event=cancelled) is None
    assert process.terminated
