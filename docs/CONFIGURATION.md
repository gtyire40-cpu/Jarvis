# Configuración

Jarvis carga `.env` desde la raíz del proyecto. Las variables del proceso
prevalecen sobre `.env`. La interfaz guarda preferencias en `settings.json`;
para la mayoría de los ajustes interactivos, esos valores pueden prevalecer
sobre los valores iniciales de `.env`.

Copia `.env.example` a `.env` y cambia solo lo necesario. No guardes
contraseñas reales en Git.

## Ollama y conversación

| Variable | Valor predeterminado | Descripción |
|---|---|---|
| `JARVIS_OLLAMA_URL` | `http://localhost:11434` | URL base del servidor Ollama |
| `JARVIS_MODEL` | `qwen2.5:7b` | Modelo de chat |
| `JARVIS_VISION_MODEL` | El modelo de chat | Modelo multimodal opcional |
| `JARVIS_OLLAMA_TIMEOUT` | `120` | Timeout HTTP en segundos |
| `JARVIS_MAX_TOOL_ITERATIONS` | `8` | Máximo de turnos de herramienta |
| `JARVIS_TEMPERATURE` | `0.2` | Temperatura enviada a Ollama |
| `JARVIS_MAX_RECOVERY_RETRIES` | `2` | Reintentos de verificación recuperables |

## Voz

| Variable | Valor predeterminado | Descripción |
|---|---|---|
| `JARVIS_WHISPER_MODEL` | `small` | Tamaño/modelo de Faster-Whisper |
| `JARVIS_WHISPER_DEVICE` | `auto` | Dispositivo solicitado para Whisper |
| `JARVIS_WHISPER_COMPUTE_TYPE` | `auto` | Tipo de cómputo solicitado |
| `JARVIS_WAKE_WORD_MODEL` | `hey_jarvis` | Modelo de palabra de activación |
| `JARVIS_WAKE_WORD_THRESHOLD` | `0.5` | Umbral de detección |
| `JARVIS_RECORD_SECONDS` | `6` | Duración para grabación fija |
| `JARVIS_VOICE_MAX_SECONDS` | `20` | Duración máxima de una captura por voz |
| `JARVIS_VOICE_SILENCE_SECONDS` | `1.0` | Silencio que finaliza la grabación |
| `JARVIS_VOICE_RMS_THRESHOLD` | `0.015` | Umbral de energía de voz |
| `JARVIS_VOICE_BLOCK_MS` | `30` | Tamaño de bloque de captura |
| `JARVIS_VOICE_PRE_ROLL_MS` | `240` | Audio previo que se conserva al detectar voz |

El dispositivo efectivo de Whisper también depende del soporte real disponible
en CTranslate2 y del hardware. Jarvis puede recurrir a CPU si no se puede usar
la GPU.

## Piper y reproducción

| Variable | Valor predeterminado | Descripción |
|---|---|---|
| `JARVIS_PIPER_BINARY` | `.venv/bin/piper` | Ruta al ejecutable Piper |
| `JARVIS_PIPER_VOICE` | `resources/voices/es_ES-davefx-medium.onnx` | Modelo de voz |
| `JARVIS_AUDIO_PLAYER` | `auto` | `auto`, `direct`, `paplay`, `aplay` o `ffplay` |

El bootstrap descarga el modelo si no está presente.

## Datos y memoria

| Variable | Valor predeterminado | Descripción |
|---|---|---|
| `JARVIS_HOME_DIR` | `~` | Límite base para herramientas de archivos |
| `JARVIS_APP_DIR` | Carpeta del proyecto | Raíz usada para datos e instalación |
| `JARVIS_DATA_DIR` | `APP_DIR/data` | Datos locales |
| `JARVIS_LOGS_DIR` | `APP_DIR/logs` | Registros |
| `JARVIS_DB_PATH` | `DATA_DIR/jarvis.db` | Base SQLite |
| `JARVIS_HISTORY_MAX` | `40` | Mensajes de conversación cargados |
| `JARVIS_MEMORY_AUTO_SAVE` | `false` | Guardado automático de recuerdos |
| `JARVIS_MEMORY_CONTEXT_RECALL` | `true` | Recuperar recuerdos/tareas relevantes |
| `JARVIS_MEMORY_CONTEXT_MAX_RECALLS` | `8` | Máximo de recuerdos de contexto |
| `JARVIS_REMINDER_POLL_SECONDS` | `15` | Intervalo de comprobación de recordatorios |

`JARVIS_MAX_SEARCH_RESULTS` (predeterminado `15`) limita resultados en la
búsqueda local de archivos.

## Aplicaciones instaladas

Jarvis descubre las aplicaciones gráficas publicadas en los menús `.desktop`
del usuario, la distribución, Snap y Flatpak. Puede abrirlas por su nombre
visible en el menú, comprobar si están ejecutándose y cerrarlas. Para Flatpak,
la consulta y el cierre se limitan al identificador exacto de la aplicación.
`JARVIS_ALLOWED_APPS` se conserva únicamente como compatibilidad para los
nombres antiguos que no tengan un archivo `.desktop`; no limita las
aplicaciones descubiertas. Jarvis no ejecuta comandos arbitrarios escritos en
el chat.

## Correo y música

| Variable | Valor predeterminado | Descripción |
|---|---|---|
| `JARVIS_EMAIL_ADDRESS` | Vacío | Cuenta usada por IMAP/SMTP |
| `JARVIS_EMAIL_PASSWORD` | Vacío | Credencial de la cuenta |
| `JARVIS_IMAP_SERVER` / `JARVIS_IMAP_PORT` | `imap.gmail.com` / `993` | Servidor de entrada |
| `JARVIS_SMTP_SERVER` / `JARVIS_SMTP_PORT` | `smtp.gmail.com` / `587` | Servidor de salida |
| `JARVIS_MUSIC_PLAYER` | Vacío | Reproductor para `playerctl`; vacío usa el predeterminado |

Usa una contraseña de aplicación o el mecanismo recomendado por tu proveedor.
No compartas ni publiques el archivo `.env`.

## Ajustes de la interfaz

La GUI mantiene varios ajustes en `settings.json`, incluyendo modelo, URL de
Ollama, temperatura, pasos máximos, historial, opciones de voz y actividad.
La edición manual de `.env` puede no reemplazar valores previamente guardados
en `settings.json`; elimina o respalda ese archivo si quieres que la GUI
vuelva a cargar valores iniciales.

Los grupos de herramientas se pueden activar desde la página **Herramientas**
de la GUI o configurar con `JARVIS_ENABLED_TOOL_GROUPS`, una lista separada
por comas: `web,browser,desktop,files,email,media,memory`. Todos están
habilitados por defecto. La selección de la interfaz se guarda en
`settings.json`.
