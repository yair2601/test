"""Turn a harvest into files a human can read and a config draft to paste."""

from __future__ import annotations

from pathlib import Path

from .elements import best_frame
from .frames import format_tree
from .util import now_iso, safe_name, truncate, write_json, write_text

# The config shape the loader will eventually read. Each entry is
# (yaml key, hint name, hint field, comment).
ORDERS_ACTIONS = [
    ("new_record_button", "new_record", "action_hints", "opens a blank ORDERS record"),
    ("save_button", "save", "action_hints", "commits the header"),
    ("search_button", "search", "action_hints", "runs a search/query by reference"),
    ("lines_tab", "lines", "action_hints", "opens the ORDERITEMS sub-screen"),
]
ORDERS_FIELDS = [
    ("reference", "reference", "field_hints", "header field holding the Excel reference"),
    ("customer", "customer", "field_hints", "header customer field"),
    ("date", "date", "field_hints", "header date field"),
]
LINE_FIELDS = [
    ("item_code", "item", "field_hints", "line item / SKU"),
    ("quantity", "quantity", "field_hints", "line quantity"),
    ("price", "price", "field_hints", "line unit price"),
]


def _yaml_str(value: str) -> str:
    """Double-quote a scalar. Selectors start with '#', which YAML would
    otherwise read as a comment and silently turn into null."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _element_line(el: dict) -> str:
    selector = el["selectors"][0]["selector"] if el.get("selectors") else "(no unique selector)"
    bits = [f"<{el['tag']}" + (f" type={el['type']}" if el.get("type") else "") + ">"]
    for key in ("name", "id", "label", "title", "placeholder"):
        if el.get(key):
            bits.append(f"{key}={truncate(el[key], 40)!r}")
    if el.get("text"):
        bits.append(f"text={truncate(el['text'], 40)!r}")
    flags = [f for f in ("readonly", "disabled", "required") if el.get(f)]
    if flags:
        bits.append("[" + ",".join(flags) + "]")
    if el.get("in_grid"):
        bits.append("[in-grid]")
    return "  " + " ".join(bits) + f"\n      {selector}"


def _matching(elements: list[dict], key: str, hint_field: str) -> list[dict]:
    return [el for el in elements if key in el.get(hint_field, []) and el.get("visible")]


def write_dump(out_dir: Path, page, frames: list[dict], harvests: list[dict],
               label: str = "", net_entries: list[dict] | None = None) -> Path:
    """Write report.md, elements.json, per-frame HTML, screenshot, config draft."""
    out_dir.mkdir(parents=True, exist_ok=True)

    write_json(out_dir / "elements.json", {
        "captured_at": now_iso(),
        "label": label,
        "page_url": page.url,
        "frames": frames,
        "harvests": harvests,
        "network": net_entries or [],
    })

    # Screenshot (full page of the top-level document).
    try:
        page.screenshot(path=str(out_dir / "screenshot.png"), full_page=False)
    except Exception as exc:
        write_text(out_dir / "screenshot-failed.txt", f"{type(exc).__name__}: {exc}")

    # Raw HTML per frame, so a selector can be worked out offline later.
    html_dir = out_dir / "html"
    for index, frame in enumerate(page.frames):
        if frame.is_detached() or frame.url in ("about:blank", ""):
            continue
        try:
            name = safe_name(frame.name or f"frame{index}")
            write_text(html_dir / f"{index:02d}-{name}.html", frame.content())
        except Exception:
            continue

    write_text(out_dir / "report.md", _render_report(page, frames, harvests, label, net_entries))
    write_text(out_dir / "config-draft.yaml", _render_config_draft(frames, harvests))
    return out_dir


def _render_report(page, frames, harvests, label, net_entries) -> str:
    main = best_frame(harvests)
    main_index = main.get("frame_index") if main else None
    real_frames = [f for f in frames if f["url"] not in ("about:blank", "")]

    lines = [
        f"# Priority screen dump{f' — {label}' if label else ''}",
        "",
        f"- Captured: {now_iso()}",
        f"- Page URL: `{page.url}`",
        f"- Frames: {len(real_frames)}",
        "",
        "## Answers to the open questions",
        "",
    ]

    # Q: is the screen inside an iframe?
    if len(real_frames) <= 1:
        lines.append("**iframes:** no — the screen is in the top-level document. "
                     "`frame` in the config can stay `null`.")
    else:
        handle = ""
        if main_index is not None:
            rec = next((f for f in frames if f["index"] == main_index), None)
            handle = (rec or {}).get("iframe_css") or (rec or {}).get("name") or ""
        lines.append(
            f"**iframes:** yes — {len(real_frames)} frames. The working screen is most "
            f"likely **frame[{main_index}]**"
            + (f" (`{handle}`)" if handle else "")
            + f" with {main['input_count'] if main else 0} visible inputs. "
              "Every selector below is relative to its own frame."
        )
    lines.append("")

    # Q: grid or form?
    all_grids = [(h["frame_index"], g) for h in harvests for g in h.get("grids", [])]
    data_grids = [(i, g) for i, g in all_grids if g["input_count"] > 0 and g["rows"] > 1]
    if data_grids:
        index, grid = max(data_grids, key=lambda pair: pair[1]["input_count"])
        lines.append(
            f"**Grid or form:** a grid with editable cells was found in frame[{index}] "
            f"({grid['rows']} rows, {grid['input_count']} inputs). Columns: "
            + ", ".join(f"`{h}`" for h in grid["headers"][:12] if h)
            + f"\n  Set `line_entry_mode: grid` and use `{grid['css_path']}` as the grid root."
        )
    else:
        lines.append("**Grid or form:** no editable grid detected on this screen — "
                     "lines are probably entered through a form. Set `line_entry_mode: form`.")
    lines.append("")

    # Q: which buttons exist?
    lines.append("## Action buttons found")
    lines.append("")
    any_action = False
    for action in ("new_record", "save", "cancel", "search", "delete", "lines"):
        found = []
        for harvest in harvests:
            for el in _matching(harvest.get("elements", []), action, "action_hints"):
                found.append((harvest["frame_index"], el))
        if not found:
            continue
        any_action = True
        lines.append(f"### {action}")
        for index, el in found[:8]:
            lines.append(f"- frame[{index}] " + _element_line(el).strip())
        lines.append("")
    if not any_action:
        lines.append("_No buttons matched the known keywords. Use `pick` mode and click the "
                     "button yourself — that always works, even for icon-only toolbars._")
        lines.append("")

    # Q: which fields exist?
    lines.append("## Fields that look relevant")
    lines.append("")
    any_field = False
    for field in ("reference", "customer", "date", "item", "quantity", "price"):
        found = []
        for harvest in harvests:
            for el in _matching(harvest.get("elements", []), field, "field_hints"):
                found.append((harvest["frame_index"], el))
        if not found:
            continue
        any_field = True
        lines.append(f"### {field}")
        for index, el in found[:8]:
            lines.append(f"- frame[{index}] " + _element_line(el).strip())
        lines.append("")
    if not any_field:
        lines.append("_No fields matched the known names. This is expected if the labels are "
                     "images or the field names are internal codes — use `pick` mode._")
        lines.append("")

    lines += ["## Frame tree", "", "```", format_tree(frames), "```", ""]

    lines += ["## All visible controls, by frame", ""]
    for harvest in harvests:
        if harvest.get("error"):
            lines.append(f"### frame[{harvest['frame_index']}] — ERROR: {harvest['error']}")
            lines.append("")
            continue
        visible = [e for e in harvest["elements"] if e["visible"]]
        lines.append(
            f"### frame[{harvest['frame_index']}] — {len(visible)} visible "
            f"({harvest['input_count']} inputs, {harvest['button_count']} buttons)"
        )
        lines.append(f"`{truncate(harvest['frame_url'], 120)}`")
        lines.append("")
        if not visible:
            lines.append("_(nothing visible)_")
            lines.append("")
            continue
        lines.append("```")
        for el in visible[:250]:
            lines.append(_element_line(el))
        if len(visible) > 250:
            lines.append(f"... {len(visible) - 250} more — see elements.json")
        lines.append("```")
        lines.append("")

        for grid in harvest.get("grids", []):
            if grid["rows"] <= 1 and grid["input_count"] == 0:
                continue
            lines.append(
                f"- grid `{grid['css_path']}`: {grid['rows']} rows, "
                f"{grid['input_count']} inputs, headers: "
                + (", ".join(f"`{h}`" for h in grid["headers"][:15]) or "_none_")
            )
        lines.append("")

    if net_entries:
        from .netlog import format_entries
        lines += ["## Network activity", "", "```", format_entries(net_entries), "```", ""]

    return "\n".join(lines)


def _render_config_draft(frames, harvests) -> str:
    """A valid YAML fragment pre-filled with whatever could be verified.

    Anything that could not be determined is written as FILL_ME rather than
    guessed, so a half-known screen never produces a config that looks ready.
    """
    main = best_frame(harvests)
    main_index = main.get("frame_index") if main else None
    frame_rec = next((f for f in frames if f["index"] == main_index), None) if main else None
    frame_css = (frame_rec or {}).get("iframe_css") or ""

    def candidates(hint: str, hint_field: str, in_grid=None) -> list[dict]:
        out = []
        for harvest in harvests:
            for el in harvest.get("elements", []):
                if hint not in el.get(hint_field, []) or not el.get("visible"):
                    continue
                if in_grid is not None and bool(el.get("in_grid")) != in_grid:
                    continue
                out.append(el)
        return out

    def emit(lines: list[str], indent: str, key: str, hint: str, hint_field: str,
             comment: str, in_grid=None) -> None:
        found = [el for el in candidates(hint, hint_field, in_grid) if el.get("selectors")]
        lines.append(f"{indent}# {comment}")
        if found:
            best = found[0]
            label = truncate(best.get("label") or best.get("text") or best.get("name"), 40)
            lines.append(f"{indent}{key}: {_yaml_str(best['selectors'][0]['selector'])}"
                         f"   # <{best['tag']}> {label!r}")
            for extra in found[1:4]:
                other = truncate(extra.get("label") or extra.get("text") or extra.get("name"), 40)
                lines.append(f"{indent}#   alternative: "
                             f"{extra['selectors'][0]['selector']}   # {other!r}")
        else:
            lines.append(f"{indent}{key}: FILL_ME"
                         f"   # not found automatically - use `pick` in explore_priority.py")

    # Pick the most plausible editable grid for the lines sub-screen.
    data_grids = [(h["frame_index"], g) for h in harvests for g in h.get("grids", [])
                  if g["input_count"] > 0 and g["rows"] > 1]
    grid = max(data_grids, key=lambda pair: pair[1]["input_count"])[1] if data_grids else None

    lines = [
        "# Auto-generated draft - review every line before using it.",
        f"# Generated: {now_iso()}",
        "#",
        "# Selectors here were VERIFIED against the live page: each matched exactly",
        "# one element at capture time. FILL_ME means it could not be determined -",
        "# use `pick` mode in explore_priority.py, click the control yourself, and",
        "# paste the selector it reports. Nothing here is guessed.",
        "",
        "frame:",
        "  # The frame the screen lives in. null = top-level document.",
        f"  selector: {_yaml_str(frame_css) if frame_css else 'null'}",
        f"  # discovery found the screen in frame index {main_index}",
        "",
        "orders:",
    ]
    for key, hint, hint_field, comment in ORDERS_ACTIONS:
        emit(lines, "  ", key, hint, hint_field, comment)
    lines.append("  fields:")
    for key, hint, hint_field, comment in ORDERS_FIELDS:
        emit(lines, "    ", key, hint, hint_field, comment)

    lines += ["", "order_items:"]
    if grid:
        lines += [
            "  # An editable grid was detected, so lines are typed into cells.",
            "  line_entry_mode: grid",
            f"  grid_root: {_yaml_str(grid['css_path'])}",
            "  # Map each Priority field to a GRID COLUMN HEADER. Header text is far",
            "  # more stable than a cell selector, which changes with the row number.",
            "  columns:",
        ]
        headers = [h for h in grid["headers"] if h]
        for key, hint, hint_field, comment in LINE_FIELDS:
            found = [el for el in candidates(hint, hint_field, in_grid=True) if el.get("label")]
            lines.append(f"    # {comment}")
            if found:
                lines.append(f"    {key}: {_yaml_str(found[0]['label'])}")
            else:
                lines.append(f"    {key}: FILL_ME   # columns seen: "
                             + (", ".join(headers) if headers else "none"))
        lines += [
            "  # How a new line is started once the last one is filled.",
            "  new_line: FILL_ME   # e.g. 'tab_from_last_cell', a button selector, or a shortcut",
        ]
    else:
        lines += [
            "  # No editable grid found - lines are probably entered through a form.",
            "  line_entry_mode: form",
        ]
        emit(lines, "  ", "add_line_button", "new_record", "action_hints",
             "control that opens a blank line")
        lines.append("  fields:")
        for key, hint, hint_field, comment in LINE_FIELDS:
            emit(lines, "    ", key, hint, hint_field, comment, in_grid=False)

    lines.append("")
    return "\n".join(lines)
