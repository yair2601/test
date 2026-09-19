"""Small shared helpers. All file writes are explicit UTF-8 (Windows defaults
to cp1255, which mangles the Hebrew coming out of Priority)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_name(text: str, max_len: int = 40) -> str:
    """Turn arbitrary text into something Windows will accept as a filename."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(text)).strip(" .")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned or "unnamed")[:max_len]


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def truncate(text, limit: int = 60) -> str:
    text = "" if text is None else str(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
