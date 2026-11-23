"""Capa de automatización del ordenador para Jarvis.

Combina navegador, ventanas y visión para aportar contexto observable antes y
 después de acciones de interfaz. No toma decisiones peligrosas por su cuenta:
 las acciones siguen pasando por ToolManager y SecurityManager.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ComputerAgent:
    """Diagnóstico y contexto para tareas que interactúan con la interfaz."""

    UI_TOOLS = {
        "abrir_aplicacion", "cerrar_aplicacion", "enfocar_ventana",
        "mover_redimensionar_ventana", "mover_raton", "hacer_click",
        "escribir_en_escritorio", "pulsar_tecla", "click_elemento_visual",
        "navegador_abrir", "navegador_atras", "navegador_click_texto",
        "navegador_click_role", "navegador_escribir", "navegador_tecla",
        "navegador_cerrar",
    }

    def observe(self, include_visual: bool = False, prompt: str = "") -> dict[str, Any]:
        """Recoge un estado compacto del escritorio y del navegador."""
        context: dict[str, Any] = {}

        try:
            import tools
            windows = tools.listar_ventanas()
            context["ventanas"] = windows
        except Exception as exc:
            context["ventanas_error"] = str(exc)

        try:
            import tools
            browser = tools.navegador_estado()
            context["navegador"] = browser
        except Exception as exc:
            context["navegador_error"] = str(exc)

        try:
            from core.vision import VISION
            inspection = VISION.inspect(max_elements=80, include_visual=include_visual, prompt=prompt or None)
            context["pantalla"] = inspection
        except Exception as exc:
            context["pantalla_error"] = str(exc)

        return context

    def recovery_context(self, tool_name: str, reason: str) -> dict[str, Any]:
        """Obtiene información para que el siguiente ciclo del LLM pueda recuperarse."""
        if tool_name not in self.UI_TOOLS:
            return {"available": False, "reason": reason}

        include_visual = tool_name.startswith("navegador_") or "visual" in tool_name or tool_name in {
            "hacer_click", "escribir_en_escritorio", "pulsar_tecla", "enfocar_ventana"
        }
        context = self.observe(include_visual=include_visual, prompt=f"Diagnostica por qué falló la acción {tool_name}: {reason}")
        return {
            "available": True,
            "tool": tool_name,
            "reason": reason,
            "instruction": "Usa este contexto para elegir una alternativa o una nueva acción. No repitas ciegamente la misma acción.",
            "context": context,
        }
