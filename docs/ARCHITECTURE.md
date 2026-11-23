# Arquitectura

Jarvis es una aplicación Python local organizada alrededor de un agente, un
registro de herramientas y adaptadores para los servicios del sistema.

## Flujo de una conversación

1. `main.py` o `gui.py` carga el historial y recibe la entrada.
2. `core/agent.py` combina el objetivo con contexto y planificación opcionales.
3. `llm.py` llama al endpoint `/api/chat` de Ollama y procesa respuestas o
   llamadas de herramientas.
4. `core/tool_manager.py` valida el nombre de herramienta, consulta la política
   de seguridad, solicita confirmación cuando corresponde y ejecuta/verifica.
5. `core/verifier.py` valida resultados observables y determina si es seguro
   reintentar.
6. `memory.py` persiste conversación, recuerdos, tareas y evidencias en SQLite.

## Módulos principales

| Ruta | Responsabilidad |
|---|---|
| `main.py` | Entradas de terminal, texto y voz |
| `gui.py` | Interfaz Tkinter y ciclo de eventos |
| `config.py` | Configuración de entorno y valores predeterminados |
| `llm.py` | Cliente Ollama, streaming y tool calls |
| `tools.py` | Implementación y esquemas de herramientas |
| `memory.py` | Historial, SQLite, recuerdos, tareas y recordatorios |
| `scheduler.py` | Servicio de recordatorios |
| `stt.py` / `tts.py` / `wakeword.py` | Voz de entrada, salida y activación |
| `gpu_runtime.py` | Detección de GPU y preparación del runtime |
| `core/security.py` | Políticas de riesgo y confirmaciones |
| `core/tool_manager.py` | Ejecución, recuperación y trazabilidad |
| `core/browser_agent.py` | Sesión Playwright |
| `core/vision.py` | Análisis visual del escritorio |
| `bootstrap.py` | Preparación inicial del entorno y arranque gráfico |

## Directorios

- `core/`: coordinación de agente, seguridad y verificación.
- `docs/`: guías de usuario y desarrollo.
- `resources/`: iconos y modelos de voz locales.
- `scripts/`: instalación del lanzador de escritorio.
- `tests/`: pruebas automáticas.
- `dist/`: lanzadores y binarios distribuidos.
- `data/` y `logs/`: datos y registros creados al ejecutar; no se versionan.

## Extender herramientas

Para añadir una herramienta:

1. Implementa una función en `tools.py` con validación explícita de entradas.
2. Añádela a `DISPATCH`.
3. Declara sus parámetros y uso en `TOOL_SCHEMAS`.
4. Añade una política en `core/security.py`. Las acciones de escritura,
   control del escritorio o envío de información requieren especial cuidado y
   normalmente confirmación.
5. Añade verificación explícita en `core/verifier.py` si puede cambiar estado.
6. Añade pruebas que comprueben comportamiento y consistencia.

Las pruebas aseguran que todas las herramientas tengan esquema y política.
