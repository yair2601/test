"""Network observation.

Shows which XHR/fetch calls a screen makes. Useful for spotting the endpoint
that saves a record and the one that runs a search — which in turn tells the
loader what to wait for instead of sleeping blindly.

Request bodies are NOT captured by default: this runs against production data.
"""

from __future__ import annotations

from .util import truncate

INTERESTING = {"xhr", "fetch", "document"}


class NetLog:
    def __init__(self, page, capture_payloads: bool = False, limit: int = 500):
        self.page = page
        self.capture_payloads = capture_payloads
        self.limit = limit
        self.entries: list[dict] = []
        self.enabled = False
        self._handlers_attached = False

    def _on_request(self, request) -> None:
        if not self.enabled or len(self.entries) >= self.limit:
            return
        if request.resource_type not in INTERESTING:
            return
        entry = {
            "phase": "request",
            "method": request.method,
            "url": request.url,
            "resource_type": request.resource_type,
            "payload": "",
        }
        if self.capture_payloads and request.method != "GET":
            try:
                entry["payload"] = truncate(request.post_data or "", 2000)
            except Exception:
                pass
        self.entries.append(entry)

    def _on_response(self, response) -> None:
        if not self.enabled or len(self.entries) >= self.limit:
            return
        try:
            if response.request.resource_type not in INTERESTING:
                return
            self.entries.append({
                "phase": "response",
                "method": response.request.method,
                "url": response.url,
                "status": response.status,
                "resource_type": response.request.resource_type,
            })
        except Exception:
            pass

    def start(self) -> None:
        if not self._handlers_attached:
            self.page.on("request", self._on_request)
            self.page.on("response", self._on_response)
            self._handlers_attached = True
        self.enabled = True

    def stop(self) -> None:
        self.enabled = False

    def drain(self) -> list[dict]:
        entries, self.entries = self.entries, []
        return entries


def format_entries(entries: list[dict], max_items: int = 40) -> str:
    if not entries:
        return "(no network activity recorded)"
    lines = []
    for entry in entries[:max_items]:
        if entry["phase"] == "request":
            lines.append(f"  -> {entry['method']:<6} {truncate(entry['url'], 110)}")
            if entry.get("payload"):
                lines.append(f"     body: {truncate(entry['payload'], 160)}")
        else:
            lines.append(f"  <- {entry.get('status', '?'):<6} {truncate(entry['url'], 110)}")
    if len(entries) > max_items:
        lines.append(f"  ... {len(entries) - max_items} more (see the JSON dump)")
    return "\n".join(lines)
