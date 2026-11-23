"""Cancellable streaming transport for Ollama's newline-delimited JSON API."""
from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator

import requests


class StreamCancelled(Exception):
    pass


def iter_json_lines(url: str, payload: dict, timeout: float, cancel_event=None) -> Iterator[dict]:
    if cancel_event is not None and cancel_event.is_set():
        raise StreamCancelled

    messages = queue.Queue()
    stop_event = threading.Event()
    response_holder = {}

    def produce():
        try:
            if stop_event.is_set():
                return
            connect_timeout = max(min(timeout, 10), 0.1)
            read_timeout = max(timeout, 0.1)
            with requests.post(
                url,
                json=payload,
                timeout=(connect_timeout, read_timeout),
                stream=True,
            ) as response:
                response_holder["response"] = response
                if stop_event.is_set():
                    response.close()
                    return
                response.raise_for_status()
                for line in response.iter_lines():
                    if stop_event.is_set():
                        return
                    if line:
                        messages.put(("item", json.loads(line)))
        except (requests.RequestException, json.JSONDecodeError, UnicodeDecodeError) as exc:
            messages.put(("error", exc))
        finally:
            messages.put(("end", None))

    worker = threading.Thread(target=produce, daemon=True)
    worker.start()
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise StreamCancelled
            try:
                kind, value = messages.get(timeout=0.1)
            except queue.Empty:
                continue
            if kind == "item":
                yield value
            elif kind == "error":
                raise value
            else:
                return
    finally:
        stop_event.set()
        response = response_holder.get("response")
        if response is not None:
            response.close()
