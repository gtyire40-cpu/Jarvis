# Jarvis Local

Asistente personal para Linux que conecta un modelo local de Ollama con voz,
memoria, una interfaz gráfica y herramientas para interactuar con el escritorio.
El proyecto está en desarrollo; algunas funciones dependen del entorno de
escritorio y de programas externos.

## Funciones

- Conversación con modelos servidos por [Ollama](https://ollama.com/), con
  ejecución de herramientas y streaming.
- Interfaz gráfica y modos de texto y voz.
- Reconocimiento de voz con Faster-Whisper y síntesis con Piper.
- Memoria local y agenda almacenadas en SQLite.
- Herramientas para aplicaciones permitidas, archivos del usuario, navegador y
  escritorio.
- Verificación de resultados y confirmación de acciones sensibles.
- Detección de GPU y selección de un backend compatible para Whisper.

## Requisitos

- Linux de escritorio; el control gráfico está pensado principalmente para
  sesiones X11. Algunas funciones no están disponibles en Wayland.
- Python 3.12 para preparar el entorno automáticamente.
- Ollama instalado y en ejecución, con al menos un modelo descargado.
- Micrófono y salida de audio para usar las funciones de voz.
- Conexión a Internet durante la primera instalación para descargar paquetes,
  el modelo de voz y, cuando haga falta, modelos de Whisper.

Las capacidades de voz, OCR, automatización de ventanas y audio dependen de
herramientas o bibliotecas nativas adicionales. Consulta
[Instalación](docs/INSTALLATION.md).

## Inicio rápido

Clona el repositorio y ejecuta el lanzador desde su raíz:

```bash
git clone https://github.com/gtyire40-cpu/Jarvis.git
cd Jarvis
./dist/executable
```

El primer arranque prepara `.venv`, instala las dependencias runtime y obtiene
el modelo Piper español. Después abre la interfaz gráfica. Si prefieres
configurar opciones, copia `.env.example` a `.env` antes de iniciarlo:

```bash
cp .env.example .env
```

Para registrar Jarvis en el menú de aplicaciones:

```bash
./scripts/install.sh
```

El instalador copia el proyecto a `~/.local/share/jarvis` y crea el lanzador
`~/.local/bin/jarvis`. Para instalar en otra ubicación, define
`JARVIS_INSTALL_DIR` o `JARVIS_BIN_DIR` al ejecutar el script.

## Uso desde terminal

```bash
./.venv/bin/python main.py --gui
./.venv/bin/python main.py --modo texto
./.venv/bin/python main.py --modo voz
./.venv/bin/python main.py --modo voz --sin-wakeword
```

También se pueden pasar `--model NOMBRE` y `--ollama-url URL` para cambiar el
modelo o servidor solo durante esa ejecución. En modo voz, el wake word está
activado por defecto.

## Configuración y datos

Las variables de entorno se pueden establecer en `.env`; las variables ya
definidas en el proceso tienen prioridad. La interfaz también guarda sus
preferencias en `settings.json`. Consulta la
[guía de configuración](docs/CONFIGURATION.md).

Por defecto, la base de datos se guarda en `data/jarvis.db` y los registros en
`logs/`. Se pueden cambiar con variables de entorno. Estos archivos contienen
datos locales y no deben subirse al repositorio.

## Desarrollo

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pytest
```

Consulta la [guía de desarrollo](docs/DEVELOPMENT.md), la
[arquitectura](docs/ARCHITECTURE.md) y las
[consideraciones de seguridad](docs/SECURITY.md).

## Privacidad y seguridad

La conversación y la memoria se guardan localmente, pero las búsquedas web
envían la consulta al buscador y el correo usa el proveedor configurado.
Ollama, Faster-Whisper y Piper se ejecutan localmente una vez instalados sus
modelos. Revisa las confirmaciones antes de permitir acciones de escritorio o
modificaciones de archivos. Más información en
[Seguridad y privacidad](docs/SECURITY.md).

Consulta el [registro de cambios](docs/CHANGELOG.md).

## Licencia

El repositorio no incluye todavía un archivo de licencia. Hasta que se añada,
no asumas que el código puede redistribuirse o modificarse bajo una licencia
de código abierto.
