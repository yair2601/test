"""Before/after DOM diffing.

The workflow that answers 'what does the New Record button actually do':
  snap  -> you click the button yourself -> diff
The report lists fields that appeared, buttons that became enabled, rows added.
"""

from __future__ import annotations

from .js import SIGNATURE_JS
from .util import truncate


def snapshot(page) -> dict:
    """Capture a lightweight signature of every frame."""
    snap: dict[int, dict] = {}
    for index, frame in enumerate(page.frames):
        if frame.is_detached() or frame.url in ("about:blank", ""):
            continue
        try:
            snap[index] = frame.evaluate(SIGNATURE_JS)
        except Exception:
            continue
    return snap


def diff(before: dict, after: dict) -> dict:
    """Compare two snapshots, frame by frame."""
    report: dict[int, dict] = {}
    for index in sorted(set(before) | set(after)):
        old = before.get(index)
        new = after.get(index)
        if old is None:
            report[index] = {"frame_status": "appeared", "url": new.get("url", "")}
            continue
        if new is None:
            report[index] = {"frame_status": "disappeared", "url": old.get("url", "")}
            continue

        old_nodes, new_nodes = old["nodes"], new["nodes"]
        added = [k for k in new_nodes if k not in old_nodes]
        removed = [k for k in old_nodes if k not in new_nodes]
        changed = []
        for key in new_nodes:
            if key not in old_nodes:
                continue
            a, b = old_nodes[key], new_nodes[key]
            deltas = [
                f"{field}: {a[field]} -> {b[field]}"
                for field in ("visible", "disabled", "readonly", "label")
                if a.get(field) != b.get(field)
            ]
            if deltas:
                changed.append({"key": key, "node": b, "changes": deltas})

        entry = {
            "frame_status": "changed" if (added or removed or changed) else "same",
            "url_changed": old.get("url") != new.get("url"),
            "url_before": old.get("url", ""),
            "url_after": new.get("url", ""),
            "row_count_before": old.get("row_count", 0),
            "row_count_after": new.get("row_count", 0),
            "added": [{"key": k, "node": new_nodes[k]} for k in added],
            "removed": [{"key": k, "node": old_nodes[k]} for k in removed],
            "changed": changed,
        }
        if entry["frame_status"] != "same" or entry["url_changed"]:
            report[index] = entry
    return report


def format_diff(report: dict, max_items: int = 25) -> str:
    if not report:
        return "No differences detected."
    lines = []
    for index, entry in report.items():
        lines.append(f"\n=== frame[{index}] : {entry['frame_status']} ===")
        if entry.get("url_changed"):
            lines.append(f"  URL: {truncate(entry['url_before'], 70)}")
            lines.append(f"   ->  {truncate(entry['url_after'], 70)}")
        if entry.get("frame_status") in ("appeared", "disappeared"):
            continue
        before_rows, after_rows = entry["row_count_before"], entry["row_count_after"]
        if before_rows != after_rows:
            lines.append(f"  rows: {before_rows} -> {after_rows}  (grid row added/removed)")

        for title, key in (("ADDED", "added"), ("REMOVED", "removed")):
            items = entry[key]
            if not items:
                continue
            lines.append(f"  {title} ({len(items)}):")
            for item in items[:max_items]:
                node = item["node"]
                ident = node.get("name") or node.get("id") or node.get("label") or ""
                lines.append(f"    <{node['tag']}> {ident!r}  {item['key']}")
            if len(items) > max_items:
                lines.append(f"    ... {len(items) - max_items} more (see the JSON dump)")

        if entry["changed"]:
            lines.append(f"  CHANGED ({len(entry['changed'])}):")
            for item in entry["changed"][:max_items]:
                node = item["node"]
                ident = node.get("name") or node.get("id") or node.get("label") or ""
                lines.append(f"    <{node['tag']}> {ident!r}: {'; '.join(item['changes'])}")
            if len(entry["changed"]) > max_items:
                lines.append(f"    ... {len(entry['changed']) - max_items} more")
    return "\n".join(lines)
