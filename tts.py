"""Síntesis de voz local con Piper, con reproducción directa por sounddevice."""
import logging
import os
import shutil
import subprocess
import tempfile
import time
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


def _play_wav(path, cancel_event=None):
    direct_error = None
    # Preferimos reproducción directa para no depender de aplay/paplay.
    if getattr(config, 'PIPER_AUDIO_PLAYER', 'auto') in ('auto', 'direct'):
        try:
            import sounddevice as sd
            import soundfile as sf
            data, rate = sf.read(path, dtype='float32')
            sd.play(data, rate)
            if cancel_event is None:
                sd.wait()
            else:
                stream = sd.get_stream()
                while stream is not None and stream.active:
                    if cancel_event.is_set():
                        sd.stop()
                        return
                    time.sleep(0.05)
            return
        except Exception as exc:
            direct_error = exc
            logger.debug('Reproducción directa no disponible: %s', exc)

    preferred = getattr(config, 'PIPER_AUDIO_PLAYER', 'auto')
    candidates = (preferred,) if preferred not in ('', 'auto', 'direct') else ('paplay', 'aplay', 'ffplay')
    for candidate in candidates:
        if shutil.which(candidate):
            cmd = [candidate, path] if candidate != 'ffplay' else [candidate, '-nodisp', '-autoexit', '-loglevel', 'error', path]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 60
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        if proc.poll() is not None:
                            proc.communicate()
                            return
                        proc.terminate()
                        try:
                            proc.communicate(timeout=2)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.communicate()
                        return
                    try:
                        _stdout, stderr = proc.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline:
                            proc.kill()
                            _stdout, stderr = proc.communicate()
                            raise subprocess.TimeoutExpired(cmd, 60, output=_stdout, stderr=stderr)
                        continue
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr)
            return
    raise RuntimeError('No encuentro un reproductor de audio compatible.')


def hablar(texto: str, cancel_event=None) -> None:
    texto = (texto or '').strip()
    if not texto or (cancel_event is not None and cancel_event.is_set()):
        return
    model = _find_model()
    piper = _find_piper()
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        wav = tmp.name
    try:
        proc = subprocess.Popen(
            [piper, '--model', model, '--output_file', wav],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        command = [piper, '--model', model, '--output_file', wav]
        deadline = time.monotonic() + 60
        try:
            input_data = texto.encode('utf-8')
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    if proc.poll() is not None:
                        proc.communicate()
                        return
                    proc.terminate()
                    try:
                        proc.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.communicate()
                    return
                try:
                    _stdout, stderr = proc.communicate(input=input_data, timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    input_data = None
                    if time.monotonic() >= deadline:
                        proc.kill()
                        _stdout, stderr = proc.communicate()
                        raise subprocess.TimeoutExpired(command, 60, output=_stdout, stderr=stderr)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode('utf-8', 'replace').strip() or 'Piper devolvió un error.')
        if cancel_event is None or not cancel_event.is_set():
            _play_wav(wav, cancel_event=cancel_event)
    except Exception as exc:
        logger.exception('Error de TTS')
        raise RuntimeError(f'No pude reproducir la respuesta de voz: {exc}') from exc
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass
