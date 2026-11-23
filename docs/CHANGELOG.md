# Jarvis Local 3.6.2

Jarvis Local 3.6.2 is based on the 3.5.0 codebase and focuses on reliability, real verification, GUI control, and a redesigned desktop interface.

## Fixed from 3.5 testing
- Mouse center and bottom-right verification.
- Application closing verification, including calculator-style apps.
- Folder and file creation verification.
- Separate screenshot capture from OCR.
- Better window dependency diagnostics.
- More robust web search parsing.
- Real RAM and disk-space queries without unrelated system information.
- Natural-language variants such as "otra vez" and new-tab requests.
- Keyboard shortcut routing.
- Reduced opportunity for false action claims.

## New in 3.6
- Strict post-action verification.
- Retry/recovery flow that actually retries instead of returning early.
- Tools and Diagnostics sections in the GUI.
- More explicit real-time activity states.
- Separate capture tool independent of OCR.
- Dedicated RAM/disk queries.
- Improved deterministic intent router.
- Database/history version migrated to 3.6.
- Foundation for multi-step automation and richer computer control.

## 3.6.2 — GPU universal y diagnóstico
- Detección de NVIDIA, AMD e Intel mediante hardware del sistema.
- CUDA opcional: los paquetes CUDA de NVIDIA solo se instalan cuando se detecta una GPU NVIDIA.
- Whisper mantiene una política conservadora: CUDA solo se usa cuando CTranslate2 confirma soporte real; AMD/Intel pasan a CPU si no existe un backend compatible para Whisper.
- Diagnóstico separado de GPU física, backend recomendado y backend real de Whisper.
- Fallback automático a CPU.
