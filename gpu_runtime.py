"""Detección unificada de GPU y selección conservadora de aceleración.

La detección de hardware es independiente del runtime de Whisper. Ollama puede
usar un backend distinto del que CTranslate2/faster-whisper soporte en la
máquina. Nunca se anuncia aceleración GPU para Whisper si CTranslate2 no la
confirma.
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GPUInfo:
    vendor: str
    name: str
    driver: str | None = None
    vram_mb: int | None = None
    backend: str = "cpu"
    acceleration: str = "CPU fallback"
    available: bool = True


def _run(cmd: list[str], timeout: float = 4) -> str:
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           text=True, timeout=timeout, check=False)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _parse_vram_mb(text: str) -> int | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(MiB|MB|GiB|GB)", text, re.I)
    if not m:
        return None
    value = float(m.group(1))
    return int(value * (1024 if m.group(2).lower().startswith("g") else 1))


def _lspci_gpus() -> list[GPUInfo]:
    out = _run(["lspci", "-nnk"])
    if not out:
        return []
    result = []
    for block in re.split(r"\n(?=[0-9a-f:.]+\s+.*(?:VGA|3D|Display))", out, flags=re.I):
        if not re.search(r"VGA compatible controller|3D controller|Display controller", block, re.I):
            continue
        first = block.splitlines()[0] if block.splitlines() else block
        low = block.lower()
        if "nvidia" in low:
            vendor = "NVIDIA"
            backend = "cuda"
            acceleration = "CUDA disponible (si el runtime lo confirma)"
        elif "advanced micro devices" in low or "amd/ati" in low or "amd " in low:
            vendor = "AMD"
            backend = "rocm/vulkan"
            acceleration = "ROCm/Vulkan posible; depende del runtime instalado"
        elif "intel" in low:
            vendor = "Intel"
            backend = "vulkan"
            acceleration = "Vulkan posible; depende del runtime instalado"
        else:
            vendor = "Desconocido"
            backend = "cpu"
            acceleration = "CPU fallback"
        name = re.sub(r"^[0-9a-f:.]+\s+", "", first).strip()
        result.append(GPUInfo(vendor, name, backend=backend, acceleration=acceleration))
    return result


def detect_gpus() -> list[GPUInfo]:
    """Devuelve GPUs detectadas sin instalar ni modificar runtimes."""
    gpus = _lspci_gpus()
    nvidia = nvidia_details()
    if nvidia:
        replaced = 0
        for i, item in enumerate(gpus):
            if item.vendor == "NVIDIA" and replaced < len(nvidia):
                gpus[i] = nvidia[replaced]
                replaced += 1
        gpus.extend(nvidia[replaced:])
    return gpus


def nvidia_details() -> list[GPUInfo]:
    if not shutil.which("nvidia-smi"):
        return []
    out = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits"])
    if not out:
        return []
    result = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try: vram = int(float(parts[2]))
            except ValueError: vram = None
            result.append(GPUInfo("NVIDIA", parts[0], parts[1] or None, vram,
                                  "cuda", "CUDA disponible (driver NVIDIA detectado)"))
    return result


def detect_primary_gpu() -> GPUInfo | None:
    gpus = detect_gpus()
    return gpus[0] if gpus else None


def recommended_backend() -> str:
    gpu = detect_primary_gpu()
    if not gpu:
        return "cpu"
    if gpu.vendor == "NVIDIA":
        return "cuda"
    if gpu.vendor == "AMD":
        return "rocm/vulkan"
    if gpu.vendor == "Intel":
        return "vulkan"
    return "cpu"


def prepare_cuda_runtime() -> list[str]:
    """Hace visibles CUDA 12 solo cuando el sistema tiene NVIDIA."""
    if not nvidia_details():
        return []
    dirs = []
    try:
        import nvidia.cublas.lib as cublas_lib
        dirs.append(str(Path(cublas_lib.__file__).resolve().parent))
    except Exception:
        pass
    try:
        import nvidia.cudnn.lib as cudnn_lib
        dirs.append(str(Path(cudnn_lib.__file__).resolve().parent))
    except Exception:
        pass
    if dirs:
        current = os.environ.get("LD_LIBRARY_PATH", "")
        existing = [d for d in current.split(":") if d]
        merged = []
        for d in dirs + existing:
            if d not in merged:
                merged.append(d)
        os.environ["LD_LIBRARY_PATH"] = ":".join(merged)
        for name in ("libcublas.so.12", "libcudnn.so.9"):
            for d in dirs:
                candidate = Path(d) / name
                if candidate.exists():
                    try: ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
                    except OSError: pass
                    break
    return dirs


def nvidia_smi_available() -> bool:
    return shutil.which("nvidia-smi") is not None


def nvidia_gpu_available() -> bool:
    return bool(nvidia_details())


def ctranslate2_cuda_available() -> bool:
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return False


def detect_whisper_runtime():
    """Selecciona CUDA solo si CTranslate2 lo confirma; resto -> CPU."""
    if nvidia_gpu_available():
        prepare_cuda_runtime()
    requested = os.getenv("JARVIS_WHISPER_DEVICE", "auto").strip().lower()
    compute = os.getenv("JARVIS_WHISPER_COMPUTE_TYPE", "auto").strip().lower()
    ct2 = ctranslate2_cuda_available() if nvidia_gpu_available() else False
    if requested in {"cuda", "gpu"}:
        device = "cuda" if ct2 else "cpu"
    elif requested == "cpu":
        device = "cpu"
    else:
        device = "cuda" if ct2 else "cpu"
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute, device == "cuda"


def diagnostics() -> dict:
    gpus = detect_gpus()
    device, compute, whisper_gpu = detect_whisper_runtime()
    return {
        "gpus": [asdict(g) for g in gpus],
        "recommended_backend": recommended_backend(),
        "nvidia_smi": nvidia_smi_available(),
        "ctranslate2_cuda": ctranslate2_cuda_available() if nvidia_gpu_available() else False,
        "whisper_device": device,
        "whisper_compute_type": compute,
        "whisper_gpu_acceleration": whisper_gpu,
    }
