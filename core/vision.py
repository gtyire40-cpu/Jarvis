"""Local desktop vision: screenshot capture, OCR, visual analysis and element lookup."""
from __future__ import annotations

import base64
import io
import re
import time
from dataclasses import dataclass, asdict
from typing import Any

import requests

import config


@dataclass
class ScreenElement:
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["center"] = list(self.center)
        return d


class ScreenVision:
    def _capture(self):
        try:
            import mss
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Faltan las dependencias de captura de pantalla. Revisa requirements.txt.") from exc

        with mss.mss() as grabber:
            monitor = grabber.monitors[0]
            shot = grabber.grab(monitor)
            image = Image.frombytes("RGB", shot.size, shot.rgb)
        return image

    def capture_png(self) -> bytes:
        image = self._capture()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    def ocr(self, image=None, min_confidence: float = 25.0) -> list[ScreenElement]:
        try:
            import pytesseract
        except ImportError as exc:
            raise RuntimeError("Falta pytesseract. Revisa requirements.txt.") from exc
        if image is None:
            image = self._capture()
        data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
            config="--psm 11",
        )
        # PSM 11 funciona bien para interfaces abiertas. Si no devuelve texto,
        # PSM 12 mejora la detección de bloques dispersos sin cambiar la API.
        if not any((x or "").strip() for x in data.get("text", [])):
            data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT,
                config="--psm 12",
            )
        elements: list[ScreenElement] = []
        for i, raw in enumerate(data.get("text", [])):
            text = (raw or "").strip()
            try:
                confidence = float(data["conf"][i])
                x = int(data["left"][i])
                y = int(data["top"][i])
                width = int(data["width"][i])
                height = int(data["height"][i])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if text and confidence >= min_confidence and width > 0 and height > 0:
                elements.append(ScreenElement(text, round(confidence, 1), x, y, width, height))
        return elements

    @staticmethod
    def find(elements: list[ScreenElement], query: str, exact: bool = False) -> list[ScreenElement]:
        query = (query or "").strip().casefold()
        if not query:
            return []
        if exact:
            return [e for e in elements if e.text.casefold() == query]
        return [e for e in elements if query in e.text.casefold()]

    def describe(self, image: bytes | None = None, prompt: str | None = None) -> dict[str, Any]:
        """Ask Ollama for visual understanding when the selected model accepts images.
        OCR remains available as a deterministic fallback.
        """
        png = image or self.capture_png()
        model = getattr(config, "VISION_MODEL", "") or config.MODEL
        user_prompt = prompt or (
            "Analiza esta captura de pantalla. Describe de forma breve y objetiva "
            "las ventanas visibles, aplicaciones, controles y elementos relevantes "
            "para poder interactuar con el escritorio. No inventes elementos."
        )
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": user_prompt,
                "images": [base64.b64encode(png).decode("ascii")],
            }],
            "stream": False,
            "options": {"temperature": 0.0},
        }
        started = time.perf_counter()
        try:
            response = requests.post(
                f"{config.OLLAMA_URL.rstrip('/')}/api/chat",
                json=payload,
                timeout=min(config.OLLAMA_TIMEOUT, 90),
            )
            response.raise_for_status()
            data = response.json()
            content = (data.get("message", {}).get("content") or "").strip()
            if not content:
                raise RuntimeError("El modelo visual no devolvió una descripción.")
            return {
                "model": model,
                "description": content,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "source": "ollama-vision",
            }
        except Exception as exc:
            return {
                "model": model,
                "description": "",
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "source": "unavailable",
                "error": str(exc),
            }

    def inspect(self, max_elements: int = 150, include_visual: bool = True, prompt: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        image = self._capture()
        elements = self.ocr(image=image)
        result: dict[str, Any] = {
            "screen_size": [image.width, image.height],
            "elements": [e.to_dict() for e in elements[:max_elements]],
            "element_count": len(elements),
        }
        if include_visual:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            result["visual"] = self.describe(buffer.getvalue(), prompt)
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return result


VISION = ScreenVision()
