"""Passive recorder: captures the clicks and shortcuts *you* perform.

This never drives the UI. It installs capture-phase listeners that observe and
return; Priority behaves exactly as if the tool were not there.
"""

from __future__ import annotations

from .elements import _candidate_selectors, verify_selectors
from .js import DRAIN_JS, RECORDER_JS


class Recorder:
    def __init__(self, page):
        self.page = page
        self._init_script_added = False

    def install(self) -> int:
        """Install listeners in every live frame. Safe to call repeatedly."""
        if not self._init_script_added:
            # Covers frames created by future navigations.
            self.page.add_init_script(f"({RECORDER_JS})()")
            self._init_script_added = True

        installed = 0
        for frame in self.page.frames:
            if frame.is_detached():
                continue
            try:
                frame.evaluate(RECORDER_JS)
                installed += 1
            except Exception:
                continue
        return installed

    def drain(self, verify: bool = True) -> list[dict]:
        """Collect everything recorded so far and clear the buffers.

        Same-origin frames share sessionStorage, so the same event can come
        back from several frames. Each event carries the URL of the frame that
        produced it; that is what decides where it really happened.
        """
        frames = [f for f in self.page.frames if not f.is_detached()]
        by_url: dict[str, object] = {}
        index_of: dict[object, int] = {}
        for index, frame in enumerate(self.page.frames):
            if frame.is_detached():
                continue
            index_of[frame] = index
            by_url.setdefault(frame.url, frame)

        collected: list[tuple[object, dict]] = []
        for frame in frames:
            try:
                raw = frame.evaluate(DRAIN_JS)
            except Exception:
                continue
            for event in raw or []:
                collected.append((frame, event))

        events: list[dict] = []
        seen: set[tuple] = set()
        for read_from, event in collected:
            origin = event.get("frame_url") or ""
            owner = by_url.get(origin, read_from)
            target = event.get("target") or {}
            signature = (
                event.get("t"), event.get("kind"), event.get("key", ""),
                origin, target.get("css_path", ""),
            )
            if signature in seen:
                continue
            seen.add(signature)
            event["frame_index"] = index_of.get(owner, -1)
            event["frame_name"] = getattr(owner, "name", "") or ""
            if verify:
                self._attach_selectors(owner, event)
            events.append(event)

        events.sort(key=lambda e: e.get("t", 0))
        return events

    def _attach_selectors(self, frame, event: dict) -> None:
        """Turn the recorded element description into verified selectors."""
        for key in ("host", "target"):
            desc = event.get(key)
            if not isinstance(desc, dict):
                continue
            desc.setdefault("attrs", {})
            candidates = _candidate_selectors(desc)
            desc["selector_candidates"] = candidates
            try:
                desc["selectors"] = verify_selectors(frame, candidates)
            except Exception:
                desc["selectors"] = []


def format_events(events: list[dict]) -> str:
    """Human-readable rendering of recorded events for the console."""
    if not events:
        return "(nothing recorded)"
    lines = []
    for i, event in enumerate(events, 1):
        if event.get("kind") == "key":
            combo = "+".join(
                part for part, on in (
                    ("Ctrl", event.get("ctrl")), ("Alt", event.get("alt")),
                    ("Shift", event.get("shift")), ("Meta", event.get("meta")),
                ) if on
            )
            combo = f"{combo}+{event.get('key')}" if combo else str(event.get("key"))
            target = event.get("target") or {}
            lines.append(
                f"{i:>3}. KEY   {combo:<20} frame[{event.get('frame_index')}] "
                f"on <{target.get('tag', '?')}> {target.get('name') or target.get('id') or ''}"
            )
            continue

        desc = event.get("host") or event.get("target") or {}
        label = desc.get("text") or desc.get("title") or desc.get("name") or desc.get("id") or "?"
        selectors = desc.get("selectors") or []
        best = selectors[0]["selector"] if selectors else "(no unique selector found)"
        lines.append(
            f"{i:>3}. CLICK frame[{event.get('frame_index')}] <{desc.get('tag', '?')}> "
            f"{label!r}\n       -> {best}"
        )
        for extra in selectors[1:]:
            lines.append(f"       alt: {extra['selector']}")
    return "\n".join(lines)
