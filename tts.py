"""Síntesis de voz local con Piper, con reproducción directa por sounddevice."""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _find_piper():
    candidates = []
    configured = getattr(config, 'PIPER_BINARY', '')
    if configured:
        candidates.append(Path(os.path.expanduser(configured)))
    candidates += [
        Path(config.APP_DIR) / '.venv' / 'bin' / 'piper',
        Path(__file__).resolve().parent / '.venv' / 'bin' / 'piper',
    ]
    found = shutil.which('piper')
    if found:
        candidates.append(Path(found))
    for p in candidates:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    raise FileNotFoundError('No encuentro Piper. El primer arranque debe completar la instalación.')


def _find_model():
    candidates = [
        Path(os.path.expanduser(config.PIPER_VOICE_MODEL)),
        Path(config.APP_DIR) / 'resources' / 'voices' / 'es_ES-davefx-medium.onnx',
        Path(config.APP_DIR) / 'voices' / 'es_ES-davefx-medium.onnx',
        Path(__file__).resolve().parent / 'voices' / 'es_ES-davefx-medium.onnx',
        Path.home() / '.jarvis' / 'voices' / 'es_ES-davefx-medium.onnx',
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    raise FileNotFoundError('No encuentro el modelo de voz de Piper (es_ES-davefx-medium.onnx).')


def _play_wav(path):
    direct_error = None
    # Preferimos reproducción directa para no depender de aplay/paplay.
    if getattr(config, 'PIPER_AUDIO_PLAYER', 'auto') in ('auto', 'direct'):
        try:
            import sounddevice as sd
            import soundfile as sf
            data, rate = sf.read(path, dtype='float32')
            sd.play(data, rate)
            sd.wait()
            return
        except Exception as exc:
            direct_error = exc
            logger.debug('Reproducción directa no disponible: %s', exc)

    preferred = getattr(config, 'PIPER_AUDIO_PLAYER', 'auto')
    candidates = (preferred,) if preferred not in ('', 'auto', 'direct') else ('paplay', 'aplay', 'ffplay')
    for candidate in candidates:
        if shutil.which(candidate):
            cmd = [candidate, path] if candidate != 'ffplay' else [candidate, '-nodisp', '-autoexit', '-loglevel', 'error', path]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
            return
    raise RuntimeError('No encuentro un reproductor de audio compatible.')


def hablar(texto: str) -> None:
    texto = (texto or '').strip()
    if not texto:
        return
    model = _find_model()
    piper = _find_piper()
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        wav = tmp.name
    try:
        proc = subprocess.run(
            [piper, '--model', model, '--output_file', wav],
            input=texto.encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode('utf-8', 'replace').strip() or 'Piper devolvió un error.')
        _play_wav(wav)
    except Exception as exc:
        logger.exception('Error de TTS')
        raise RuntimeError(f'No pude reproducir la respuesta de voz: {exc}') from exc
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass
