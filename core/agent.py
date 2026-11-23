"""Orquestador de Jarvis con planificación, contexto persistente y recuperación."""
import config
import llm
import memory
from core.tool_manager import ToolManager
from core.planner import make_plan


class Agent:
    def __init__(self, tool_manager=None):
        self.tools = tool_manager or ToolManager()
        self.last_run = self.tools.last_run

    def _with_plan(self, messages, model=None, base_url=None):
        if not messages:
            return messages
        goal = messages[-1].get("content", "")
        if not goal:
            return messages

        context_text = ""
        if config.MEMORY_CONTEXT_RECALL:
            try:
                ctx = memory.contexto_relevante(
                    goal,
                    max_recuerdos=config.MEMORY_CONTEXT_MAX_RECALLS,
                )
                if ctx["recuerdos"] or ctx["tareas_pendientes"]:
                    context_text = (
                        "Contexto persistente relevante (solo lectura):\n"
                        + str({
                            "recuerdos": ctx["recuerdos"],
                            "tareas_pendientes": ctx["tareas_pendientes"],
                        })
                        + "\n\n"
                    )
            except Exception:
                context_text = ""

        plan_text = ""
        if len(goal) >= 20:
            try:
                steps = make_plan(goal, model=model, base_url=base_url)
            except Exception:
                steps = []
            if steps:
                plan_text = (
                    "Plan operativo (resumen):\n"
                    + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
                    + "\n\nRegla de ejecución: después de cada acción, usa su resultado de verificación. "
                      "Si una acción de interfaz falla, observa el estado actual y elige una alternativa; "
                      "no repitas ciegamente la misma acción.\n"
                )

        if not context_text and not plan_text:
            return messages
        injected = {"role": "system", "content": context_text + plan_text}
        if messages and messages[0].get("role") == "system":
            return [messages[0], injected, *messages[1:]]
        return [injected, *messages]

    def run(self, messages: list, model=None, base_url=None) -> str:
        result = llm.chat(self._with_plan(messages, model, base_url), tool_manager=self.tools, model=model, base_url=base_url)
        self.last_run = self.tools.last_run
        return result

    def stream(self, messages: list, model=None, base_url=None):
        for chunk in llm.chat_stream(self._with_plan(messages, model, base_url), tool_manager=self.tools, model=model, base_url=base_url):
            yield chunk
        self.last_run = self.tools.last_run
