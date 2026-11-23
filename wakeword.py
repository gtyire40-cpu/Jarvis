"""
Palabra de activación ("Hey Jarvis") usando openWakeWord.
Escucha continuamente el micrófono en segundo plano hasta detectar la palabra clave.
"""

import numpy as np
import sounddevice as sd
try:
    from openwakeword.model import Model
except ImportError:
    Model = None

import config

FRAME_SAMPLES = 1280  # 80ms a 16kHz, tamaño que espera openWakeWord

_model = None


def _get_model():
    global _model
    if _model is None:
        print("[wakeword] Cargando modelo de palabra de activación...")
        _model = Model(wakeword_models=[config.WAKE_WORD_MODEL])
    return _model


def esperar_palabra_activacion() -> None:
    """Bloquea hasta que se detecta 'hey jarvis' en el micrófono."""
    model = _get_model()
    print(f'Escucha Esperando "hey jarvis"...')

    with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=FRAME_SAMPLES) as stream:
        while True:
            audio_chunk, _ = stream.read(FRAME_SAMPLES)
            audio_chunk = audio_chunk.flatten().astype(np.int16)
            prediction = model.predict(audio_chunk)
            score = prediction.get(config.WAKE_WORD_MODEL, 0.0)
            if score > config.WAKE_WORD_THRESHOLD:
                model.reset()
                print("✅ ¡Palabra de activación detectada!")
                return
