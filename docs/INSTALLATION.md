# Instalación

## Preparación automática

En Linux, desde la raíz del proyecto:

```bash
./dist/executable
```

El lanzador ejecuta `bootstrap.py`. En el primer inicio prepara un entorno
virtual Python, instala `requirements_runtime.txt`, instala paquetes
específicos de NVIDIA cuando detecta una GPU NVIDIA, descarga el modelo de voz
Piper y comprueba los componentes. Después inicia la GUI.

Se necesita Python 3.12 accesible como `python3.12`. Si el entorno está
incompleto, el bootstrap intenta recrearlo. La instalación requiere conexión a
Internet y espacio para dependencias y modelos de voz/Whisper.

## Requisitos del sistema

La lista exacta depende de las funciones que se quieran utilizar:

| Función | Dependencia del sistema |
|---|---|
| Control de ratón y teclado | `xdotool` |
| Listar, enfocar y mover ventanas | `wmctrl` y un gestor de ventanas compatible |
| OCR y clicks por texto | Tesseract OCR y el paquete de idioma correspondiente |
| Control de volumen | `amixer` (ALSA) |
| Control de reproductores | `playerctl` y un reproductor compatible |
| Instalador de escritorio | `rsync` |
| Audio en Linux | Dispositivo de audio y bibliotecas de audio de la distribución |
| Navegador automatizado | Playwright y Chromium; el navegador puede instalarse por separado |

En Debian/Ubuntu, una base habitual es:

```bash
sudo apt install xdotool wmctrl tesseract-ocr alsa-utils playerctl
```

Instala solo lo que necesites. La disponibilidad de `xdotool` y `wmctrl`
depende de la sesión gráfica; no se garantiza control de escritorio completo
en Wayland.

## Ollama

Instala Ollama siguiendo su documentación oficial, inicia el servicio y
descarga el modelo que quieras usar. Por ejemplo:

```bash
ollama pull qwen2.5:7b
ollama list
```

El modelo configurado por defecto es `qwen2.5:7b`. Cambia `JARVIS_MODEL` si
usas otro. Para servidores remotos o puertos distintos, configura
`JARVIS_OLLAMA_URL`.

## Instalación del lanzador de escritorio

```bash
./scripts/install.sh
```

El script usa `rsync` para copiar el proyecto a
`~/.local/share/jarvis`, crea un wrapper en `~/.local/bin/jarvis` y registra
un archivo `.desktop`. Omite `.env`, `settings.json`, `data/`, `logs/`, el
entorno virtual y las pruebas; así no copia preferencias ni datos personales
desde la carpeta de desarrollo. Asegúrate de que `~/.local/bin` esté en tu
`PATH`.

El instalador coloca el lanzador x86_64 en la ruta interna que espera el
bootstrap. Para reconstruirlo desde el código fuente, ejecuta
`./scripts/build_launcher.sh` en una máquina Linux x86_64 con compilador C.

Variables opcionales:

- `JARVIS_INSTALL_DIR`: carpeta de instalación.
- `JARVIS_BIN_DIR`: carpeta del comando `jarvis`.
- `XDG_DATA_HOME`: ubicación de los datos de escritorio del usuario.

Al reinstalar, el script sincroniza el código con `rsync --delete`. Los
directorios locales `data/` y `logs/`, y el archivo `settings.json` existente
en la instalación, se conservan. Aun así, haz copias de seguridad regulares.

## Instalación para desarrollo

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

`requirements_runtime.txt` contiene las dependencias usadas por el bootstrap.
`requirements.txt` añade herramientas de desarrollo y empaquetado.

## Resolución de problemas

### Ollama no responde

Comprueba que el servicio está activo, que la URL de Ollama es correcta y que
el modelo aparece en `ollama list`.

### No se detecta el micrófono

Comprueba los permisos y dispositivos de audio del sistema. `sounddevice`
requiere una instalación de PortAudio compatible con la distribución.

### No se reproduce la voz

Comprueba que Piper y el modelo español estén instalados. Jarvis intenta
reproducir con `sounddevice` y después puede recurrir a `paplay`, `aplay` o
`ffplay`. Puedes elegir un reproductor con `JARVIS_AUDIO_PLAYER`.

### No funciona OCR

Instala Tesseract y su idioma español; las dependencias Python por sí solas no
instalan el ejecutable del sistema.

### El control de escritorio no funciona

Comprueba que `xdotool`/`wmctrl` estén instalados y que la sesión gráfica sea
compatible. Algunas funciones requieren que la ventana objetivo esté visible.

### Revisar registros

El bootstrap escribe en `~/.jarvis/bootstrap.log`; los registros de la
aplicación se guardan en la carpeta `logs/` configurada.
