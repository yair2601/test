"""Frame tree inspection. Priority Web nests its screens in iframes, and the
first thing every selector needs to know is which frame it lives in."""

from __future__ import annotations

from .util import truncate


def frame_records(page) -> list[dict]:
    """Flat list of every frame in the page, with parent links and an index.

    The index is what the rest of the tooling (and the generated config) uses to
    refer to a frame, because frame names in Priority are often auto-generated.
    """
    frames = page.frames
    index_of = {f: i for i, f in enumerate(frames)}
    records = []
    for i, frame in enumerate(frames):
        parent = frame.parent_frame
        rec = {
            "index": i,
            "name": frame.name or "",
            "url": frame.url or "",
            "parent_index": index_of.get(parent) if parent is not None else None,
            "detached": frame.is_detached(),
            "iframe_id": "",
            "iframe_name": "",
            "iframe_css": "",
        }
        if parent is not None and not frame.is_detached():
            try:
                el = frame.frame_element()
                rec["iframe_id"] = el.get_attribute("id") or ""
                rec["iframe_name"] = el.get_attribute("name") or ""
                if rec["iframe_id"]:
                    rec["iframe_css"] = f"#{rec['iframe_id']}"
                elif rec["iframe_name"]:
                    rec["iframe_css"] = f'iframe[name="{rec["iframe_name"]}"]'
            except Exception:
                pass
        records.append(rec)
    return records


def format_tree(records: list[dict]) -> str:
    """Render the frame list as an indented tree for the console."""
    children: dict[int | None, list[dict]] = {}
    for rec in records:
        children.setdefault(rec["parent_index"], []).append(rec)

    lines: list[str] = []

    def walk(parent_index, depth):
        for rec in children.get(parent_index, []):
            handle = rec["iframe_css"] or rec["iframe_name"] or rec["name"] or "(anonymous)"
            lines.append(
                f"{'  ' * depth}[{rec['index']}] {handle}  {truncate(rec['url'], 90)}"
            )
            walk(rec["index"], depth + 1)

    walk(None, 0)
    return "\n".join(lines)


def frame_by_index(page, index: int):
    frames = page.frames
    if index < 0 or index >= len(frames):
        raise IndexError(f"No frame with index {index} (page has {len(frames)})")
    return frames[index]
