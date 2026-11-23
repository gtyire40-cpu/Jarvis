"""
Palabra de activación ("Hey Jarvis") usando openWakeWord.
Escucha continuamente el micrófono en segundo plano hasta detectar la palabra clave.
"""

import importlib
import numpy as np
from typing import Any, Callable

_ModelFactory: Callable[..., Any] | None = None
try:
    _ModelFactory = importlib.import_module("openwakeword.model").Model
except ImportError as exc:
    _OPENWAKEWORD_IMPORT_ERROR = exc
else:
    _OPENWAKEWORD_IMPORT_ERROR = None

import config

FRAME_SAMPLES = 1280  # 80ms a 16kHz, tamaño que espera openWakeWord

_model = None


def _get_sounddevice():
    try:
        import sounddevice
        return sounddevice
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "El audio de entrada no está disponible: falta PortAudio. "
            "Instala la biblioteca de audio del sistema para usar la palabra "
            "de activación."
        ) from exc


def _get_model():
    global _model
    if _model is None:
        if _ModelFactory is None:
            raise RuntimeError(
                "La detección de palabra de activación requiere openwakeword. "
                "Instala una versión compatible con tu Python o usa --sin-wakeword."
            ) from _OPENWAKEWORD_IMPORT_ERROR
        print("[wakeword] Cargando modelo de palabra de activación...")
        _model = _ModelFactory(wakeword_models=[config.WAKE_WORD_MODEL])
    return _model


def esperar_palabra_activacion(cancel_event=None) -> bool:
    """Bloquea hasta que se detecta 'hey jarvis' en el micrófono."""
    sd = _get_sounddevice()
    model = _get_model()
    print(f'Escucha Esperando "hey jarvis"...')

    with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=FRAME_SAMPLES) as stream:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return False
            audio_chunk, _ = stream.read(FRAME_SAMPLES)
            if cancel_event is not None and cancel_event.is_set():
                return False
            audio_chunk = audio_chunk.flatten().astype(np.int16)
            prediction = model.predict(audio_chunk)
            score = prediction.get(config.WAKE_WORD_MODEL, 0.0)
            if score > config.WAKE_WORD_THRESHOLD:
                model.reset()
                print("✅ ¡Palabra de activación detectada!")
                return True
