from core.security import SecurityManager
import json
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest

import config
import llm
import tts
import tools
from core import ollama_transport
from core.planner import make_plan
from core.privacy import is_local_endpoint, ollama_disclosure, tool_disclosure
from core.tool_manager import ToolManager
from core.verifier import Verifier


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


def test_desktop_menu_applications_are_discovered_and_filtered(monkeypatch, tmp_path):
    applications = tmp_path / "applications"
    applications.mkdir()
    (applications / "sample.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Sample Editor\n"
        "Name[es]=Editor de prueba\n"
        "Exec=/usr/bin/sample-editor %U\n"
        "Icon=sample-editor\n",
        encoding="utf-8",
    )
    (applications / "hidden.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Hidden App\nExec=hidden-app\nNoDisplay=true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tools, "_application_dirs", lambda: [applications])

    discovered = tools._installed_applications()
    assert [app["name"] for app in discovered] == ["Editor de prueba"]
    assert tools.listar_aplicaciones_permitidas("editor") == "Aplicaciones gráficas instaladas: Editor de prueba"
    assert tools._find_application("sample editor")["id"] == "sample"


def test_any_discovered_desktop_app_can_launch_without_allowlist(monkeypatch, tmp_path):
    applications = tmp_path / "applications"
    applications.mkdir()
    (applications / "unlisted.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Unlisted App\n"
        "Exec=/usr/bin/unlisted-app --title=%c %U\n",
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(tools, "_application_dirs", lambda: [applications])
    monkeypatch.setattr(tools.shutil, "which", lambda _name: None)
    monkeypatch.setattr(tools.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(config, "ALLOWED_APPS", set())

    result = tools.abrir_aplicacion("Unlisted App")
    assert result == "He iniciado Unlisted App."
    assert calls[0][0] == ["/usr/bin/unlisted-app", "--title=Unlisted App"]
    assert "shell" not in calls[0][1]


def test_flatpak_apps_are_checked_and_closed_by_exact_app_id(monkeypatch, tmp_path):
    applications = tmp_path / "applications"
    applications.mkdir()
    (applications / "com.example.Editor.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Example Editor\n"
        "Exec=flatpak run --branch=stable --arch=x86_64 com.example.Editor\n",
        encoding="utf-8",
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "Application\ncom.example.Editor\n", "")

    monkeypatch.setattr(tools, "_application_dirs", lambda: [applications])
    monkeypatch.setattr(tools.shutil, "which", lambda name: "/usr/bin/flatpak" if name == "flatpak" else None)
    monkeypatch.setattr(tools.subprocess, "run", fake_run)

    app = tools._find_application("com.example.Editor")
    assert app["flatpak_id"] == "com.example.Editor"
    assert "está ejecutándose" in tools.comprobar_aplicacion("Example Editor")
    assert tools.cerrar_aplicacion("Example Editor") == "Solicitud de cierre enviada a Example Editor."
    assert calls == [
        ["/usr/bin/flatpak", "ps", "--columns=application"],
        ["/usr/bin/flatpak", "kill", "com.example.Editor"],
    ]


@pytest.mark.parametrize("fetch_data", [None, [], [None], [(b"metadata", 123)]])
def test_email_reader_reports_missing_or_invalid_message_payload(monkeypatch, fetch_data):
    class FakeIMAP:
        def __init__(self, *_args, **_kwargs):
            pass

        def login(self, *_args):
            pass

        def select(self, *_args):
            return "OK", []

        def search(self, *_args):
            return "OK", [b"42"]

        def fetch(self, *_args):
            return "OK", fetch_data

        def logout(self):
            pass

    monkeypatch.setattr(config, "EMAIL_ADDRESS", "user@example.test")
    monkeypatch.setattr(config, "EMAIL_PASSWORD", "test-password")
    monkeypatch.setattr(tools.imaplib, "IMAP4_SSL", FakeIMAP)

    with pytest.raises(RuntimeError, match="formato inesperado"):
        tools.leer_correos()


def test_wakeword_reports_missing_optional_model_dependency(monkeypatch):
    import wakeword

    monkeypatch.setattr(wakeword, "_model", None)
    monkeypatch.setattr(wakeword, "_ModelFactory", None)

    with pytest.raises(RuntimeError, match="requiere openwakeword"):
        wakeword._get_model()


def test_application_launch_verifier_recognizes_new_status_text(monkeypatch):
    class Result:
        success = True
        data = None

    monkeypatch.setattr(tools, "comprobar_aplicacion", lambda _name: "Editor está instalada y está ejecutándose.")
    verification = Verifier().verify("abrir_aplicacion", {"nombre": "Editor"}, Result())
    assert verification.verified


def test_desktop_exec_field_codes_do_not_become_shell_commands():
    application = {
        "name": "Editor",
        "exec": "/usr/bin/editor --label=%c %U --literal=%%",
        "path": "/apps/editor.desktop",
        "icon": "editor",
    }
    assert tools._desktop_exec_argv(application) == [
        "/usr/bin/editor",
        "--label=Editor",
        "--literal=%",
    ]


def test_arbitrary_shell_text_is_not_accepted_as_application(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "_application_dirs", lambda: [tmp_path])
    monkeypatch.setattr(config, "ALLOWED_APPS", set())
    with pytest.raises(FileNotFoundError):
        tools._find_application("sh -c 'touch /tmp/not-an-app'")
