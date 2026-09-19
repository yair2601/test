"""Harvest interactive elements from a frame and propose *verified* selectors.

A proposed selector is only reported once it has been counted against the live
frame and resolves to exactly one element. That is the whole point of this
tool: never hand back a selector that was guessed.
"""

from __future__ import annotations

import re

from .js import HARVEST_JS
from .util import truncate

# Buttons/labels worth flagging in the report, Hebrew and English.
ACTION_KEYWORDS = {
    "new_record": ["רשומה חדשה", "חדש", "הוספה", "הוסף", "new", "add", "create", "insert"],
    "save": ["שמור", "שמירה", "אישור", "save", "apply", "confirm", "submit"],
    "cancel": ["בטל", "ביטול", "cancel", "undo", "discard"],
    "search": ["חיפוש", "חפש", "שאילתה", "סנן", "סינון", "search", "find", "query", "filter"],
    "delete": ["מחק", "מחיקה", "delete", "remove"],
    "lines": ["שורות", "פריטים", "שורות הזמנה", "items", "lines", "details"],
}

# Field names we ultimately need to map for the loader.
FIELD_HINTS = {
    "reference": ["אסמכתא", "אסמכתה", "reference", "ref", "custorder", "ordername"],
    "customer": ["לקוח", "customer", "custname", "custdes", "account"],
    "date": ["תאריך", "date", "curdate", "duedate"],
    "item": ["מק\"ט", "מקט", "פריט", "part", "item", "partname", "sku"],
    "quantity": ["כמות", "qty", "quantity", "tquant"],
    "price": ["מחיר", "price", "vprice", "unitprice"],
}

_SAFE_IDENT = re.compile(r'^[A-Za-z][\w:.-]*$')


def _css_quote(value: str) -> str | None:
    """Quote an attribute value for a CSS attribute selector, or reject it."""
    if value is None:
        return None
    value = str(value)
    if not value or "\n" in value or len(value) > 80:
        return None
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _candidate_selectors(el: dict) -> list[str]:
    """Ordered list of selector guesses for one element, most stable first."""
    out: list[str] = []
    tag = el.get("tag") or "*"

    el_id = el.get("id") or ""
    if el_id and _SAFE_IDENT.match(el_id):
        out.append(f"#{el_id}")

    name = _css_quote(el.get("name"))
    if name:
        out.append(f"{tag}[name={name}]")

    for attr, value in (el.get("attrs") or {}).items():
        if not attr.startswith("data-"):
            continue
        quoted = _css_quote(value)
        if quoted:
            out.append(f"[{attr}={quoted}]")

    aria = _css_quote((el.get("attrs") or {}).get("aria-label"))
    if aria:
        out.append(f"{tag}[aria-label={aria}]")

    title = _css_quote(el.get("title"))
    if title:
        out.append(f"{tag}[title={title}]")

    placeholder = _css_quote(el.get("placeholder"))
    if placeholder:
        out.append(f"{tag}[placeholder={placeholder}]")

    # Text-based, for buttons and links. Playwright CSS extension.
    text = (el.get("text") or "").strip()
    if text and len(text) <= 40 and tag in ("button", "a", "span", "div", "td"):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        out.append(f'{tag}:has-text("{escaped}")')

    css_path = el.get("css_path") or ""
    if css_path:
        out.append(css_path)

    # Preserve order, drop duplicates.
    seen = set()
    unique = []
    for sel in out:
        if sel not in seen:
            seen.add(sel)
            unique.append(sel)
    return unique


def verify_selectors(frame, candidates: list[str], limit: int = 3) -> list[dict]:
    """Count each candidate against the live frame; keep the unique ones."""
    verified: list[dict] = []
    for sel in candidates:
        try:
            count = frame.locator(sel).count()
        except Exception:
            continue
        if count == 1:
            verified.append({"selector": sel, "matches": 1})
            if len(verified) >= limit:
                break
    return verified


def _keyword_hit(haystack: str, word: str) -> bool:
    """Substring match for Hebrew; word-boundary match for Latin keywords.

    Without the boundary, short keywords like 'add' or 'ref' match inside
    unrelated words ('address', 'prefix') and mislabel half the screen.
    """
    word = word.lower()
    if re.search(r"[a-z]", word):
        return re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", haystack) is not None
    return word in haystack


def _classify(el: dict, table: dict[str, list[str]]) -> list[str]:
    """Tag an element with the roles its own text/label/name hints at."""
    keys = ("text", "label", "title", "name", "id", "placeholder")
    parts = [str(el.get(key) or "") for key in keys]
    parts.append((el.get("attrs") or {}).get("aria-label", ""))
    haystack = " ".join(parts).lower()
    return [tag for tag, words in table.items()
            if any(_keyword_hit(haystack, word) for word in words)]


def harvest_frame(frame, max_elements: int = 1200, capture_values: bool = False,
                  verify: bool = True) -> dict:
    """Read one frame and return its elements, grids and verified selectors."""
    data = frame.evaluate(HARVEST_JS, {"max_elements": max_elements,
                                       "capture_values": capture_values})

    for el in data["elements"]:
        el["selector_candidates"] = _candidate_selectors(el)
        el["selectors"] = (
            verify_selectors(frame, el["selector_candidates"]) if verify else []
        )
        el["action_hints"] = _classify(el, ACTION_KEYWORDS)
        el["field_hints"] = _classify(el, FIELD_HINTS)

    data["input_count"] = sum(
        1 for e in data["elements"]
        if e["tag"] in ("input", "select", "textarea") and e["visible"]
    )
    data["button_count"] = sum(
        1 for e in data["elements"]
        if (e["tag"] == "button" or e.get("role") == "button") and e["visible"]
    )
    return data


def harvest_all_frames(page, max_elements: int = 1200, capture_values: bool = False,
                       verify: bool = True, skip_blank: bool = True) -> list[dict]:
    """Harvest every frame, tolerating frames that detach mid-run."""
    results = []
    for index, frame in enumerate(page.frames):
        if frame.is_detached():
            continue
        if skip_blank and frame.url in ("about:blank", ""):
            continue
        try:
            data = harvest_frame(frame, max_elements, capture_values, verify)
        except Exception as exc:
            results.append({
                "frame_index": index,
                "frame_url": frame.url,
                "error": f"{type(exc).__name__}: {truncate(exc, 200)}",
                "elements": [], "grids": [], "input_count": 0, "button_count": 0,
            })
            continue
        data["frame_index"] = index
        data["frame_url"] = frame.url
        data["frame_name"] = frame.name or ""
        results.append(data)
    return results


def best_frame(harvests: list[dict]) -> dict | None:
    """The frame most likely to hold the working screen: the most form fields."""
    scored = [h for h in harvests if not h.get("error")]
    if not scored:
        return None
    return max(scored, key=lambda h: (h["input_count"], h["button_count"]))
