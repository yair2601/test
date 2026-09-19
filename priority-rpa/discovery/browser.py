"""Browser launch + session handling for discovery runs.

Always headed. The user drives the browser; this module only opens it with the
saved session and hands back the page.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_STATE = Path("storage_state.json")


class Session:
    """Owns the Playwright lifecycle for a discovery run."""

    def __init__(self, storage_state: Path | None = DEFAULT_STATE, start_url: str | None = None,
                 slow_mo: int = 0, browser_channel: str | None = None):
        self.storage_state = Path(storage_state) if storage_state else None
        self.start_url = start_url
        self.slow_mo = slow_mo
        self.browser_channel = browser_channel
        self._pw = None
        self.browser = None
        self.context = None
        self.page = None

    def __enter__(self) -> "Session":
        self._pw = sync_playwright().start()
        launch_kwargs = {"headless": False, "slow_mo": self.slow_mo}
        if self.browser_channel:
            launch_kwargs["channel"] = self.browser_channel
        self.browser = self._pw.chromium.launch(**launch_kwargs)

        ctx_kwargs = {"viewport": None, "accept_downloads": False}
        if self.storage_state and self.storage_state.exists():
            ctx_kwargs["storage_state"] = str(self.storage_state)
        self.context = self.browser.new_context(**ctx_kwargs)
        self.context.set_default_timeout(15_000)

        self.page = self.context.new_page()
        if self.start_url:
            self.page.goto(self.start_url, wait_until="domcontentloaded")
        return self

    def save_state(self, path: Path | None = None) -> Path:
        target = Path(path or self.storage_state or DEFAULT_STATE)
        self.context.storage_state(path=str(target))
        return target

    def __exit__(self, exc_type, exc, tb) -> None:
        for closer in (self.context, self.browser):
            try:
                if closer:
                    closer.close()
            except Exception:
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


def has_saved_state(path: Path = DEFAULT_STATE) -> bool:
    return Path(path).exists()
