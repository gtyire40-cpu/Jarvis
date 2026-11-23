import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    print("Jarvis Local Doctor 3.2.1")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Arquitectura: {__import__('platform').machine()}")
    print(f"nvidia-smi: {'OK' if shutil.which('nvidia-smi') else 'NO'}")
    if shutil.which('nvidia-smi'):
        r=subprocess.run(['nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader'], text=True, capture_output=True)
        print(r.stdout.strip() or 'GPU NVIDIA no detectada')
    for mod in ('requests','faster_whisper','sounddevice','piper','onnxruntime','playwright'):
        print(f"{mod}: {'OK' if importlib.util.find_spec(mod) else 'NO'}")
    try:
        import gpu_runtime
        print('Whisper:', gpu_runtime.diagnostics())
    except Exception as exc:
        print(f'Whisper runtime: ERROR {exc}')

if __name__ == '__main__': main()
