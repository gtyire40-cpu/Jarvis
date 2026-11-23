#!/usr/bin/env python3
"""Primer arranque de Jarvis: prepara entorno, voz y abre la GUI."""
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / "bin" / "python"
STAMP = VENV / ".jarvis_deps_ok"
LOG = Path.home() / ".jarvis" / "bootstrap.log"
VOICE_DIR = ROOT / "resources" / "voices"
VOICE_NAME = "es_ES-davefx-medium.onnx"
VOICE_META = VOICE_NAME + ".json"
VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/"
LOG.parent.mkdir(parents=True, exist_ok=True)

STEPS = [("env", "Entorno Python"), ("deps", "Componentes"), ("voice", "Voz en español"), ("check", "Verificación")]

# Paleta compartida con gui.py.
BG = "#060a12"; CARD = "#0d1522"; BORDER = "#20314a"
TEXT = "#edf5ff"; MUTED = "#71839f"; DIM = "#33455f"
ACCENT = "#4da8ff"; CYAN = "#39e6ff"; SUCCESS = "#59e0a2"; DANGER = "#ff667d"


class UI:
    """Splash de primer arranque con estética HUD, checklist de pasos y
    animación continua, alineado visualmente con la app principal."""

    def __init__(self):
        self.root: Any = None
        self.canvas: Any = None
        self.label: int | None = None
        self.detail: int | None = None
        self.arc: int | None = None
        self.phase = 0
        self.step_dots: dict[str, int] = {}
        self.step_labels: dict[str, int] = {}
        self.bar: int | None = None
        self.bar_w = 0
        try:
            import tkinter as tk
            self.tk = tk
            W, H = 640, 400
            self.root = tk.Tk(); self.root.title("JARVIS LOCAL — INSTALACIÓN"); self.root.geometry(f"{W}x{H}"); self.root.resizable(False, False); self.root.configure(bg=BG)
            self.root.protocol("WM_DELETE_WINDOW", lambda: None)
            self.canvas = tk.Canvas(self.root, width=W, height=H, bg=BG, highlightthickness=0); self.canvas.pack(fill="both", expand=True)

            # tarjeta redondeada de fondo
            self._round_rect(18, 18, W - 18, H - 18, 22, fill=CARD, outline=BORDER, width=1)

            cx = W / 2
            self.canvas.create_text(cx, 54, text="J A R V I S", fill=TEXT, font=("Segoe UI", 22, "bold"))
            self.canvas.create_text(cx, 78, text="LOCAL INTELLIGENCE SYSTEM", fill=MUTED, font=("Consolas", 8, "bold"))

            ring_cy = 170
            self.canvas.create_oval(cx - 100, ring_cy - 100, cx + 100, ring_cy + 100, outline="#122640", width=1)
            self.canvas.create_oval(cx - 84, ring_cy - 84, cx + 84, ring_cy + 84, outline="#17466a", width=2)
            self.canvas.create_oval(cx - 62, ring_cy - 62, cx + 62, ring_cy + 62, outline="#0e789b", width=1)
            self.canvas.create_oval(cx - 28, ring_cy - 28, cx + 28, ring_cy + 28, outline=CYAN, width=2)
            self.canvas.create_oval(cx - 12, ring_cy - 12, cx + 12, ring_cy + 12, outline="#a9f3ff", width=2)
            self.arc = self.canvas.create_arc(cx - 92, ring_cy - 92, cx + 92, ring_cy + 92, start=0, extent=42, style="arc", outline=CYAN, width=3)

            self.label = self.canvas.create_text(cx, 288, text="Inicializando…", fill=TEXT, font=("Segoe UI", 11, "bold"))
            self.detail = self.canvas.create_text(cx, 306, text="", fill=MUTED, font=("Consolas", 8))

            # barra de progreso
            bar_x0, bar_x1, bar_y = 60, W - 60, 322
            self.canvas.create_line(bar_x0, bar_y, bar_x1, bar_y, fill=BORDER, width=4, capstyle="round")
            self.bar_x0, self.bar_x1, self.bar_y = bar_x0, bar_x1, bar_y
            self.bar = self.canvas.create_line(bar_x0, bar_y, bar_x0, bar_y, fill=ACCENT, width=4, capstyle="round")

            # checklist de pasos
            step_y = 350; gap = (W - 100) / (len(STEPS) - 1)
            for i, (key, label) in enumerate(STEPS):
                sx = 50 + gap * i
                dot = self.canvas.create_oval(sx - 4, step_y - 4, sx + 4, step_y + 4, fill=DIM, outline="")
                txt = self.canvas.create_text(sx, step_y + 16, text=label, fill=DIM, font=("Segoe UI", 7, "bold"))
                self.step_dots[key] = dot; self.step_labels[key] = txt

            self._animate(); self.root.update_idletasks(); self.root.update()
        except Exception:
            self.root = None

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        canvas = self.canvas
        if canvas is not None:
            canvas.create_polygon(pts, smooth=True, **kw)

    def _animate(self):
        root = self.root
        canvas = self.canvas
        arc = self.arc
        if root is None or canvas is None or arc is None:
            return
        self.phase = (self.phase + 8) % 360
        canvas.itemconfigure(arc, start=self.phase)
        root.after(55, self._animate)

    def step(self, key, state="active"):
        """Marca un paso del checklist como activo/completado/error."""
        root = self.root
        canvas = self.canvas
        dot = self.step_dots.get(key)
        label = self.step_labels.get(key)
        bar = self.bar
        if root is None or canvas is None or dot is None or label is None or bar is None:
            return
        color = {"active": ACCENT, "done": SUCCESS, "error": DANGER}.get(state, DIM)
        canvas.itemconfigure(dot, fill=color)
        canvas.itemconfigure(label, fill=(TEXT if state != "pending" else DIM))
        done_count = sum(
            1 for step_id in self.step_dots.values()
            if canvas.itemcget(step_id, "fill") == SUCCESS
        )
        progress = (done_count + (0.5 if state == "active" else 0)) / len(STEPS)
        x = self.bar_x0 + (self.bar_x1 - self.bar_x0) * min(1.0, progress)
        canvas.coords(bar, self.bar_x0, self.bar_y, x, self.bar_y)
        root.update_idletasks(); root.update()

    def set(self, text, detail=""):
        root = self.root
        canvas = self.canvas
        label = self.label
        detail_id = self.detail
        if root is not None and canvas is not None and label is not None and detail_id is not None:
            canvas.itemconfigure(label, text=text)
            canvas.itemconfigure(detail_id, text=detail)
            root.update_idletasks()
            root.update()
        else: notify("Jarvis Local", text, False)
        log(f"STATUS: {text} {detail}")

    def error(self, text):
        root = self.root
        canvas = self.canvas
        label = self.label
        detail_id = self.detail
        bar = self.bar
        if root is not None and canvas is not None and label is not None and detail_id is not None and bar is not None:
            canvas.itemconfigure(label, text="No se pudo preparar Jarvis", fill=DANGER)
            canvas.itemconfigure(detail_id, text=text, fill="#ff9aaa")
            canvas.itemconfigure(bar, fill=DANGER)
            root.update_idletasks()
            root.update()
            time.sleep(3)
            root.destroy()
        notify("Jarvis Local", text, True)

def log(text):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")

def notify(title, msg, critical=False):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-u", "critical" if critical else "normal", title, msg], check=False)

def run(cmd, ui, label, detail=""):
    ui.set(label, detail)
    log("$ " + " ".join(map(str, cmd)))
    with LOG.open("a", encoding="utf-8") as f:
        p = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, text=True)
    if p.returncode:
        raise RuntimeError(f"El comando terminó con código {p.returncode}. Consulta {LOG}")

def ensure_python(ui):
    if PY.exists():
        try:
            result = subprocess.run(
                [str(PY), "-c", "import encodings, sys; print(sys.version)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
        ui.set("Reparando entorno Python…", "El entorno virtual existente no es válido")
    else:
        ui.set("Creando entorno Python…", "Esto solo ocurre durante la primera preparación")
    compatible_python = (
        shutil.which("python3.12")
        or ("/run/host/usr/bin/python3.12" if os.path.isfile("/run/host/usr/bin/python3.12") else None)
        or ("/run/host/root/usr/bin/python3.12" if os.path.isfile("/run/host/root/usr/bin/python3.12") else None)
    )
    if not compatible_python:
        raise RuntimeError("No encontré Python 3.12/compatible para crear el entorno.")
    result = subprocess.run(
        [compatible_python, "-m", "venv", "--clear", "--copies", str(VENV)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError("No se pudo crear un entorno virtual con Python compatible.")
    if not PY.exists():
        raise RuntimeError("Python no pudo crear el entorno virtual.")

def ensure_deps(ui):
    if STAMP.exists():
        return
    run([str(PY), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--prefer-binary", "-r", str(ROOT / "requirements_runtime.txt")], ui, "Instalando componentes…", "Puede tardar varios minutos")
    # CUDA es opcional: solo se instala en equipos NVIDIA. AMD/Intel no reciben
    # paquetes CUDA innecesarios y pueden usar Ollama/runtime compatible o CPU.
    try:
        sys.path.insert(0, str(ROOT))
        import gpu_runtime
        gpu = gpu_runtime.detect_primary_gpu()
        if gpu and gpu.vendor == "NVIDIA":
            run([str(PY), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--prefer-binary", "-r", str(ROOT / "requirements_nvidia.txt")], ui, "Preparando NVIDIA/CUDA…", gpu.name)
    except Exception as exc:
        log("GPU opcional: " + repr(exc))
    STAMP.touch()

def download(url, target, ui, name):
    ui.set("Descargando voz española…", name)
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=30) as src, tmp.open("wb") as dst:
            total = int(src.headers.get("Content-Length") or 0); done = 0
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk: break
                dst.write(chunk); done += len(chunk)
                if total:
                    ui.set("Descargando voz española…", f"{done / 1048576:.1f} / {total / 1048576:.1f} MB")
        tmp.replace(target)
    finally:
        if tmp.exists(): tmp.unlink()

def ensure_voice(ui):
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    model = VOICE_DIR / VOICE_NAME
    meta = VOICE_DIR / VOICE_META
    if model.is_file() and meta.is_file():
        return
    old = Path.home() / ".jarvis" / "voices"
    old_model, old_meta = old / VOICE_NAME, old / VOICE_META
    if old_model.is_file() and old_meta.is_file():
        for src, dst in ((old_model, model), (old_meta, meta)):
            try: dst.symlink_to(src)
            except FileExistsError: pass
        return
    try:
        download(VOICE_BASE + VOICE_NAME, model, ui, VOICE_NAME)
        download(VOICE_BASE + VOICE_META, meta, ui, VOICE_META)
    except Exception as exc:
        raise RuntimeError(f"No se pudo descargar la voz de Piper: {exc}") from exc

def validate_runtime(ui):
    ui.set("Comprobando componentes…", "Piper, audio y aceleración disponible")
    run([
        str(PY),
        "-c",
        "import gpu_runtime; gpu_runtime.prepare_cuda_runtime(); "
        "import faster_whisper, soundfile, piper; "
        "print('runtime-core-ok'); "
        "exec(\"try:\\n import sounddevice\\n print('audio-ok')\\nexcept (ImportError, OSError) as exc:\\n print('audio-unavailable:', exc)\")",
    ], ui, "Comprobando componentes…")
    # Solo comprueba que el binario puede cargar el modelo; no reproduce sonido durante la instalación.
    run([str(PY), "-c", "import tts; print(tts._find_piper()); print(tts._find_model())"], ui, "Comprobando voz…")
    run([str(PY), "-c", "import gpu_runtime; print(gpu_runtime.diagnostics())"], ui, "Comprobando aceleración…")


def host_gui_command():
    """Use the host Python/Tk runtime in Flatpak, while keeping the Jarvis
    virtualenv packages available through PYTHONPATH."""
    if not shutil.which("flatpak-spawn"):
        return None
    host_python = "/usr/bin/python3.12"
    if not os.path.isfile("/run/host" + host_python):
        host_python = "/usr/bin/python3"
    if not os.path.isfile("/run/host" + host_python):
        return None
    site_packages = VENV / "lib" / "python3.12" / "site-packages"
    pythonpath = os.pathsep.join(str(path) for path in (ROOT, site_packages)
                                 if path and os.path.exists(str(path)))
    current = os.environ.get("PYTHONPATH")
    if current:
        pythonpath = os.pathsep.join((pythonpath, current))
    environment = [
        "env",
        f"PYTHONPATH={pythonpath}",
    ]
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        value = os.environ.get(name)
        if value:
            environment.append(f"{name}={value}")
    return [
        "flatpak-spawn",
        "--host",
        *environment,
        host_python,
        str(ROOT / "main.py"),
        "--gui",
    ]

def main():
    ui = UI()
    try:
        ui.step("env", "active")
        ensure_python(ui)
        ui.step("env", "done")

        ui.step("deps", "active")
        if not STAMP.exists():
            ensure_deps(ui)
        ui.step("deps", "done")

        ui.step("voice", "active")
        ensure_voice(ui)
        ui.step("voice", "done")

        ui.step("check", "active")
        validate_runtime(ui)
        ui.step("check", "done")

        ui.set("Jarvis está listo", "Iniciando la interfaz…")
        time.sleep(.4)
        if ui.root: ui.root.destroy()
        os.chdir(ROOT)
        host_command = host_gui_command()
        if host_command:
            os.execvp(host_command[0], host_command)
        os.execv(str(PY), [str(PY), str(ROOT / "main.py"), "--gui"])
    except Exception as exc:
        msg = str(exc)
        log("ERROR: " + repr(exc))
        for key in ("env", "deps", "voice", "check"):
            # marca en rojo el primer paso que todavía no se completó
            canvas = ui.canvas
            dot = ui.step_dots.get(key)
            if ui.root is not None and canvas is not None and dot is not None and canvas.itemcget(dot, "fill") != SUCCESS:
                ui.step(key, "error"); break
        ui.error(msg[:180])
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
