"""Punto de entrada de Jarvis Local."""
import argparse
import re
import config
import memory
import scheduler
from core.agent import Agent
from core.tool_manager import ToolManager
from core.security import SecurityManager
from logging_config import configure_logging

configure_logging()
SEPARADOR_FRASES = re.compile(r"(?<=[.!?¡¿])\s+")

def _confirm_cli(name, preview):
    answer = input(f"\n⚠️ Jarvis quiere ejecutar {preview}. ¿Confirmas? [s/N] ").strip().lower()
    return answer in ("s", "si", "sí", "y", "yes")

def _confirm_external(name, destination, disclosure):
    print(f"\n⚠️ {name} enviará datos a: {destination}")
    print("Contenido que se enviará:")
    print(disclosure)
    answer = input("¿Autorizar este envío? [s/N] ").strip().lower()
    return answer in ("s", "si", "sí", "y", "yes")

def build_agent(confirm_callback=None):
    return Agent(ToolManager(
        SecurityManager(),
        confirm_callback or _confirm_cli,
        privacy_callback=_confirm_external,
    ))

def _cargar_conversacion():
    return [{"role":"system", "content":config.SYSTEM_PROMPT}, *memory.cargar_historial()]

def modo_texto(model=None, ollama_url=None):
    memory.init_db(); scheduler.start(); messages = _cargar_conversacion(); agent = build_agent()
    print("Jarvis Local (texto). Escribe 'salir' para terminar.\n")
    while True:
        try: entrada = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt): break
        if entrada.lower() in ("salir", "exit", "quit"): break
        if not entrada: continue
        messages.append({"role":"user","content":entrada}); memory.guardar_mensaje("user", entrada)
        print("Jarvis: ", end="", flush=True); respuesta=""
        for chunk in agent.stream(messages, model, ollama_url): print(chunk, end="", flush=True); respuesta += chunk
        print("\n")
        if respuesta.strip():
            memory.guardar_mensaje("assistant", respuesta.strip())
        for record in agent.last_run.get("tool_results", []):
            memory.guardar_ejecucion_herramienta(record)

def modo_voz(usar_wakeword=True, model=None, ollama_url=None):
    import stt
    import tts
    memory.init_db(); scheduler.start(); messages = _cargar_conversacion(); agent = build_agent()
    print("Jarvis Local (voz). Ctrl+C para salir.\n")
    wakeword = None
    if usar_wakeword:
        import wakeword as _wakeword
        wakeword = _wakeword
    while True:
        try:
            if wakeword:
                wakeword.esperar_palabra_activacion()
            entrada = stt.grabar_hasta_silencio_y_transcribir()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"⚠️ Error de voz: {exc}")
            continue
        if not entrada or not entrada.strip():
            continue
        messages.append({"role":"user","content":entrada}); memory.guardar_mensaje("user",entrada)
        print("Jarvis: ", end="", flush=True); buffer=""; respuesta=""
        for chunk in agent.stream(messages, model, ollama_url):
            print(chunk,end="",flush=True); respuesta+=chunk; buffer+=chunk
            partes=SEPARADOR_FRASES.split(buffer)
            if len(partes)>1:
                for frase in partes[:-1]:
                    if frase.strip(): tts.hablar(frase.strip())
                buffer=partes[-1]
        if buffer.strip(): tts.hablar(buffer.strip())
        print("\n")
        if respuesta.strip(): memory.guardar_mensaje("assistant",respuesta.strip())
        for record in agent.last_run.get("tool_results", []):
            memory.guardar_ejecucion_herramienta(record)

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--modo",choices=["texto","voz"],default="texto"); p.add_argument("--sin-wakeword",action="store_true"); p.add_argument("--gui",action="store_true"); p.add_argument("--model"); p.add_argument("--ollama-url"); a=p.parse_args()
    if a.gui:
        from gui import launch_gui; launch_gui()
    elif a.modo=="texto": modo_texto(a.model,a.ollama_url)
    else: modo_voz(not a.sin_wakeword,a.model,a.ollama_url)
