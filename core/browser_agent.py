"""Controlled Playwright browser session for Jarvis.

One browser session is kept per process. Playwright is started lazily.
"""
from __future__ import annotations

import re
import threading
import shutil
import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@dataclass
class BrowserPageInfo:
    url: str
    title: str


class BrowserAgent:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self._lock = threading.RLock()
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def _ensure(self):
        if sync_playwright is None:
            raise RuntimeError("Playwright no está instalado. Instala 'playwright' y Chromium.")
        if self._page is not None:
            return self._page
        self._pw = sync_playwright().start()
        executable = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
        launch_kwargs = {"headless": self.headless}
        if executable:
            launch_kwargs["executable_path"] = executable
        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(viewport={"width": 1440, "height": 900})
        self._page = self._context.new_page()
        return self._page

    @staticmethod
    def _validate_url(url: str) -> str:
        url = url.strip()
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            raise ValueError("URL inválida")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("Por seguridad no se permite acceder a destinos locales desde el navegador web.")
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("Por seguridad no se permite acceder a destinos privados o locales.")
        except ValueError as exc:
            if str(exc).startswith("Por seguridad"):
                raise
            try:
                addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            except socket.gaierror as dns_exc:
                raise ValueError("No se pudo resolver el dominio solicitado.") from dns_exc
            if not addresses:
                raise ValueError("El dominio solicitado no tiene direcciones accesibles.")
            for address in addresses:
                try:
                    resolved = ipaddress.ip_address(address[4][0])
                except ValueError:
                    continue
                if resolved.is_private or resolved.is_loopback or resolved.is_link_local or resolved.is_reserved:
                    raise ValueError("Por seguridad no se permite acceder a destinos privados o locales.")
        return url

    def navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict[str, Any]:
        with self._lock:
            page = self._ensure()
            target = self._validate_url(url)
            page.goto(target, wait_until=wait_until, timeout=30000)
            return {"url": page.url, "title": page.title()}

    def back(self) -> dict[str, Any]:
        with self._lock:
            page = self._ensure()
            page.go_back(wait_until="domcontentloaded", timeout=30000)
            return {"url": page.url, "title": page.title()}

    def click_text(self, text: str) -> dict[str, Any]:
        with self._lock:
            page = self._ensure()
            locator = page.get_by_text(text, exact=True).first
            locator.click(timeout=10000)
            return {"url": page.url, "title": page.title(), "clicked": text}

    def click_role(self, role: str, name: str) -> dict[str, Any]:
        with self._lock:
            page = self._ensure()
            locator = page.get_by_role(role, name=name).first
            locator.click(timeout=10000)
            return {"url": page.url, "title": page.title(), "clicked": name, "role": role}

    def fill(self, label_or_placeholder: str, value: str) -> dict[str, Any]:
        with self._lock:
            page = self._ensure()
            locator = page.get_by_label(label_or_placeholder).first
            if locator.count() == 0:
                locator = page.get_by_placeholder(label_or_placeholder).first
            locator.fill(value, timeout=10000)
            return {"url": page.url, "filled": label_or_placeholder}

    def press(self, key: str) -> dict[str, Any]:
        with self._lock:
            page = self._ensure()
            page.keyboard.press(key)
            return {"url": page.url, "pressed": key}

    def extract(self, max_chars: int = 12000) -> dict[str, Any]:
        with self._lock:
            page = self._ensure()
            text = page.locator("body").inner_text(timeout=10000)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            return {"url": page.url, "title": page.title(), "text": text[:max_chars]}

    def screenshot(self, path: str) -> dict[str, Any]:
        with self._lock:
            page = self._ensure()
            page.screenshot(path=path, full_page=False)
            return {"url": page.url, "path": path}

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._page is None:
                return {"running": False}
            return {"running": True, "url": self._page.url, "title": self._page.title()}

    def close(self):
        with self._lock:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
            self._context = self._browser = self._pw = self._page = None


BROWSER = BrowserAgent(headless=False)
