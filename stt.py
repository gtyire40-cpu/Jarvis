"""Reconocimiento de voz local con faster-whisper y detección simple de voz/silencio."""
import logging
import tempfile
import time

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as write_wav

import config
import gpu_runtime

logger = logging.getLogger(__name__)
SAMPLE_RATE = 16000
_model = None


def _get_model():
    global _model
    if _model is None:
        logger.info("Cargando modelo Whisper...")
        gpu_runtime.prepare_cuda_runtime()
        from faster_whisper import WhisperModel
        device, compute_type, gpu = gpu_runtime.detect_whisper_runtime()
        logger.info("Whisper runtime: device=%s compute=%s nvidia=%s", device, compute_type, gpu)
        try:
            _model = WhisperModel(config.WHISPER_MODEL_SIZE, device=device, compute_type=compute_type)
        except Exception:
            if device != "cpu":
                logger.exception("No se pudo iniciar Whisper en GPU; usando CPU.")
                _model = WhisperModel(config.WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
            else:
                raise
    return _model


def _transcribir_audio(audio: np.ndarray) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name
        write_wav(path, SAMPLE_RATE, audio.astype(np.int16))
    try:
        segments, _ = _get_model().transcribe(path, language="es", vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments if seg.text and seg.text.strip())
    finally:
        import os
        try: os.unlink(path)
        except OSError: pass


def _rms(block: np.ndarray) -> float:
    x = block.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(x * x)) + 1e-9)


def grabar_duracion_fija_y_transcribir(segundos: float = None) -> str:
    segundos = float(segundos or config.GRABACION_SEGUNDOS)
    print(f"Voz️ Escuchando hasta {segundos:.0f}s...")
    audio = sd.rec(int(segundos * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    texto = _transcribir_audio(audio.reshape(-1))
    print(f"Texto Transcrito: {texto}")
    return texto


def grabar_hasta_silencio_y_transcribir(max_seconds: float = None, silence_seconds: float = None) -> str:
    """Graba desde que hay voz hasta detectar silencio sostenido, sin duración fija obligatoria."""
    max_seconds = float(max_seconds or config.VOICE_MAX_SECONDS)
    silence_seconds = float(silence_seconds or config.VOICE_SILENCE_SECONDS)
    threshold = float(config.VOICE_RMS_THRESHOLD)
    blocksize = int(config.VOICE_BLOCK_MS * SAMPLE_RATE / 1000)
    pre_blocks = max(1, int(config.VOICE_PRE_ROLL_MS / config.VOICE_BLOCK_MS))
    max_blocks = max(1, int(max_seconds * 1000 / config.VOICE_BLOCK_MS))
    silence_blocks_needed = max(1, int(silence_seconds * 1000 / config.VOICE_BLOCK_MS))

    frames = []
    recent = []
    started = False
    silent = 0
    started_at = time.monotonic()
    print("Voz️ Esperando voz...")
    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=blocksize)
        stream.start()
    except Exception as exc:
        raise RuntimeError(f"No pude iniciar el microfono: {exc}") from exc
    try:
        for _ in range(max_blocks):
            block, _ = stream.read(blocksize)
            block = block.reshape(-1).copy()
            level = _rms(block)
            recent.append(block)
            if len(recent) > pre_blocks:
                recent.pop(0)

            if not started:
                if level >= threshold:
                    started = True
                    frames.extend(recent)
                    recent.clear()
                    silent = 0
                    print("Voz️ Grabando...")
                continue

            frames.append(block)
            if level < threshold:
                silent += 1
                if silent >= silence_blocks_needed:
                    break
            else:
                silent = 0

            if time.monotonic() - started_at >= max_seconds:
                break
    finally:
        stream.stop()
        stream.close()

    if not frames:
        return ""
    audio = np.concatenate(frames)
    texto = _transcribir_audio(audio)
    print(f"Texto Transcrito: {texto}")
    return texto


def grabar_y_transcribir() -> str:
    input("Pulsa ENTER y habla...")
    return grabar_hasta_silencio_y_transcribir()
