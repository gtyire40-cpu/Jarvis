"""Configuración central de Jarvis Local."""
import os
from pathlib import Path

def _load_env_file() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists(): return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key, value = [part.strip() for part in line.split("=", 1)]
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))

_load_env_file()

OLLAMA_URL = os.getenv("JARVIS_OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:7b")
VISION_MODEL = os.getenv("JARVIS_VISION_MODEL", MODEL)
OLLAMA_TIMEOUT = float(os.getenv("JARVIS_OLLAMA_TIMEOUT", "120"))
MAX_TOOL_ITERATIONS = int(os.getenv("JARVIS_MAX_TOOL_ITERATIONS", "8"))
TEMPERATURE = float(os.getenv("JARVIS_TEMPERATURE", "0.2"))

WHISPER_MODEL_SIZE = os.getenv("JARVIS_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("JARVIS_WHISPER_DEVICE", "auto")
WHISPER_COMPUTE_TYPE = os.getenv("JARVIS_WHISPER_COMPUTE_TYPE", "auto")

PROJECT_DIR = Path(__file__).resolve().parent
HOME_DIR = os.path.expanduser(os.getenv("JARVIS_HOME_DIR", "~"))
APP_DIR = Path(os.path.expanduser(os.getenv("JARVIS_APP_DIR", str(Path(__file__).resolve().parent))))
DATA_DIR = Path(os.path.expanduser(os.getenv("JARVIS_DATA_DIR", str(APP_DIR / "data"))))
LOGS_DIR = Path(os.path.expanduser(os.getenv("JARVIS_LOGS_DIR", str(APP_DIR / "logs"))))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
MAX_SEARCH_RESULTS = int(os.getenv("JARVIS_MAX_SEARCH_RESULTS", "15"))
MAX_RECOVERY_RETRIES = int(os.getenv("JARVIS_MAX_RECOVERY_RETRIES", "2"))

PIPER_BINARY = os.getenv("JARVIS_PIPER_BINARY", str(PROJECT_DIR / ".venv" / "bin" / "piper"))
PIPER_VOICE_MODEL = os.getenv("JARVIS_PIPER_VOICE", str(APP_DIR / "resources" / "voices" / "es_ES-davefx-medium.onnx"))
PIPER_AUDIO_PLAYER = os.getenv("JARVIS_AUDIO_PLAYER", "auto")

DB_PATH = os.getenv("JARVIS_DB_PATH", str(DATA_DIR / "jarvis_v3_6.db"))
HISTORIAL_MENSAJES_MAX = int(os.getenv("JARVIS_HISTORY_MAX", "40"))
WAKE_WORD_MODEL = os.getenv("JARVIS_WAKE_WORD_MODEL", "hey_jarvis")
WAKE_WORD_THRESHOLD = float(os.getenv("JARVIS_WAKE_WORD_THRESHOLD", "0.5"))
GRABACION_SEGUNDOS = float(os.getenv("JARVIS_RECORD_SECONDS", "6"))
VOICE_MAX_SECONDS = float(os.getenv("JARVIS_VOICE_MAX_SECONDS", "20"))
VOICE_SILENCE_SECONDS = float(os.getenv("JARVIS_VOICE_SILENCE_SECONDS", "1.0"))
VOICE_RMS_THRESHOLD = float(os.getenv("JARVIS_VOICE_RMS_THRESHOLD", "0.015"))
VOICE_BLOCK_MS = int(os.getenv("JARVIS_VOICE_BLOCK_MS", "30"))
VOICE_PRE_ROLL_MS = int(os.getenv("JARVIS_VOICE_PRE_ROLL_MS", "240"))
MEMORY_AUTO_SAVE = os.getenv("JARVIS_MEMORY_AUTO_SAVE", "false").lower() in ("1", "true", "yes", "on")
MEMORY_CONTEXT_RECALL = os.getenv("JARVIS_MEMORY_CONTEXT_RECALL", "true").lower() in ("1", "true", "yes", "on")
MEMORY_CONTEXT_MAX_RECALLS = int(os.getenv("JARVIS_MEMORY_CONTEXT_MAX_RECALLS", "8"))
REMINDER_POLL_SECONDS = float(os.getenv("JARVIS_REMINDER_POLL_SECONDS", "15"))

EMAIL_ADDRESS = os.getenv("JARVIS_EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("JARVIS_EMAIL_PASSWORD", "")
IMAP_SERVER = os.getenv("JARVIS_IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("JARVIS_IMAP_PORT", "993"))
SMTP_SERVER = os.getenv("JARVIS_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("JARVIS_SMTP_PORT", "587"))
MUSIC_PLAYER = os.getenv("JARVIS_MUSIC_PLAYER")
ALLOWED_APPS = {a.strip().lower() for a in os.getenv("JARVIS_ALLOWED_APPS", "firefox,code,nautilus,spotify,steam,gedit,gnome-terminal,gnome-calculator,librewolf,thunderbird,vlc,discord,chrome,chromium,brave").split(",") if a.strip()}

SYSTEM_PROMPT = """Eres Jarvis, un asistente personal local en Linux. Hablas español y eres breve, claro y preciso.

REGLA CRÍTICA DE EJECUCIÓN: nunca inventes comandos, JSON, resultados, capturas, procesos, fechas, archivos ni acciones. Una acción solo cuenta como realizada cuando una herramienta real la ejecuta y su resultado vuelve al agente. No muestres simulaciones de tool-calls ni bloques de output ficticios.

REGLAS CRÍTICAS DE EJECUCIÓN:
- Una herramienta solo se ha ejecutado si recibes un tool_call real y el sistema devuelve su resultado.
- Nunca simules, inventes ni describas como realizado un tool_call que no haya ocurrido.
- Nunca inventes resultados, fechas, horas, procesos, aplicaciones abiertas, rutas, archivos ni estados del sistema.
- Si no tienes un resultado real de herramienta, dilo claramente y no afirmes que la acción se realizó.
- Analiza el resultado de cada herramienta antes de decidir el siguiente paso.
- Si una herramienta devuelve fallo o la verificación falla, trata la acción como NO realizada.
- Las acciones sensibles pueden requerir confirmación; respeta siempre el resultado de seguridad.
- La memoria permanente solo debe modificarse cuando el usuario lo pida explícitamente o indique claramente que quiere que recuerdes algo. No inventes recuerdos.
- Para tareas de varios pasos, ejecuta una herramienta cada vez, verifica su resultado y solo después continúa.
- Si una herramienta falla, explica el error real y, cuando sea razonable, intenta una alternativa segura.

IMPORTANTE: el historial de conversación es contexto, no evidencia de que una herramienta se ejecutó. Solo los resultados de herramientas del turno actual son evidencia de ejecución.
"""

def configure_runtime(model: str | None = None, ollama_url: str | None = None) -> None:
    global MODEL, OLLAMA_URL
    if model and model.strip(): MODEL = model.strip()
    if ollama_url and ollama_url.strip(): OLLAMA_URL = ollama_url.strip().rstrip("/")
