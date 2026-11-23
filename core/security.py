from dataclasses import dataclass
from enum import IntEnum
import logging

logger = logging.getLogger(__name__)

class Risk(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3

@dataclass(frozen=True)
class ToolPolicy:
    risk: Risk
    confirmation: bool = False

class SecurityManager:
    def __init__(self):
        self.policies = {
            "obtener_fecha_hora": ToolPolicy(Risk.LOW),
            "estado_sistema": ToolPolicy(Risk.LOW),
            "listar_aplicaciones_permitidas": ToolPolicy(Risk.LOW),
            "buscar_en_web": ToolPolicy(Risk.LOW),
            "leer_pagina_web": ToolPolicy(Risk.LOW),
            "abrir_url": ToolPolicy(Risk.LOW),
            "buscar_archivos": ToolPolicy(Risk.MEDIUM),
            "listar_archivos": ToolPolicy(Risk.MEDIUM),
            "abrir_aplicacion": ToolPolicy(Risk.LOW),
            "comprobar_aplicacion": ToolPolicy(Risk.LOW),
            "crear_carpeta": ToolPolicy(Risk.HIGH, True),
            "leer_archivo": ToolPolicy(Risk.MEDIUM),
            "capturar_pantalla": ToolPolicy(Risk.MEDIUM),
            "uso_ram": ToolPolicy(Risk.LOW),
            "espacio_libre_disco": ToolPolicy(Risk.LOW),
            "controlar_volumen": ToolPolicy(Risk.LOW),
            "controlar_musica": ToolPolicy(Risk.LOW),
            "leer_correos": ToolPolicy(Risk.MEDIUM),
            "agendar_evento": ToolPolicy(Risk.MEDIUM),
            "listar_eventos": ToolPolicy(Risk.LOW),
            "enviar_correo": ToolPolicy(Risk.HIGH, True),
            "crear_archivo": ToolPolicy(Risk.HIGH, True),
            "modificar_archivo": ToolPolicy(Risk.HIGH, True),
            "eliminar_archivo": ToolPolicy(Risk.CRITICAL, True),
            "cerrar_aplicacion": ToolPolicy(Risk.HIGH, True),
            "listar_procesos": ToolPolicy(Risk.LOW),
            "obtener_proceso": ToolPolicy(Risk.LOW),
            "guardar_recuerdo": ToolPolicy(Risk.MEDIUM),
            "buscar_recuerdos": ToolPolicy(Risk.LOW),
            "borrar_recuerdo": ToolPolicy(Risk.HIGH, True),
            "crear_recordatorio": ToolPolicy(Risk.MEDIUM),
            "listar_recordatorios": ToolPolicy(Risk.LOW),
            "completar_recordatorio": ToolPolicy(Risk.MEDIUM),
            "listar_ventanas": ToolPolicy(Risk.LOW),
            "enfocar_ventana": ToolPolicy(Risk.MEDIUM),
            "mover_redimensionar_ventana": ToolPolicy(Risk.MEDIUM),
            "crear_tarea": ToolPolicy(Risk.MEDIUM),
            "listar_tareas": ToolPolicy(Risk.LOW),
            "actualizar_tarea": ToolPolicy(Risk.MEDIUM),
            "completar_tarea": ToolPolicy(Risk.MEDIUM),
            "cancelar_tarea": ToolPolicy(Risk.MEDIUM),
            "obtener_contexto_relevante": ToolPolicy(Risk.LOW),
            "obtener_posicion_raton": ToolPolicy(Risk.LOW),
            "obtener_tamano_pantalla": ToolPolicy(Risk.LOW),
            "mover_raton": ToolPolicy(Risk.MEDIUM),
            "hacer_click": ToolPolicy(Risk.HIGH, True),
            "escribir_en_escritorio": ToolPolicy(Risk.HIGH, True),
            "pulsar_tecla": ToolPolicy(Risk.HIGH, True),
            "observar_pantalla": ToolPolicy(Risk.LOW),
            "analizar_pantalla": ToolPolicy(Risk.LOW),
            "buscar_elemento_visual": ToolPolicy(Risk.LOW),
            "esperar_elemento_visual": ToolPolicy(Risk.LOW),
            "click_elemento_visual": ToolPolicy(Risk.HIGH, True),
            "hacer_click_en_texto": ToolPolicy(Risk.HIGH, True),
            "navegador_abrir": ToolPolicy(Risk.LOW),
            "navegador_atras": ToolPolicy(Risk.LOW),
            "navegador_click_texto": ToolPolicy(Risk.HIGH, True),
            "navegador_click_role": ToolPolicy(Risk.HIGH, True),
            "navegador_escribir": ToolPolicy(Risk.HIGH, True),
            "navegador_tecla": ToolPolicy(Risk.HIGH, True),
            "navegador_extraer": ToolPolicy(Risk.LOW),
            "navegador_estado": ToolPolicy(Risk.LOW),
            "navegador_cerrar": ToolPolicy(Risk.MEDIUM, True),
        }

    def policy_for(self, name: str) -> ToolPolicy:
        return self.policies.get(name, ToolPolicy(Risk.HIGH, True))

    def needs_confirmation(self, name: str) -> bool:
        return self.policy_for(name).confirmation

    def approve(self, name: str, confirm_callback=None, preview: str = "") -> bool:
        if not self.needs_confirmation(name):
            return True
        if confirm_callback is None:
            logger.warning("Acción bloqueada sin confirmación: %s", name)
            return False
        return bool(confirm_callback(name, preview))
