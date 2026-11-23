"""Interfaz gráfica Jarvis Local — HUD tecnológico.

Cambios de esta versión respecto al diseño anterior:
- Paleta y componentes redondeados (paneles, burbujas de chat, botones,
  barra de estado) construidos sobre un helper `RoundedPanel` reutilizable.
- Chat en burbujas (usuario a la derecha, Jarvis a la izquierda con avatar),
  con scroll propio en vez de un único `Text` plano.
- Paleta de comandos "/" (buscar, analizar, investigar, planificar,
  verificar, profundo, ejecutar, rápido) y selector de "Modo" persistente,
  ambos inyectan una instrucción de sistema real para el turno correspondiente.
- Barra superior con estado en vivo.
- Estadísticas de sistema en vivo en la barra lateral (GPU/CPU/RAM).
- Corrige un bug de concurrencia real: los diálogos de confirmación
  (`messagebox.askyesno`) y la actualización de widgets desde el hilo de voz
  ya no se disparan desde hilos de fondo (Tkinter no es thread-safe); ahora
  todo pasa por la cola de eventos y se resuelve en el hilo principal.
"""
from __future__ import annotations

import json, os, queue, threading, time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Literal

import config
import memory
import tools
from core.agent import Agent
from core.security import SecurityManager
from core.tool_manager import ToolManager

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")
# ---------------------------------------------------------------- paleta --
BG = "#0a0f14"; SIDEBAR = "#0e151c"; TOPBAR = "#0e151c"; PANEL = "#111a22"; PANEL_2 = "#17232d"
CARD = "#15212b"; BORDER = "#263743"; BORDER_SOFT = "#202e38"
TEXT = "#edf3f7"; MUTED = "#9aabb8"; DIM = "#718391"
ACCENT = "#69d5c3"; ACCENT_SOFT = "#a0eadc"; CYAN = "#77dfd0"
SUCCESS = "#79c49d"; WARNING = "#d8b66d"; DANGER = "#dc8181"
BUBBLE_USER = "#1d3538"; BUBBLE_ASSISTANT = "#17232b"
FONT = "TkDefaultFont"; MONO = "TkFixedFont"

SLASH_COMMANDS = [
    ("buscar", "🔍", "Busca información actual en Internet.", "Búsqueda",
     "Antes de responder usa buscar_en_web para obtener información actual y cita lo relevante."),
    ("analizar", "📊", "Analiza un archivo, texto o código y encuentra relaciones, errores y conclusiones.", "Análisis",
     "Analiza en profundidad lo indicado por el usuario: relaciones, errores, riesgos y conclusiones, de forma estructurada."),
    ("investigar", "🌐", "Investiga un tema usando varias fuentes y contrasta la información.", "Investigación",
     "Investiga el tema con varias búsquedas web, contrasta fuentes distintas y señala discrepancias antes de concluir."),
    ("planificar", "📋", "Crea un plan detallado antes de ejecutar una tarea.", "Planificación",
     "Antes de actuar expón un plan detallado paso a paso; ejecútalo solo después de presentarlo."),
    ("verificar", "✔", "Comprueba si un resultado o acción es realmente correcto.", "Verificación",
     "No des nada por hecho: verifica explícitamente el resultado real de cualquier acción antes de darla por buena."),
    ("profundo", "🧠", "Usa un razonamiento más profundo y detallado.", "Razonamiento",
     "Razona con más profundidad, considera alternativas y explica tu criterio antes de responder."),
    ("ejecutar", "▶", "Intenta ejecutar una acción real en el ordenador.", "Ejecución",
     "El usuario quiere una acción real con herramientas, no una simulación ni una descripción de lo que harías."),
    ("rápido", "⚡", "Prioriza una respuesta rápida y directa.", "Rapidez",
     "Responde de forma directa y breve, sin pasos ni explicaciones innecesarias."),
]
SLASH_BY_CMD = {c[0]: c for c in SLASH_COMMANDS}

MODES = {
    "Normal": None,
    "Rápido": "Responde de forma directa y breve, prioriza velocidad sobre exhaustividad.",
    "Profundo": "Piensa paso a paso con más profundidad antes de responder; contempla alternativas.",
}


def load_settings():
    defaults = {"model": config.MODEL, "ollama_url": config.OLLAMA_URL, "temperature": 0.2, "max_tool_iterations": config.MAX_TOOL_ITERATIONS,
                "history_max": config.HISTORIAL_MENSAJES_MAX, "memory_context": config.MEMORY_CONTEXT_RECALL, "memory_recalls": config.MEMORY_CONTEXT_MAX_RECALLS,
                "speak_responses": True, "continuous_voice": False, "show_activity": True, "whisper_model": config.WHISPER_MODEL_SIZE,
                "wake_threshold": config.WAKE_WORD_THRESHOLD, "silence_seconds": config.VOICE_SILENCE_SECONDS, "rms_threshold": config.VOICE_RMS_THRESHOLD,
                "enabled_tool_groups": sorted(config.ENABLED_TOOL_GROUPS)}
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict): defaults.update(d)
    except (OSError, ValueError): pass
    groups = defaults.get("enabled_tool_groups", [])
    if not isinstance(groups, list):
        groups = list(config.ENABLED_TOOL_GROUPS)
    defaults["enabled_tool_groups"] = sorted(
        {group for group in groups if isinstance(group, str)} & set(tools.TOOL_GROUPS)
    )
    return defaults


def save_settings(settings):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f: json.dump(settings, f, indent=2, ensure_ascii=False)


# ------------------------------------------------------------- utilidades --
def _round_points(x1, y1, x2, y2, r):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


class RoundedPanel(tk.Canvas):
    """Canvas que dibuja un rectángulo redondeado detrás de un Frame interno
    (self.inner) y se auto-ajusta al tamaño de su contenido."""

    def __init__(self, parent, radius=14, bg_color=PANEL_2, outline_color="", outline_width=0, parent_bg=None, **kw):
        super().__init__(parent, highlightthickness=0, bg=parent_bg or parent["bg"], bd=0, **kw)
        self.radius = radius; self.bg_color = bg_color; self.outline_color = outline_color; self.outline_width = outline_width
        self.inner = tk.Frame(self, bg=bg_color)
        self.win = self.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._redraw)

    def set_bg(self, color):
        self.bg_color = color; self.inner.configure(bg=color); self._redraw()

    def _redraw(self, _e=None):
        w = max(2, self.inner.winfo_reqwidth()); h = max(2, self.inner.winfo_reqheight())
        self.configure(width=w, height=h)
        self.delete("bg")
        pts = _round_points(1, 1, w - 1, h - 1, self.radius)
        outline = self.outline_color or self.bg_color
        self.create_polygon(pts, smooth=True, fill=self.bg_color, outline=outline, width=self.outline_width or 1, tags="bg")
        self.tag_lower("bg")


class HoverButton(RoundedPanel):
    """Botón redondeado clicable con estado hover/activo, usado en la barra
    lateral, la paleta de comandos y acciones destacadas."""

    def __init__(self, parent, text, command=None, icon="", radius=10, bg_color=PANEL_2, hover_color=None,
                 fg=TEXT, font=(FONT, 10, "bold"),
                 anchor: Literal["nw", "n", "ne", "w", "center", "e", "sw", "s", "se"] = "w",
                 padx=14, pady=9, **kw):
        super().__init__(parent, radius=radius, bg_color=bg_color, **kw)
        self.command = command; self.base_bg = bg_color; self.hover_bg = hover_color or bg_color
        self.base_fg = fg
        row = tk.Frame(self.inner, bg=bg_color); row.pack(fill="x", padx=padx, pady=pady)
        self._labels = []
        if icon:
            li = tk.Label(row, text=icon, bg=bg_color, fg=fg, font=(FONT, 10)); li.pack(side="left", padx=(0, 8)); self._labels.append(li)
        lt = tk.Label(row, text=text, bg=bg_color, fg=fg, font=font, anchor=anchor); lt.pack(side="left", fill="x", expand=True); self._labels.append(lt)
        for w in (self, self.inner, row, *self._labels):
            w.bind("<Enter>", self._on_enter); w.bind("<Leave>", self._on_leave); w.bind("<Button-1>", self._on_click)
        self._row = row

    def _apply(self, color, fg=None):
        self.set_bg(color); self._row.configure(bg=color)
        for w in self._labels: w.configure(bg=color, fg=fg or self.base_fg)

    def _on_enter(self, _e=None):
        if self.hover_bg != self.base_bg: self._apply(self.hover_bg)

    def _on_leave(self, _e=None): self._apply(self.base_bg)

    def _on_click(self, _e=None):
        if self.command: self.command()

    def set_active(self, active):
        self.base_bg = "#243242" if active else SIDEBAR
        self.base_fg = ACCENT_SOFT if active else MUTED
        self._apply(self.base_bg, self.base_fg)


def _fmt_time(): return time.strftime("%H:%M")


class ChatFeed(tk.Frame):
    """Lista de burbujas de chat con scroll propio (canvas + frame interno)."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.bg = bg
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.vsb = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            bg=PANEL_2,
            troughcolor=BG,
            activebackground=ACCENT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            width=9,
        )
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", self._grab_wheel); self.canvas.bind("<Leave>", self._release_wheel)

    def _grab_wheel(self, _e=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel); self.canvas.bind_all("<Button-5>", self._on_wheel)

    def _release_wheel(self, _e=None):
        self.canvas.unbind_all("<MouseWheel>"); self.canvas.unbind_all("<Button-4>"); self.canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4: self.canvas.yview_scroll(-2, "units")
        elif getattr(event, "num", None) == 5: self.canvas.yview_scroll(2, "units")
        else: self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def clear(self):
        for w in self.inner.winfo_children(): w.destroy()

    def scroll_bottom(self):
        self.canvas.update_idletasks(); self.canvas.yview_moveto(1.0)

    def add_bubble(self, role, text, ts=None, animate=False, tag=None):
        ts = ts or _fmt_time()
        is_user = role == "user"
        row = tk.Frame(self.inner, bg=self.bg); row.pack(fill="x", padx=18, pady=(6, 6))
        col = tk.Frame(row, bg=self.bg)
        if is_user:
            col.pack(side="right")
        else:
            av = tk.Canvas(row, width=30, height=30, bg=self.bg, highlightthickness=0); av.pack(side="left", padx=(0, 9), pady=(2, 0))
            av.create_oval(3, 3, 27, 27, fill="#243242", outline="")
            av.create_text(15, 15, text="J", fill=ACCENT_SOFT, font=(FONT, 10, "bold"))
            col.pack(side="left")
        bubble_bg = BUBBLE_USER if is_user else BUBBLE_ASSISTANT
        panel = RoundedPanel(col, radius=10, bg_color=bubble_bg, parent_bg=self.bg)
        panel.pack(anchor="e" if is_user else "w")
        if tag:
            tk.Label(panel.inner, text=tag, bg=bubble_bg, fg=CYAN, font=(MONO, 7, "bold")).pack(anchor="w", padx=14, pady=(9, 0))
        lbl = tk.Label(panel.inner, text="", bg=bubble_bg, fg=TEXT, font=(FONT, 10), justify="left", wraplength=680, anchor="w")
        lbl.pack(padx=15, pady=(10 if not tag else 3, 10))
        meta = tk.Label(col, text=("TÚ · " if is_user else "JARVIS · ") + ts, bg=self.bg, fg=DIM, font=(FONT, 8))
        meta.pack(anchor="e" if is_user else "w", padx=4, pady=(3, 0))

        full = (text or "").strip()
        if animate and full:
            lbl.configure(text=full)
            self.inner.update_idletasks()
            w = panel.inner.winfo_reqwidth(); h = panel.inner.winfo_reqheight()
            panel.inner.pack_propagate(False); panel.inner.configure(width=w, height=h)
            lbl.configure(text="")
            self._type(lbl, list(full), 0)
        else:
            lbl.configure(text=full)
        self.scroll_bottom()
        return row

    def _type(self, lbl, chars, i):
        if not lbl.winfo_exists(): return
        if i >= len(chars):
            self.scroll_bottom(); return
        lbl.configure(text="".join(chars[:i + 1]))
        if i % 6 == 0: self.scroll_bottom()
        delay = 30 if chars[i] in ".,!?\n" else 9
        lbl.after(delay, lambda: self._type(lbl, chars, i + 1))

    def add_thinking(self):
        row = tk.Frame(self.inner, bg=self.bg); row.pack(fill="x", padx=18, pady=(6, 6))
        av = tk.Canvas(row, width=30, height=30, bg=self.bg, highlightthickness=0); av.pack(side="left", padx=(0, 9))
        av.create_oval(3, 3, 27, 27, fill="#243242", outline="")
        av.create_text(15, 15, text="J", fill=ACCENT_SOFT, font=(FONT, 10, "bold"))
        panel = RoundedPanel(row, radius=10, bg_color=BUBBLE_ASSISTANT, parent_bg=self.bg); panel.pack(side="left")
        lbl = tk.Label(panel.inner, text="Procesando", bg=BUBBLE_ASSISTANT, fg=CYAN, font=(MONO, 9, "bold")); lbl.pack(padx=14, pady=10)
        self.scroll_bottom()

        job = {"n": 0, "alive": True}
        def pulse():
            if not job["alive"] or not lbl.winfo_exists(): return
            lbl.configure(text="Procesando" + "." * ((job["n"] % 3) + 1)); job["n"] += 1
            lbl.after(320, pulse)
        pulse()

        def stop():
            job["alive"] = False
            if row.winfo_exists(): row.destroy()
        return stop


# ------------------------------------------------------------------ GUI ---
class JarvisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Jarvis")
        self.root.geometry("1360x860")
        self.root.minsize(980, 680)
        self.root.configure(bg=BG)
        self._select_fonts()
        self.settings = load_settings(); self.events = queue.Queue(); self.busy = False; self.listening = False
        self.voice_stop = threading.Event(); self.cancel_event = threading.Event(); self.speech_cancel_event = threading.Event()
        self.speaking = False; self.ready_event = threading.Event(); self.ready_event.set()
        self._pending_privacy_close = None; self._pending_confirm_close = None
        self._thinking_stop: Callable[[], None] | None = None
        self.mode = "Normal"; self.pending_directive = None
        self.messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
        memory.init_db(); self.messages.extend(memory.cargar_historial(int(self.settings.get("history_max", 40))))
        security = SecurityManager()
        self.agent = Agent(ToolManager(
            security,
            self._confirm_action,
            event_callback=self._tool_event,
            privacy_callback=self._privacy_confirm,
            enabled_tool_groups=self.settings["enabled_tool_groups"],
        ))
        self._configure_style(); self._build(); self._render_history(); self._poll_stats()
        self.root.after(60, self._drain_events); self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _select_fonts(self):
        global FONT, MONO
        import tkinter.font as tkfont

        available = set(tkfont.families(self.root))
        FONT = next((name for name in ("Inter", "Noto Sans", "Cantarell", "DejaVu Sans", "Liberation Sans") if name in available), "TkDefaultFont")
        MONO = next((name for name in ("JetBrains Mono", "Cascadia Code", "DejaVu Sans Mono", "Liberation Mono") if name in available), "TkFixedFont")
        tkfont.nametofont("TkDefaultFont").configure(family=FONT, size=10)
        tkfont.nametofont("TkFixedFont").configure(family=MONO, size=9)

    # -- estilo ttk (widgets nativos: entradas, checkbox, scrollbar) --
    def _configure_style(self):
        s = ttk.Style(self.root); s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=TEXT, font=(FONT, 10))
        s.configure("TCheckbutton", background=CARD, foreground=TEXT, font=(FONT, 9), padding=5)
        s.map("TCheckbutton", background=[("active", CARD)], foreground=[("disabled", DIM)])
        s.configure("TEntry", fieldbackground="#11171e", foreground=TEXT, insertcolor=ACCENT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=9)
        s.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=BG, bordercolor=BG,
                    arrowcolor=MUTED, lightcolor=PANEL_2, darkcolor=PANEL_2, width=10)

    def _build(self):
        self._build_topbar()
        body = tk.Frame(self.root, bg=BG); body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self.content = tk.Frame(body, bg=BG); self.content.pack(side="left", fill="both", expand=True, padx=(14, 18), pady=(0, 18))
        self.pages = {}
        self._build_chat_page(); self._build_activity_page(); self._build_memory_page(); self._build_tools_page(); self._build_diagnostics_page(); self._build_settings_page()
        self._show_page("chat", animate=False)

    # -- barra superior --
    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=TOPBAR, height=58); bar.pack(fill="x"); bar.pack_propagate(False)
        tk.Frame(bar, bg=BORDER, height=1).pack(side="bottom", fill="x")
        brand = tk.Frame(bar, bg=TOPBAR); brand.pack(side="left", padx=22)
        tk.Label(brand, text="Jarvis", bg=TOPBAR, fg=TEXT, font=(FONT, 14, "bold")).pack(side="left")
        tk.Label(brand, text="  ASISTENTE LOCAL", bg=TOPBAR, fg=DIM, font=(FONT, 8, "bold")).pack(side="left", pady=(4, 0))
        right = tk.Frame(bar, bg=TOPBAR); right.pack(side="right", padx=22)
        self.top_status_dot = tk.Canvas(right, width=9, height=9, bg=TOPBAR, highlightthickness=0)
        self.top_status_dot.pack(side="left", padx=(0, 8))
        self.top_status_dot_id = self.top_status_dot.create_oval(1, 1, 8, 8, fill=SUCCESS, outline="")
        self.top_status_text = tk.StringVar(value="Listo")
        tk.Label(right, textvariable=self.top_status_text, bg=TOPBAR, fg=MUTED, font=(FONT, 9)).pack(side="left")

    # -- barra lateral --
    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=SIDEBAR, width=238); side.pack(side="left", fill="y"); side.pack_propagate(False)
        brand = tk.Frame(side, bg=SIDEBAR); brand.pack(fill="x", padx=22, pady=(24, 26))
        tk.Label(brand, text="J", bg="#243242", fg=ACCENT_SOFT, width=2, height=1,
                 font=(FONT, 15, "bold")).pack(side="left", padx=(0, 11), ipady=5)
        brand_text = tk.Frame(brand, bg=SIDEBAR); brand_text.pack(side="left")
        tk.Label(brand_text, text="Jarvis", bg=SIDEBAR, fg=TEXT, font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(brand_text, text="ASISTENTE PERSONAL", bg=SIDEBAR, fg=DIM, font=(FONT, 7, "bold")).pack(anchor="w", pady=(2, 0))

        tk.Label(side, text="ESPACIO DE TRABAJO", bg=SIDEBAR, fg=DIM, font=(FONT, 7, "bold")).pack(anchor="w", padx=22, pady=(0, 8))
        nav = tk.Frame(side, bg=SIDEBAR); nav.pack(fill="x", padx=12)
        self.nav_buttons = {}
        for key, icon, label in (("chat", "○", "Conversación"), ("activity", "◷", "Actividad"), ("memory", "▤", "Memoria"),
                                  ("tools", "⌘", "Herramientas"), ("diagnostics", "◫", "Diagnóstico"), ("settings", "⚙", "Configuración")):
            b = HoverButton(nav, label, command=lambda k=key: self._show_page(k), icon=icon, radius=8,
                            bg_color=SIDEBAR, hover_color=PANEL_2, fg=MUTED, font=(FONT, 9), padx=11, pady=8)
            b.pack(fill="x", pady=2); self.nav_buttons[key] = b
        self.nav_buttons["chat"].set_active(True)

        tk.Frame(side, bg=SIDEBAR).pack(fill="both", expand=True)
        tk.Frame(side, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(0, 14))
        tk.Label(side, text="RECURSOS DEL SISTEMA", bg=SIDEBAR, fg=DIM, font=(FONT, 7, "bold")).pack(anchor="w", padx=22, pady=(0, 8))
        stats = tk.Frame(side, bg=SIDEBAR); stats.pack(fill="x", padx=22, pady=(0, 18))
        self.stat_labels = {}
        for key, label in (("gpu", "GPU"), ("cpu", "CPU"), ("ram", "RAM")):
            row = tk.Frame(stats, bg=SIDEBAR); row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=SIDEBAR, fg=MUTED, font=(FONT, 8), width=5, anchor="w").pack(side="left")
            v = tk.Label(row, text="—", bg=SIDEBAR, fg=TEXT, font=(FONT, 8, "bold")); v.pack(side="left")
            self.stat_labels[key] = v

        status_row = tk.Frame(side, bg=SIDEBAR); status_row.pack(anchor="w", padx=22, pady=(0, 4))
        self.side_dot = tk.Canvas(status_row, width=8, height=8, bg=SIDEBAR, highlightthickness=0); self.side_dot.pack(side="left", padx=(0, 7))
        self._side_dot_id = self.side_dot.create_oval(1, 1, 7, 7, fill=SUCCESS, outline="")
        self.side_status = tk.StringVar(value="Sistema en línea")
        tk.Label(status_row, textvariable=self.side_status, bg=SIDEBAR, fg=MUTED, font=(FONT, 8)).pack(side="left")
        tk.Label(side, text="Ollama · procesamiento local", bg=SIDEBAR, fg=DIM, font=(FONT, 7)).pack(anchor="w", padx=22, pady=(0, 18))

    # -- páginas --
    def _new_page(self, title, subtitle):
        page = tk.Frame(
            self.content,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0,
        )
        page.place(relx=0, rely=0, relwidth=1, relheight=1)
        page.pack_propagate(False)
        inner = page
        top = tk.Frame(inner, bg=PANEL); top.pack(fill="x", padx=24, pady=(20, 12))
        tk.Label(top, text=title, bg=PANEL, fg=TEXT, font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(top, text=subtitle, bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(5, 0))
        return page, inner

    def _build_chat_page(self):
        page, inner = self._new_page("Conversación", "Asistente local con control verificable, memoria y herramientas.")
        self.chat = ChatFeed(inner, bg=PANEL); self.chat.canvas.configure(bg=PANEL); self.chat.inner.configure(bg=PANEL)
        self.chat.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self.palette_holder = tk.Frame(inner, bg=PANEL); self.palette_holder.pack(fill="x", padx=24, pady=(0, 4))
        self.palette = None; self.mode_chip = None

        composer = tk.Frame(inner, bg=PANEL); composer.pack(fill="x", padx=24, pady=(0, 8)); composer.columnconfigure(0, weight=1)
        input_panel = tk.Frame(
            composer,
            bg=PANEL_2,
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0,
        )
        input_panel.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.input = tk.Text(input_panel, height=3, bg=PANEL_2, fg=TEXT, insertbackground=CYAN, relief="flat",
                             bd=0, wrap="word", padx=14, pady=10, font=(FONT, 10), undo=True)
        self.input.pack(fill="both", expand=True, padx=1, pady=1)
        self.input.bind("<Control-Return>", lambda e: self._send_text())
        self.input.bind("<KeyRelease>", self._on_input_key)

        actions = tk.Frame(composer, bg=PANEL); actions.grid(row=0, column=1, sticky="ns")
        self.send_btn = HoverButton(actions, "ENVIAR  ⏎", command=self._send_text, radius=10, bg_color=ACCENT, hover_color=ACCENT_SOFT,
                                     fg="#03101a", font=(FONT, 10, "bold"), anchor="center", padx=15, pady=10)
        self.send_btn.pack(fill="x")
        self.cancel_btn = HoverButton(actions, "■ DETENER", command=self._cancel_current, radius=10, bg_color="#4a1d2b", hover_color="#6b2638",
                                      fg="#ffdce2", font=(FONT, 9, "bold"), anchor="center", padx=12, pady=8)
        self.cancel_btn.pack_forget()
        self.voice_button = HoverButton(actions, "VOZ", command=self._toggle_voice, radius=10, bg_color=PANEL_2, hover_color="#1b2b43",
                                         fg=TEXT, font=(FONT, 9, "bold"), anchor="center", padx=12, pady=8)
        self.voice_button.pack(fill="x", pady=(7, 0))

        bottom = tk.Frame(inner, bg=PANEL); bottom.pack(fill="x", padx=25, pady=(0, 14))
        self.status = tk.StringVar(value="SISTEMA LISTO")
        self.status.trace_add("write", self._sync_status)
        tk.Label(bottom, textvariable=self.status, bg=PANEL, fg=SUCCESS, font=(MONO, 8, "bold")).pack(side="left")
        tk.Label(bottom, text="Ctrl + Enter para enviar", bg=PANEL, fg=DIM, font=(FONT, 8)).pack(side="left", padx=(14, 0))
        mode_box = HoverButton(bottom, f"Modo: {self.mode}  ▾", command=self._cycle_mode, radius=8, bg_color=PANEL_2, hover_color="#1b2b43",
                                fg=ACCENT_SOFT, font=(FONT, 8, "bold"), anchor="center", padx=10, pady=5)
        mode_box.pack(side="right"); self.mode_btn = mode_box
        self.pages["chat"] = page

    def _on_input_key(self, _e=None):
        text = self.input.get("1.0", "end-1c")
        first_line = text.split("\n", 1)[0]
        if first_line.startswith("/") and "\n" not in text.strip("\n")[:1] and " " not in first_line:
            self._show_palette(first_line[1:].lower())
        else:
            self._hide_palette()

    def _show_palette(self, prefix):
        matches = [c for c in SLASH_COMMANDS if c[0].startswith(prefix)] if prefix else SLASH_COMMANDS
        if self.palette is not None: self.palette.destroy(); self.palette = None
        if not matches: return
        self.palette = RoundedPanel(self.palette_holder, radius=12, bg_color=PANEL_2, outline_color=BORDER, outline_width=1, parent_bg=PANEL)
        self.palette.pack(fill="x", pady=(0, 8))
        for cmd, icon, desc, tag, _directive in matches:
            row = HoverButton(self.palette.inner, f"/{cmd}   {desc}", command=lambda c=cmd: self._apply_slash(c), icon=icon,
                               radius=8, bg_color=PANEL_2, hover_color="#1b2b43", fg=TEXT, font=(FONT, 9, "bold"), padx=12, pady=7)
            row.pack(fill="x", padx=4, pady=2)
            tk.Label(row.inner, text=tag, bg=PANEL_2, fg=CYAN, font=(MONO, 7, "bold")).pack(side="right", padx=(0, 6))

    def _hide_palette(self):
        if self.palette is not None: self.palette.destroy(); self.palette = None

    def _apply_slash(self, cmd):
        _c, _i, _d, tag, directive = SLASH_BY_CMD[cmd]
        self.input.delete("1.0", "end")
        self.pending_directive = directive
        self._hide_palette()
        self._show_directive_chip(f"/{cmd} · {tag}", one_shot=True)
        self.input.focus_set()

    def _show_directive_chip(self, label, one_shot=False):
        if self.mode_chip is not None: self.mode_chip.destroy(); self.mode_chip = None
        chip = RoundedPanel(self.palette_holder, radius=10, bg_color="#173049", parent_bg=PANEL); chip.pack(fill="x", pady=(0, 6))
        row = tk.Frame(chip.inner, bg="#173049"); row.pack(fill="x", padx=10, pady=5)
        tk.Label(row, text=("⚡ " if one_shot else "◆ ") + label, bg="#173049", fg=ACCENT_SOFT, font=(FONT, 8, "bold")).pack(side="left")
        close = tk.Label(row, text="✕", bg="#173049", fg=MUTED, font=(FONT, 8, "bold"), cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self._clear_directive())
        self.mode_chip = chip

    def _clear_directive(self):
        self.pending_directive = None; self.mode = "Normal"; self.mode_btn._apply(PANEL_2)
        self.mode_btn._labels[-1].configure(text="Modo: Normal  ▾")
        if self.mode_chip is not None: self.mode_chip.destroy(); self.mode_chip = None

    def _cycle_mode(self):
        keys = list(MODES.keys()); i = (keys.index(self.mode) + 1) % len(keys); self.mode = keys[i]
        self.mode_btn._labels[-1].configure(text=f"Modo: {self.mode}  ▾")
        if self.mode == "Normal":
            self.pending_directive = None
            if self.mode_chip is not None: self.mode_chip.destroy(); self.mode_chip = None
        else:
            self.pending_directive = MODES[self.mode]
            self._show_directive_chip(f"Modo {self.mode}", one_shot=False)

    def _build_activity_page(self):
        page, inner = self._new_page("Actividad", "Registro visual de ejecución, verificación y resultado de herramientas.")
        self.activity = tk.Text(inner, bg=CARD, fg=MUTED, relief="flat", bd=0, wrap="word", padx=18, pady=18, font=(MONO, 9), state="disabled")
        self.activity.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        self.activity.tag_configure("tool", foreground=WARNING); self.activity.tag_configure("ok", foreground=SUCCESS); self.activity.tag_configure("err", foreground=DANGER)
        self.pages["activity"] = page

    def _build_memory_page(self):
        page, inner = self._new_page("Memoria", "Recuerdos persistentes separados del historial de conversación.")
        row = tk.Frame(inner, bg=PANEL); row.pack(fill="x", padx=24, pady=(0, 10))
        HoverButton(row, "ACTUALIZAR", command=self._refresh_memory, radius=8, bg_color=PANEL_2, hover_color="#1b2b43", fg=TEXT, font=(FONT, 9, "bold"), anchor="center", padx=14, pady=8).pack(side="left")
        HoverButton(row, "LIMPIAR HISTORIAL", command=self._clear_history, radius=8, bg_color=PANEL_2, hover_color="#3a1d28", fg=DANGER, font=(FONT, 9, "bold"), anchor="center", padx=14, pady=8).pack(side="left", padx=8)
        self.memory_view = tk.Text(inner, bg=CARD, fg=TEXT, relief="flat", bd=0, wrap="word", padx=18, pady=18, font=(MONO, 9), state="disabled")
        self.memory_view.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        self.pages["memory"] = page

    def _build_tools_page(self):
        page, inner = self._new_page("Herramientas", "Mapa de capacidades de Jarvis y su estado operativo.")
        box = tk.Frame(inner, bg=PANEL); box.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        group_panel = RoundedPanel(box, radius=10, bg_color=CARD, outline_color=BORDER_SOFT, outline_width=1, parent_bg=PANEL)
        group_panel.pack(fill="x", pady=(0, 10))
        tk.Label(group_panel.inner, text="GRUPOS ACTIVOS", bg=CARD, fg=ACCENT, font=(FONT, 9, "bold")).pack(anchor="w", padx=14, pady=(10, 4))
        group_grid = tk.Frame(group_panel.inner, bg=CARD); group_grid.pack(fill="x", padx=12, pady=(0, 8))
        self.tool_group_vars = {}
        for index, (group, label) in enumerate(tools.TOOL_GROUP_LABELS.items()):
            variable = tk.BooleanVar(value=group in self.agent.tools.enabled_tool_groups)
            self.tool_group_vars[group] = variable
            ttk.Checkbutton(group_grid, text=label, variable=variable).grid(
                row=index // 2, column=index % 2, sticky="w", padx=4, pady=2,
            )
        group_grid.columnconfigure(0, weight=1); group_grid.columnconfigure(1, weight=1)
        HoverButton(group_panel.inner, "GUARDAR GRUPOS", command=self._save_tool_groups, radius=8, bg_color=PANEL_2,
                    hover_color="#1b2b43", fg=TEXT, font=(FONT, 8, "bold"), anchor="center", padx=12, pady=6).pack(
                        anchor="e", padx=12, pady=(0, 10),
                    )
        items = [("SISTEMA", "Fecha, procesos, RAM, disco y diagnóstico"), ("APLICACIONES", "Abrir, cerrar y verificar aplicaciones"),
                  ("ARCHIVOS", "Crear, leer, modificar y organizar archivos"), ("CONTROL GUI", "Ratón, teclado y ventanas"),
                  ("CAPTURA", "Captura de pantalla sin depender de OCR"), ("VISIÓN", "OCR y visión local cuando estén disponibles"),
                  ("WEB", "Búsqueda y lectura de páginas públicas"), ("MEMORIA", "Contexto y recuerdos persistentes"), ("VOZ", "Whisper, Piper y Wake Word")]
        for title, desc in items:
            card = RoundedPanel(box, radius=10, bg_color=CARD, outline_color=BORDER_SOFT, outline_width=1, parent_bg=PANEL); card.pack(fill="x", pady=4)
            row = tk.Frame(card.inner, bg=CARD); row.pack(fill="x", padx=14, pady=10)
            tk.Label(row, text="●", bg=CARD, fg=SUCCESS, font=(FONT, 12, "bold")).pack(side="left", padx=(0, 10))
            tk.Label(row, text=title, bg=CARD, fg=TEXT, font=(FONT, 9, "bold")).pack(side="left")
            tk.Label(row, text=desc, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=18)
        self.pages["tools"] = page

    def _build_diagnostics_page(self):
        page, inner = self._new_page("Diagnóstico", "Comprobación rápida del entorno real.")
        self.diag_view = tk.Text(inner, bg=CARD, fg=TEXT, relief="flat", bd=0, wrap="word", padx=18, pady=18, font=(MONO, 9), state="disabled")
        self.diag_view.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        HoverButton(inner, "EJECUTAR DIAGNÓSTICO", command=self._run_diagnostics, radius=10, bg_color=ACCENT, hover_color=ACCENT_SOFT,
                    fg="#03101a", font=(FONT, 10, "bold"), anchor="center", padx=15, pady=10).pack(fill="x", padx=24, pady=(0, 24))
        self.pages["diagnostics"] = page; self._run_diagnostics()

    def _run_diagnostics(self):
        import shutil
        import gpu_runtime
        checks = [("xdotool", "xdotool"), ("wmctrl", "wmctrl"), ("gnome-screenshot", "gnome-screenshot"), ("tesseract", "tesseract")]
        try:
            gd = gpu_runtime.diagnostics()
        except Exception as exc:
            gd = {"gpus": [], "recommended_backend": "cpu", "whisper_device": "cpu", "whisper_compute_type": "int8", "whisper_gpu_acceleration": False, "error": str(exc)}
        lines = ["JARVIS LOCAL", "", "HARDWARE / ACELERACIÓN"]
        gpus = gd.get("gpus", [])
        if not gpus:
            lines.append("GPU                  NO DETECTADA → CPU")
        else:
            for i, g in enumerate(gpus, 1):
                vram = f"{g.get('vram_mb')} MB" if g.get('vram_mb') else "VRAM no disponible"
                lines.append(f"GPU {i:<17} {g.get('vendor')} · {g.get('name')}")
                lines.append(f"  Driver/backend      {g.get('driver') or 'no disponible'} / {g.get('backend')}")
                lines.append(f"  VRAM                {vram}")
        lines += [f"Backend recomendado   {gd.get('recommended_backend','cpu')}",
                  f"Whisper               {gd.get('whisper_device')} · {gd.get('whisper_compute_type')}",
                  f"Whisper GPU real      {'SÍ' if gd.get('whisper_gpu_acceleration') else 'NO → CPU'}", "",
                  "OLLAMA", f"URL                  {self.settings.get('ollama_url',config.OLLAMA_URL)}", f"Modelo               {self.settings.get('model',config.MODEL)}", "",
                  "HERRAMIENTAS"]
        for label, cmd in checks: lines.append(f"{label:<20} {'OK' if shutil.which(cmd) else 'NO DISPONIBLE'}")
        lines += ["", "Nota: AMD/Intel se detectan a nivel de hardware. Whisper solo usa GPU cuando CTranslate2 confirma un backend compatible; si no, usa CPU automáticamente."]
        self.diag_view.configure(state="normal"); self.diag_view.delete("1.0", "end"); self.diag_view.insert("end", "\n".join(lines)); self.diag_view.configure(state="disabled")

    def _build_settings_page(self):
        page, inner = self._new_page("Configuración", "Controla el comportamiento de Jarvis sin editar archivos.")
        form = tk.Frame(inner, bg=PANEL); form.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        self.setting_vars = {}
        sections = {"IA": [("model", "Modelo Ollama", self.settings["model"]), ("ollama_url", "URL Ollama", self.settings["ollama_url"]),
                            ("temperature", "Temperatura", self.settings["temperature"]), ("max_tool_iterations", "Máximo de pasos", self.settings["max_tool_iterations"])],
                    "Memoria": [("history_max", "Mensajes de historial", self.settings["history_max"]), ("memory_recalls", "Recuerdos recuperados", self.settings["memory_recalls"])],
                    "Voz": [("whisper_model", "Modelo Whisper", self.settings["whisper_model"]), ("wake_threshold", "Umbral wake word", self.settings["wake_threshold"]),
                            ("silence_seconds", "Tiempo de silencio", self.settings["silence_seconds"]), ("rms_threshold", "Umbral de voz", self.settings["rms_threshold"])]}
        r = 0
        for title, fields in sections.items():
            tk.Label(form, text=title, bg=PANEL, fg=ACCENT, font=(FONT, 11, "bold")).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8 if r else 0, 6)); r += 1
            for key, label, value in fields:
                tk.Label(form, text=label, bg=PANEL, fg=MUTED, font=(FONT, 9)).grid(row=r, column=0, sticky="w", pady=4)
                var = tk.StringVar(value=str(value)); self.setting_vars[key] = var
                ttk.Entry(form, textvariable=var, width=36).grid(row=r, column=1, sticky="ew", padx=(25, 0), pady=4); r += 1
        for key, label in (("memory_context", "Usar memoria contextual"), ("speak_responses", "Leer respuestas en voz alta"),
                            ("continuous_voice", "Escucha continua"), ("show_activity", "Mostrar actividad de herramientas")):
            var = tk.BooleanVar(value=bool(self.settings[key])); self.setting_vars[key] = var
            ttk.Checkbutton(form, text=label, variable=var).grid(row=r, column=0, columnspan=2, sticky="w", pady=4); r += 1
        HoverButton(form, "GUARDAR CONFIGURACIÓN", command=self._save, radius=10, bg_color=ACCENT, hover_color=ACCENT_SOFT, fg="#03101a",
                    font=(FONT, 10, "bold"), anchor="center", padx=15, pady=10).grid(row=r, column=0, columnspan=2, sticky="ew", pady=(15, 4)); r += 1
        HoverButton(form, "RESTAURAR VALORES", command=self._reset_settings, radius=10, bg_color=PANEL_2, hover_color="#1b2b43", fg=TEXT,
                    font=(FONT, 9, "bold"), anchor="center", padx=15, pady=9).grid(row=r, column=0, columnspan=2, sticky="ew", pady=4)
        form.columnconfigure(1, weight=1)
        self.pages["settings"] = page

    # -- navegación --
    def _show_page(self, key, animate=True):
        page = self.pages[key]
        for k, b in self.nav_buttons.items(): b.set_active(k == key)
        # OJO: `page` es un Canvas (RoundedPanel), y tkinter.Canvas redefine
        # tkraise/lift como alias de tag_raise (para elementos del canvas,
        # no para el widget). Llamar a page.tkraise() aquí generaría un
        # TclError ("wrong # args"). Usamos el comando Tcl `raise` directo
        # sobre la ruta del widget para subirlo de verdad en el stacking.
        page.tk.call("raise", page._w)
        if key == "memory": self._refresh_memory()

    # -- render de historial / chat --
    def _render_history(self):
        for m in self.messages:
            if m.get("role") == "user": self.chat.add_bubble("user", m.get("content", ""), animate=False)
            elif m.get("role") == "assistant" and m.get("content"): self.chat.add_bubble("assistant", m.get("content", ""), animate=False)

    def _sync_status(self, *_args):
        text = self.status.get()
        self.top_status_text.set(text.title())
        lowered = text.casefold()
        color = DANGER if "error" in lowered else WARNING if any(
            word in lowered for word in ("cancel", "deten", "escuch")
        ) else SUCCESS if any(word in lowered for word in ("listo", "online", "sistema ok")) else ACCENT
        self.top_status_dot.itemconfigure(self.top_status_dot_id, fill=color)

    # -- estadísticas de sistema en vivo (barra lateral) --
    def _poll_stats(self):
        try:
            gpu_pct = cpu_pct = ram_pct = None
            try:
                with open("/proc/meminfo", encoding="utf-8") as f:
                    vals = {ln.split(":", 1)[0]: int(ln.split(":", 1)[1].split()[0]) for ln in f if ":" in ln}
                total = vals.get("MemTotal", 0); avail = vals.get("MemAvailable", 0)
                if total: ram_pct = (total - avail) / total * 100
            except OSError: pass
            try:
                load1 = os.getloadavg()[0]; cpu_pct = min(100.0, load1 / max(os.cpu_count() or 1, 1) * 100)
            except (OSError, AttributeError): pass
            try:
                import gpu_runtime
                gd = gpu_runtime.diagnostics()
                gpu_pct = gd.get("gpus", [{}])[0].get("utilization_pct") if gd.get("gpus") else None
            except Exception: pass
            self.stat_labels["ram"].configure(text=f"{ram_pct:.0f}%" if ram_pct is not None else "N/D")
            self.stat_labels["cpu"].configure(text=f"{cpu_pct:.0f}%" if cpu_pct is not None else "N/D")
            self.stat_labels["gpu"].configure(text=f"{gpu_pct:.0f}%" if isinstance(gpu_pct, (int, float)) else "AUTO")
        except Exception:
            pass
        self.root.after(4000, self._poll_stats)

    # -- actividad --
    def _activity(self, text, tag="tool"):
        if not self.settings.get("show_activity", True): return
        self.activity.configure(state="normal"); self.activity.insert("end", time.strftime("%H:%M:%S ") + text + "\n", tag); self.activity.configure(state="disabled"); self.activity.see("end")

    # -- configuración --
    def _save(self):
        try:
            s = self.setting_vars
            temperature = float(s["temperature"].get())
            max_iterations = int(s["max_tool_iterations"].get())
            history_max = int(s["history_max"].get())
            memory_recalls = int(s["memory_recalls"].get())
            wake_threshold = float(s["wake_threshold"].get())
            silence_seconds = float(s["silence_seconds"].get())
            rms_threshold = float(s["rms_threshold"].get())
            if not 0.0 <= temperature <= 2.0:
                raise ValueError("La temperatura debe estar entre 0 y 2.")
            if not 1 <= max_iterations <= 20:
                raise ValueError("Los pasos máximos deben estar entre 1 y 20.")
            if not 1 <= history_max <= 500:
                raise ValueError("El historial debe tener entre 1 y 500 mensajes.")
            if not 1 <= memory_recalls <= 50:
                raise ValueError("Los recuerdos recuperados deben estar entre 1 y 50.")
            if not 0.0 <= wake_threshold <= 1.0:
                raise ValueError("El umbral wake word debe estar entre 0 y 1.")
            if silence_seconds < 0.1 or silence_seconds > 10:
                raise ValueError("El silencio debe estar entre 0.1 y 10 segundos.")
            if not 0.001 <= rms_threshold <= 0.5:
                raise ValueError("El umbral de voz no es válido.")
            self.settings.update({"model": s["model"].get().strip() or config.MODEL, "ollama_url": s["ollama_url"].get().strip() or config.OLLAMA_URL,
                                   "temperature": temperature, "max_tool_iterations": max_iterations,
                                   "history_max": history_max, "memory_recalls": memory_recalls,
                                   "whisper_model": s["whisper_model"].get().strip() or config.WHISPER_MODEL_SIZE, "wake_threshold": wake_threshold,
                                   "silence_seconds": silence_seconds, "rms_threshold": rms_threshold,
                                   "memory_context": s["memory_context"].get(), "speak_responses": s["speak_responses"].get(),
                                   "continuous_voice": s["continuous_voice"].get(), "show_activity": s["show_activity"].get()})
            config.configure_runtime(self.settings["model"], self.settings["ollama_url"]); config.MAX_TOOL_ITERATIONS = self.settings["max_tool_iterations"]
            config.HISTORIAL_MENSAJES_MAX = self.settings["history_max"]; config.MEMORY_CONTEXT_RECALL = self.settings["memory_context"]; config.MEMORY_CONTEXT_MAX_RECALLS = self.settings["memory_recalls"]
            config.TEMPERATURE = self.settings["temperature"]
            config.WHISPER_MODEL_SIZE = self.settings["whisper_model"]
            config.WAKE_WORD_THRESHOLD = self.settings["wake_threshold"]
            config.VOICE_SILENCE_SECONDS = self.settings["silence_seconds"]
            config.VOICE_RMS_THRESHOLD = self.settings["rms_threshold"]
            save_settings(self.settings); self.status.set("CONFIGURACIÓN GUARDADA"); self.side_status.set("CONFIGURADO"); self._activity("Configuración actualizada", "ok")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Configuración", f"No se pudo guardar: {exc}", parent=self.root)

    def _reset_settings(self):
        if not messagebox.askyesno("Configuración", "¿Restaurar los valores por defecto?", parent=self.root): return
        try: os.remove(SETTINGS_PATH)
        except OSError: pass
        self.settings = load_settings()
        for key, var in self.setting_vars.items():
            if key in self.settings: var.set(self.settings[key])
        for group, variable in self.tool_group_vars.items():
            variable.set(group in self.settings["enabled_tool_groups"])
        self._apply_tool_groups(self.settings["enabled_tool_groups"])
        self.status.set("VALORES RESTAURADOS")

    def _refresh_memory(self):
        try: text = memory.buscar_recuerdos()
        except Exception as exc: text = f"Error al cargar memoria: {exc}"
        self.memory_view.configure(state="normal"); self.memory_view.delete("1.0", "end"); self.memory_view.insert("end", text); self.memory_view.configure(state="disabled")

    def _clear_history(self):
        if not messagebox.askyesno("Historial", "¿Borrar el historial de conversación? Los recuerdos no se borrarán.", parent=self.root): return
        memory.borrar_historial(); self.messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]; self.chat.clear(); self._activity("Historial conversacional eliminado", "ok")

    # -- confirmaciones de seguridad --------------------------------------
    # IMPORTANTE (fix de concurrencia): este callback lo invoca ToolManager
    # desde el hilo del agente (_agent_worker), NUNCA desde el hilo principal
    # de Tkinter. Antes se llamaba aquí mismo a messagebox.askyesno(), lo cual
    # es inseguro (Tk no es thread-safe) y podía colgar o crashear la GUI.
    # Ahora delegamos el diálogo real al hilo principal vía la cola de
    # eventos y bloqueamos este hilo de fondo con un threading.Event puro
    # (sin tocar Tk) hasta que la persona responde.
    def _confirm_action(self, name, preview):
        result = {}; done = threading.Event()
        self.events.put(("confirm", (name, preview, result, done)))
        while not done.wait(0.1):
            if self.cancel_event.is_set():
                return False
        ans = bool(result.get("ok"))
        self.events.put(("status", "ACCIÓN CONFIRMADA" if ans else "ACCIÓN CANCELADA"))
        return ans

    def _privacy_confirm(self, name, destination, disclosure):
        result = {}; done = threading.Event()
        self.events.put(("privacy", (name, destination, disclosure, result, done)))
        while not done.wait(0.1):
            if self.cancel_event.is_set():
                return False
        return bool(result.get("ok"))

    def _cancel_current(self):
        if self.busy:
            self.cancel_event.set()
            self.status.set("CANCELANDO…")
            if self._pending_privacy_close:
                self._pending_privacy_close(False)
            if self._pending_confirm_close:
                self._pending_confirm_close(False)
        if self.speaking:
            self.speech_cancel_event.set()
            self.status.set("DETENIENDO VOZ…")
        if self.listening:
            self.voice_stop.set()
            self.status.set("DETENIENDO ESCUCHA…")

    def _apply_tool_groups(self, groups):
        self.agent.tools.enabled_tool_groups = set(groups)
        config.ENABLED_TOOL_GROUPS = set(groups)

    def _save_tool_groups(self):
        groups = sorted(group for group, variable in self.tool_group_vars.items() if variable.get())
        updated_settings = {**self.settings, "enabled_tool_groups": groups}
        try:
            save_settings(updated_settings)
        except OSError as exc:
            messagebox.showerror("Herramientas", f"No se pudieron guardar los grupos: {exc}", parent=self.root)
            return
        self.settings = updated_settings
        self._apply_tool_groups(groups)
        self.status.set("GRUPOS DE HERRAMIENTAS GUARDADOS")

    def _show_privacy_dialog(self, name, destination, disclosure, result, done):
        dialog = tk.Toplevel(self.root)
        dialog.title("Consentimiento de privacidad")
        dialog.transient(self.root); dialog.geometry("660x500"); dialog.minsize(480, 320)
        dialog.configure(bg=PANEL)
        tk.Label(dialog, text="DATOS QUE SALDRÁN DEL EQUIPO", bg=PANEL, fg=WARNING,
                 font=(FONT, 11, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(dialog, text=f"Acción: {name}\nDestino: {destination}", bg=PANEL, fg=TEXT,
                 justify="left", font=(FONT, 9)).pack(anchor="w", padx=16, pady=(0, 8))
        content = tk.Frame(dialog, bg=PANEL); content.pack(fill="both", expand=True, padx=16)
        details = tk.Text(content, wrap="word", bg="#08101b", fg=TEXT, relief="flat", padx=10, pady=8)
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=details.yview)
        details.configure(yscrollcommand=scrollbar.set)
        details.pack(side="left", fill="both", expand=True); scrollbar.pack(side="right", fill="y")
        details.insert("1.0", disclosure); details.configure(state="disabled")
        buttons = tk.Frame(dialog, bg=PANEL); buttons.pack(fill="x", padx=16, pady=12)

        def finish(approved):
            if not dialog.winfo_exists():
                return
            result["ok"] = approved
            self._pending_privacy_close = None
            dialog.destroy()
            done.set()

        self._pending_privacy_close = finish
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        HoverButton(buttons, "CANCELAR ENVÍO", command=lambda: finish(False), radius=8, bg_color="#4a1d2b",
                    hover_color="#6b2638", fg="#ffdce2", font=(FONT, 9, "bold"), padx=12, pady=7).pack(side="right", padx=(8, 0))
        HoverButton(buttons, "AUTORIZAR", command=lambda: finish(True), radius=8, bg_color=ACCENT,
                    hover_color=ACCENT_SOFT, fg="#03101a", font=(FONT, 9, "bold"), padx=12, pady=7).pack(side="right")
        dialog.grab_set()

    def _show_confirm_dialog(self, name, preview, result, done):
        dialog = tk.Toplevel(self.root)
        dialog.title("Confirmación de seguridad")
        dialog.transient(self.root); dialog.configure(bg=PANEL)
        tk.Label(dialog, text=f"Jarvis quiere ejecutar {name}:\n\n{preview}", bg=PANEL, fg=TEXT,
                 justify="left", wraplength=440, font=(FONT, 10)).pack(padx=18, pady=18)
        buttons = tk.Frame(dialog, bg=PANEL); buttons.pack(fill="x", padx=16, pady=(0, 14))

        def finish(approved):
            if not dialog.winfo_exists():
                return
            result["ok"] = approved
            self._pending_confirm_close = None
            dialog.destroy()
            done.set()

        self._pending_confirm_close = finish
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        HoverButton(buttons, "NO PERMITIR", command=lambda: finish(False), radius=8, bg_color="#4a1d2b",
                    hover_color="#6b2638", fg="#ffdce2", font=(FONT, 9, "bold"), padx=12, pady=7).pack(side="right", padx=(8, 0))
        HoverButton(buttons, "PERMITIR", command=lambda: finish(True), radius=8, bg_color=ACCENT,
                    hover_color=ACCENT_SOFT, fg="#03101a", font=(FONT, 9, "bold"), padx=12, pady=7).pack(side="right")
        dialog.grab_set()

    def _tool_event(self, event): self.events.put(("tool", event))

    def _send_text(self):
        if self.busy or self.speaking: return
        text = self.input.get("1.0", "end").strip()
        if not text: return
        self.input.delete("1.0", "end"); self._hide_palette()
        self._submit(text, bool(self.settings.get("speak_responses", True)))

    def _toggle_voice(self):
        if self.listening:
            self.voice_stop.set(); self.status.set("DETENIENDO ESCUCHA…"); return
        if self.busy or self.speaking: return
        self.listening = True; self.voice_stop.clear(); self.voice_button._labels[-1].configure(text="■ DETENER")
        threading.Thread(target=self._voice_loop, daemon=True).start()

    def _voice_loop(self):
        # Hilo de fondo: SOLO captura/transcribe audio (E/S pura, sin Tk).
        # El texto se entrega a la cola de eventos y es el hilo principal
        # quien decide cuándo llamar a _submit() (que sí toca widgets).
        try:
            import stt
            while not self.voice_stop.is_set():
                self.events.put(("status", "ESCUCHANDO…"))
                text = stt.grabar_hasta_silencio_y_transcribir(cancel_event=self.voice_stop)
                if self.voice_stop.is_set(): break
                if text.strip():
                    self.ready_event.clear()
                    self.events.put(("voice_text", text.strip()))
                    self.ready_event.wait()
                if not self.settings.get("continuous_voice", False): break
        except Exception as exc:
            self.events.put(("error", f"Error de voz: {exc}"))
        finally:
            self.events.put(("voice_done", None))

    def _submit(self, text, speak=False):
        if self.busy or self.speaking: return
        self.cancel_event.clear()
        self.busy = True; self.ready_event.clear(); self.status.set("JARVIS • PENSANDO"); self.send_btn._apply(DIM)
        self.cancel_btn.pack(fill="x", pady=(7, 0))
        self.voice_button.pack_forget()
        self.chat.add_bubble("user", text)
        memory.guardar_mensaje("user", text)
        outgoing = text
        if self.pending_directive:
            outgoing = text
            self.messages.append({"role": "system", "content": self.pending_directive})
            if self.mode == "Normal":  # comando "/" de un solo uso: se consume aquí
                self.pending_directive = None
                if self.mode_chip is not None: self.mode_chip.destroy(); self.mode_chip = None
        self.messages.append({"role": "user", "content": outgoing})
        self._thinking_stop = self.chat.add_thinking()
        threading.Thread(target=self._agent_worker, args=(speak,), daemon=True).start()

    def _stop_thinking(self):
        stop = self._thinking_stop
        self._thinking_stop = None
        if stop is not None:
            stop()

    def _agent_worker(self, speak):
        try:
            response = ""
            for chunk in self.agent.stream(
                self.messages,
                self.settings.get("model"),
                self.settings.get("ollama_url"),
                cancel_event=self.cancel_event,
            ): response += chunk
            response = response.strip()
            if response:
                memory.guardar_mensaje("assistant", response); self.messages.append({"role": "assistant", "content": response})
                self.events.put(("response", (response, speak and not self.agent.last_run.get("cancelled", False))))
            for record in self.agent.last_run.get("tool_results", []): memory.guardar_ejecucion_herramienta(record)
            if not response: self.events.put(("error", "Jarvis no devolvió una respuesta."))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("ready", None))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status": self.status.set(payload)
                elif kind == "confirm":
                    name, preview, result, done = payload
                    self._show_confirm_dialog(name, preview, result, done)
                elif kind == "privacy":
                    name, destination, disclosure, result, done = payload
                    self._show_privacy_dialog(name, destination, disclosure, result, done)
                elif kind == "voice_text":
                    self._submit(payload, True)
                elif kind == "tool":
                    e = payload; name = e.get("tool", "herramienta"); phase = e.get("phase", "")
                    if phase == "start": self._activity(f"▶ {name} · intento {e.get('attempt',1)}"); self.status.set(f"EJECUTANDO • {name}")
                    elif phase == "verify": self._activity(f"↳ {name} · verificando"); self.status.set(f"VERIFICANDO • {name}")
                    elif phase == "recovery": self._activity(f"↻ {name} · reintentando", "tool")
                    elif phase == "end": self._activity(f"■ {name} · {'OK' if e.get('success') else 'ERROR'} · {e.get('elapsed',0):.2f}s", "ok" if e.get('success') else "err")
                elif kind == "response":
                    self._stop_thinking()
                    response, speak = payload; self.chat.add_bubble("assistant", response, animate=True); self.status.set("RESPUESTA LISTA")
                    if speak:
                        self.speaking = True; self.speech_cancel_event = threading.Event()
                        self.send_btn._apply(DIM)
                        self.cancel_btn.pack(fill="x", pady=(7, 0)); self.voice_button.pack_forget()
                        self.status.set("REPRODUCIENDO VOZ…")
                        threading.Thread(target=self._speak_worker, args=(response, self.speech_cancel_event), daemon=True).start()
                elif kind == "error":
                    self._stop_thinking()
                    self.status.set("ERROR"); self._activity(payload, "err"); messagebox.showerror("Jarvis", payload, parent=self.root)
                elif kind == "ready":
                    self.busy = False
                    if not self.speaking:
                        self.cancel_btn.pack_forget(); self.voice_button.pack(fill="x", pady=(7, 0))
                    self.send_btn._apply(DIM if self.speaking else ACCENT)
                    self.status.set("REPRODUCIENDO VOZ…" if self.speaking else "SISTEMA LISTO" if not self.listening else "ESCUCHANDO…")
                    self.ready_event.set()
                elif kind == "speech_done":
                    self.speaking = False
                    if not self.busy:
                        self.cancel_btn.pack_forget(); self.voice_button.pack(fill="x", pady=(7, 0))
                        self.send_btn._apply(ACCENT)
                    self.status.set("SISTEMA LISTO" if not self.listening else "ESCUCHANDO…")
                elif kind == "voice_done":
                    self.listening = False; self.voice_button._labels[-1].configure(text="VOZ"); self.status.set("SISTEMA LISTO" if not self.busy else "PROCESANDO…")
        except queue.Empty:
            pass
        self.root.after(60, self._drain_events)

    def _speak_worker(self, text, cancel_event):
        try: import tts; tts.hablar(text, cancel_event=cancel_event)
        except Exception as exc: self.events.put(("error", f"TTS: {exc}"))
        finally: self.events.put(("speech_done", None))

    def _close(self):
        self.voice_stop.set()
        self.cancel_event.set()
        self.speech_cancel_event.set()
        if self._pending_privacy_close:
            self._pending_privacy_close(False)
        if self._pending_confirm_close:
            self._pending_confirm_close(False)
        self.root.destroy()


def launch_gui():
    root = tk.Tk()
    JarvisGUI(root)
    root.mainloop()
