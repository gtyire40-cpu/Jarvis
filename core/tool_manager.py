import logging
import time
import tools
import config
from core.results import ToolResult
from core.security import SecurityManager
from core.verifier import Verifier
from core.computer_agent import ComputerAgent

logger = logging.getLogger(__name__)

class ToolManager:
    def __init__(
        self,
        security=None,
        confirm_callback=None,
        event_callback=None,
        verifier=None,
        max_retries=None,
        privacy_callback=None,
        enabled_tool_groups=None,
    ):
        self.security = security or SecurityManager()
        self.confirm_callback = confirm_callback
        self.event_callback = event_callback
        self.privacy_callback = privacy_callback
        self.verifier = verifier or Verifier()
        self.computer = ComputerAgent()
        self.max_retries = config.MAX_RECOVERY_RETRIES if max_retries is None else max(0, int(max_retries))
        groups = config.ENABLED_TOOL_GROUPS if enabled_tool_groups is None else enabled_tool_groups
        self.enabled_tool_groups = set(groups) & set(tools.TOOL_GROUPS)
        self.cancel_event = None
        uncategorized = set(tools.DISPATCH) - set(tools.TOOL_TO_GROUP)
        if uncategorized:
            raise RuntimeError(f"Hay herramientas sin grupo asignado: {', '.join(sorted(uncategorized))}")
        # Evidencia de ejecución de la conversación actual. Solo llm.py la llena
        # cuando Ollama emite tool_calls reales.
        self.last_run = {"tool_calls": [], "tool_results": [], "tool_call_count": 0}

    def _emit(self, event):
        if self.event_callback:
            try:
                self.event_callback(event)
            except Exception:
                logger.exception("El callback de herramientas falló")

    @property
    def schemas(self):
        return [
            schema for schema in tools.TOOL_SCHEMAS
            if tools.TOOL_TO_GROUP.get(schema["function"]["name"]) in self.enabled_tool_groups
        ]

    def approve_external(self, name, destination, disclosure):
        if self.privacy_callback is None:
            logger.warning("Envío externo bloqueado sin callback de privacidad: %s", name)
            return False
        return bool(self.privacy_callback(name, destination, disclosure))

    def _cancelled(self):
        return self.cancel_event is not None and self.cancel_event.is_set()

    def execute(self, name: str, args: dict | None = None) -> ToolResult:
        args = args or {}
        fn = tools.DISPATCH.get(name)
        if fn is None:
            return ToolResult(False, name, error=f"Herramienta desconocida: {name}")
        if not isinstance(args, dict):
            return ToolResult(False, name, error="Los argumentos deben ser un objeto JSON.")
        group = tools.TOOL_TO_GROUP.get(name)
        if group is None:
            return ToolResult(False, name, error="La herramienta no tiene un grupo asignado.")
        if group not in self.enabled_tool_groups:
            return ToolResult(False, name, error=f"El grupo de herramientas '{group}' está desactivado.")
        if self._cancelled():
            return ToolResult(False, name, error="Operación cancelada antes de iniciar la herramienta.")

        from core.privacy import tool_disclosure
        disclosure = tool_disclosure(name, args)
        if disclosure:
            destination, details = disclosure
            if not self.approve_external(name, destination, details):
                return ToolResult(False, name, error="Envío externo cancelado o no autorizado.")

        policy = self.security.policy_for(name)
        preview = f"{name}({args})"
        if self._cancelled():
            return ToolResult(False, name, error="Operación cancelada antes de iniciar la herramienta.")
        if policy.confirmation and not self.security.approve(name, self.confirm_callback, preview):
            return ToolResult(False, name, message="Acción cancelada: requiere confirmación.", requires_confirmation=True)

        attempts = 0
        last_result = None
        while attempts <= self.max_retries:
            attempts += 1
            started = time.perf_counter()
            self._emit({"phase": "start", "tool": name, "attempt": attempts})
            try:
                raw = fn(**args)
                elapsed = time.perf_counter() - started
                if isinstance(raw, ToolResult):
                    result = raw
                else:
                    result = ToolResult(True, name, message=str(raw), data=raw)

                verification = self.verifier.verify(name, args, result)
                result.data = {
                    "result": result.data,
                    "verification": {
                        "verified": verification.verified,
                        "reason": verification.reason,
                        "attempt": attempts,
                    },
                }
                if verification.verified:
                    result.message = f"{result.message} Verificación: {verification.reason}".strip()
                    logger.info("tool=%s success verified=%s attempt=%d elapsed=%.3fs", name, True, attempts, elapsed)
                    self._emit({"phase": "end", "tool": name, "success": True, "verified": True, "attempt": attempts, "elapsed": elapsed})
                    return result

                result.success = False
                result.error = verification.reason
                last_result = result
                logger.warning("tool=%s verification failed attempt=%d retryable=%s", name, attempts, verification.retryable)
                self._emit({"phase": "verify", "tool": name, "success": False, "retryable": verification.retryable, "attempt": attempts, "elapsed": elapsed})
                if not verification.retryable or attempts > self.max_retries:
                    self._emit({"phase": "end", "tool": name, "success": False, "verified": False, "attempt": attempts, "elapsed": elapsed})
                    return result
                if self._cancelled():
                    self._emit({"phase": "end", "tool": name, "success": False, "verified": False, "attempt": attempts, "elapsed": elapsed, "cancelled": True})
                    return result

                # En acciones de interfaz, observa el estado real y devuelve el diagnóstico
                # al LLM. Así la recuperación es adaptativa en vez de repetir ciegamente.
                recovery = self.computer.recovery_context(name, verification.reason)
                if recovery.get("available"):
                    result.data["recovery_context"] = recovery
                    self._emit({"phase": "recovery", "tool": name, "attempt": attempts, "reason": verification.reason, "context": recovery})
                else:
                    self._emit({"phase": "recovery", "tool": name, "attempt": attempts + 1, "reason": verification.reason})
                continue

            except Exception as exc:
                elapsed = time.perf_counter() - started
                result = ToolResult(False, name, error=str(exc))
                last_result = result
                retryable = (
                    not policy.confirmation
                    and not self._cancelled()
                    and self.verifier.is_retryable_error(str(exc))
                )
                logger.exception("tool=%s failed attempt=%d retryable=%s elapsed=%.3fs", name, attempts, retryable, elapsed)
                if retryable and attempts <= self.max_retries:
                    # No emitimos "end" todavía: la ejecución sigue en curso (se va a
                    # reintentar), y marcarla como finalizada aquí hacía que la
                    # Actividad mostrara un "ERROR" falso justo antes de que el
                    # reintento tuviera éxito.
                    recovery = self.computer.recovery_context(name, str(exc))
                    if recovery.get("available"):
                        result.data = {"recovery_context": recovery}
                        self._emit({"phase": "recovery", "tool": name, "attempt": attempts, "reason": str(exc), "context": recovery})
                    else:
                        self._emit({"phase": "recovery", "tool": name, "attempt": attempts + 1, "reason": str(exc)})
                    continue
                self._emit({"phase": "end", "tool": name, "success": False, "retryable": retryable, "attempt": attempts, "elapsed": elapsed, "error": str(exc)})
                return result

        return last_result or ToolResult(False, name, error="La herramienta no pudo completarse.")
